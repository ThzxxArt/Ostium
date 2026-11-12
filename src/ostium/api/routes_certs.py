"""Certificate issuance, upload, renewal and assignment."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ostium.acme.client import AcmeIssuer
from ostium.api.deps import Services, client_ip, get_current_admin, get_services, get_session
from ostium.api.errors import ApiError
from ostium.db.models import AdminUser, Certificate
from ostium.services import certificates as cert_service
from ostium.services.audit import audit
from ostium.services.jobs import JobContext

router = APIRouter(tags=["certificates"])


class IssueRequest(BaseModel):
    domain: str = Field(min_length=1, max_length=253)
    method: Literal["acme", "self-signed"] = "acme"
    auto_renew: bool = True


class UploadRequest(BaseModel):
    domain: str = Field(min_length=1, max_length=253)
    cert_pem: str
    key_pem: str
    auto_renew: bool = False


class UseRequest(BaseModel):
    kinds: list[str] = Field(default_factory=lambda: ["hysteria2", "trojan"])


async def _apply_server(services: Services, session: AsyncSession) -> dict[str, Any]:
    try:
        result = await services.engine.apply_server(session)
        return {"applied": True, "revision": result["status"].get("revision")}
    except Exception as exc:
        return {"applied": False, "warning": str(exc)}


@router.get("/certificates")
async def list_certificates(
    _: AdminUser = Depends(get_current_admin),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    rows = await cert_service.list_certificates(session)
    return {"certificates": [cert_service.serialize_certificate(row) for row in rows]}


@router.post("/certificates/issue", status_code=202)
async def issue_certificate(
    payload: IssueRequest,
    request: Request,
    admin: AdminUser = Depends(get_current_admin),
    services: Services = Depends(get_services),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    domain = payload.domain.strip().lower()
    try:
        domain = cert_service.validate_domain(domain)
    except cert_service.CertificateError as exc:
        raise ApiError(exc.status_code, str(exc), exc.code) from exc
    if payload.method == "self-signed":
        try:
            certificate = await cert_service.create_self_signed(
                session, services.settings, domain=domain
            )
        except cert_service.CertificateError as exc:
            raise ApiError(exc.status_code, str(exc), exc.code) from exc
        certificate.auto_renew = False
        await session.flush()
        await cert_service.use_for_inbounds(session, certificate)
        applied = await _apply_server(services, session)
        await audit(
            session,
            actor=admin.username,
            action="certificate.self_signed",
            target=domain,
            ip=client_ip(request),
        )
        return {
            "certificate": cert_service.serialize_certificate(certificate),
            "method": "self-signed",
            **applied,
        }
    existing = (
        await session.execute(select(Certificate).where(Certificate.domain == domain))
    ).scalar_one_or_none()
    if existing is not None:
        existing.status = "pending"
        existing.last_error = None
        existing.auto_renew = payload.auto_renew
        certificate_id = existing.id
    else:
        placeholder_dir = services.settings.paths.certs_dir / domain
        certificate = Certificate(
            domain=domain,
            cert_path=str(placeholder_dir / "fullchain.pem"),
            key_path=str(placeholder_dir / "privkey.pem"),
            status="pending",
            source="acme",
            auto_renew=payload.auto_renew,
        )
        session.add(certificate)
        await session.flush()
        certificate_id = certificate.id
    await session.commit()

    async def job(context: JobContext) -> dict[str, Any]:
        await context.progress(10, "creating ACME order")
        issuer = AcmeIssuer(services.settings, services.store)
        fullchain, key_pem = await issuer.issue(domain)
        await context.progress(75, "storing certificate")
        async with services.session_factory() as job_session:
            cert = await job_session.get(Certificate, certificate_id)
            if cert is None:
                raise RuntimeError("certificate row disappeared during issuance")
            await cert_service.import_manual(
                job_session,
                services.settings,
                domain=domain,
                cert_pem=fullchain,
                key_pem=key_pem,
                source="acme",
            )
            cert.auto_renew = payload.auto_renew
            await cert_service.use_for_inbounds(job_session, cert)
            await job_session.commit()
            try:
                await services.engine.apply_server(job_session)
            except Exception as exc:
                services.bus.log(
                    "warning", "certificate stored but engine apply failed", error=str(exc)
                )
        await context.progress(100, "certificate ready")
        return {"domain": domain}

    job_row = await services.jobs.submit(
        "acme.issue", job, message=f"issue certificate for {domain}"
    )
    await audit(
        session,
        actor=admin.username,
        action="certificate.acme_requested",
        target=domain,
        ip=client_ip(request),
        detail={"job_id": job_row.id},
    )
    return {"job_id": job_row.id, "status": "pending", "domain": domain}


@router.post("/certificates/upload")
async def upload_certificate(
    payload: UploadRequest,
    request: Request,
    admin: AdminUser = Depends(get_current_admin),
    services: Services = Depends(get_services),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    try:
        certificate = await cert_service.import_manual(
            session,
            services.settings,
            domain=payload.domain,
            cert_pem=payload.cert_pem,
            key_pem=payload.key_pem,
        )
    except cert_service.CertificateError as exc:
        raise ApiError(exc.status_code, str(exc), exc.code) from exc
    certificate.auto_renew = payload.auto_renew
    await cert_service.use_for_inbounds(session, certificate)
    applied = await _apply_server(services, session)
    await audit(
        session,
        actor=admin.username,
        action="certificate.uploaded",
        target=payload.domain,
        ip=client_ip(request),
    )
    return {"certificate": cert_service.serialize_certificate(certificate), **applied}


@router.post("/certificates/{certificate_id}/renew", status_code=202)
async def renew_certificate(
    certificate_id: str,
    request: Request,
    admin: AdminUser = Depends(get_current_admin),
    services: Services = Depends(get_services),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    certificate = await session.get(Certificate, certificate_id)
    if certificate is None:
        raise ApiError(404, "certificate not found", "not_found")
    if certificate.source != "acme":
        raise ApiError(400, "only ACME certificates can be renewed automatically", "not_acme")
    domain = certificate.domain

    async def job(context: JobContext) -> dict[str, Any]:
        await context.progress(10, "creating ACME order")
        issuer = AcmeIssuer(services.settings, services.store)
        fullchain, key_pem = await issuer.issue(domain)
        await context.progress(80, "storing renewed certificate")
        async with services.session_factory() as job_session:
            await cert_service.import_manual(
                job_session,
                services.settings,
                domain=domain,
                cert_pem=fullchain,
                key_pem=key_pem,
                source="acme",
            )
            await job_session.commit()
            try:
                await services.engine.apply_server(job_session)
            except Exception as exc:
                services.bus.log("warning", "renewed certificate apply failed", error=str(exc))
        return {"domain": domain}

    row = await services.jobs.submit("acme.renew", job, message=f"renew certificate for {domain}")
    await audit(
        session,
        actor=admin.username,
        action="certificate.renew_requested",
        target=domain,
        ip=client_ip(request),
        detail={"job_id": row.id},
    )
    return {"job_id": row.id, "status": "pending"}


@router.post("/certificates/{certificate_id}/use")
async def use_certificate(
    certificate_id: str,
    payload: UseRequest,
    request: Request,
    admin: AdminUser = Depends(get_current_admin),
    services: Services = Depends(get_services),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    certificate = await session.get(Certificate, certificate_id)
    if certificate is None:
        raise ApiError(404, "certificate not found", "not_found")
    await cert_service.use_for_inbounds(session, certificate, kinds=payload.kinds)
    applied = await _apply_server(services, session)
    await audit(
        session,
        actor=admin.username,
        action="certificate.assigned",
        target=certificate.domain,
        ip=client_ip(request),
        detail={"kinds": payload.kinds},
    )
    return {"ok": True, **applied}


@router.delete("/certificates/{certificate_id}")
async def delete_certificate(
    certificate_id: str,
    request: Request,
    admin: AdminUser = Depends(get_current_admin),
    services: Services = Depends(get_services),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    certificate = await session.get(Certificate, certificate_id)
    if certificate is None:
        raise ApiError(404, "certificate not found", "not_found")
    domain = certificate.domain
    await cert_service.delete_certificate(session, certificate)
    applied = await _apply_server(services, session)
    await audit(
        session,
        actor=admin.username,
        action="certificate.deleted",
        target=domain,
        ip=client_ip(request),
    )
    return {"deleted": True, **applied}
