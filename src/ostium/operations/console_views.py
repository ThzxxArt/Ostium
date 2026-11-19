"""Aurora console views."""

from __future__ import annotations

import re
import shutil
import time
from datetime import timedelta

import psutil
from django.conf import settings
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.core.paginator import Paginator
from django.db import connection
from django.db.models import Q, Sum
from django.http import Http404, HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from django_q.models import Task

from ostium import paths
from ostium.certificates.forms import CertificateImportForm
from ostium.certificates.models import Certificate
from ostium.certificates.services import import_certificate
from ostium.engine.clash import ClashClient, ClashError
from ostium.engine.runtime import read_usage, tail_file
from ostium.engine.supervisor import binary_version, disk_free_bytes
from ostium.formatting import format_bytes
from ostium.operations.backup import create_backup
from ostium.operations.diagnostics import build_diagnostics
from ostium.operations.doctor import doctor_summary, run_doctor
from ostium.operations.forms import BackupForm, InboundForm, SettingsForm, UserEditForm
from ostium.operations.models import Alert, AuditEvent, Backup, RuntimeState
from ostium.operations.services import record_audit
from ostium.proxy.models import Inbound, ProxyUser, TrafficDaily
from ostium.proxy.services import mark_dirty
from ostium.subscriptions.endpoints import build_endpoints
from ostium.subscriptions.services import (
    masked_token,
    public_host,
    qr_data_uri,
    subscription_links,
    subscription_url,
    userinfo_header,
)
from ostium.version import BUILD_COMMIT, BUILD_DATE, __version__


def _page(request, queryset, per_page: int = 20):
    return Paginator(queryset, per_page).get_page(request.GET.get("page"))


def _fill_series(days: int, *, user: ProxyUser | None = None) -> list[dict]:
    start = timezone.localdate() - timedelta(days=days - 1)
    queryset = TrafficDaily.objects.filter(day__gte=start)
    if user is not None:
        queryset = queryset.filter(user=user)
    rows = queryset.values("day").annotate(uplink=Sum("uplink"), downlink=Sum("downlink")).order_by("day")
    by_day = {row["day"]: row for row in rows}
    series = []
    for offset in range(days):
        day = start + timedelta(days=offset)
        row = by_day.get(day, {"uplink": 0, "downlink": 0})
        series.append(
            {
                "day": day.isoformat(),
                "label": day.strftime("%m-%d"),
                "uplink": row["uplink"] or 0,
                "downlink": row["downlink"] or 0,
            }
        )
    return series


@staff_member_required(login_url="accounts:login")
def dashboard(request):
    state = RuntimeState.load()
    usage = read_usage()
    now = timezone.now()
    today_totals = TrafficDaily.objects.filter(day=timezone.localdate()).aggregate(
        up=Sum("uplink"), down=Sum("downlink")
    )
    online_users = list(ProxyUser.objects.filter(last_seen_at__gte=now - timedelta(seconds=60)))
    top_online = []
    for user in online_users:
        item = usage.get("users", {}).get(user.name, {})
        top_online.append(
            {
                "user": user,
                "uplink_rate": item.get("uplink_rate", 0),
                "downlink_rate": item.get("downlink_rate", 0),
            }
        )
    top_online.sort(key=lambda item: item["uplink_rate"] + item["downlink_rate"], reverse=True)
    total_uplink_rate = sum(item.get("uplink_rate", 0) for item in usage.get("users", {}).values())
    total_downlink_rate = sum(item.get("downlink_rate", 0) for item in usage.get("users", {}).values())

    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        db_ok = True
    except Exception:
        db_ok = False
    free = disk_free_bytes()
    certificates = list(Certificate.objects.all())
    soon = sorted([cert for cert in certificates if cert.days_remaining <= 30], key=lambda c: c.expires_at)
    health = [
        {
            "name": "Database",
            "status": "pass" if db_ok else "fail",
            "detail": settings.DATABASES["default"]["ENGINE"].rsplit(".", 1)[-1],
        },
        {
            "name": "Worker",
            "status": "pass" if state.worker_alive else "fail",
            "detail": f"heartbeat {state.heartbeat_age:.0f}s" if state.heartbeat_age is not None else "no heartbeat",
        },
        {
            "name": "sing-box",
            "status": "pass" if state.singbox_running else "fail",
            "detail": f"PID {state.singbox_pid}" if state.singbox_pid else "stopped",
        },
        {
            "name": "Disk",
            "status": "pass" if free > 1024**3 else "fail",
            "detail": f"{format_bytes(free)} free",
        },
        {
            "name": "Statistics",
            "status": "pass" if usage.get("stats_ok") else "warn",
            "detail": "live" if usage.get("stats_ok") else "unavailable",
        },
        {
            "name": "Certificates",
            "status": "warn" if soon else "pass",
            "detail": f"{len(soon)} expiring" if soon else "all healthy",
        },
    ]
    context = {
        "active_nav": "dashboard",
        "state": state,
        "usage": usage,
        "online_count": len(online_users),
        "users_total": ProxyUser.objects.count(),
        "users_enabled": ProxyUser.objects.filter(enabled=True).count(),
        "today_uplink": today_totals["up"] or 0,
        "today_downlink": today_totals["down"] or 0,
        "today_total": (today_totals["up"] or 0) + (today_totals["down"] or 0),
        "total_uplink_rate": total_uplink_rate,
        "total_downlink_rate": total_downlink_rate,
        "series": _fill_series(7),
        "top_online": top_online[:5],
        "health": health,
        "alerts": Alert.objects.filter(acknowledged_at__isnull=True)[:5],
        "jobs": Task.objects.all().order_by("-started")[:5],
        "certificates_soon": soon[:3],
        "uptime_seconds": (now - state.singbox_started_at).total_seconds() if state.singbox_started_at else None,
        "pending_apply": state.desired_revision > state.applied_revision,
    }
    return render(request, "console/dashboard.html", context)


@staff_member_required(login_url="accounts:login")
def users(request):
    queryset = ProxyUser.objects.all()
    query = request.GET.get("q", "").strip()
    status = request.GET.get("status", "all")
    now = timezone.now()
    if query:
        queryset = queryset.filter(Q(name__icontains=query) | Q(note__icontains=query))
    if status == "active":
        queryset = (
            queryset.filter(enabled=True)
            .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))
            .filter(Q(quota_bytes=0) | Q(used_bytes__lt=models_f("quota_bytes")))
        )
    elif status == "disabled":
        queryset = queryset.filter(enabled=False)
    elif status == "expired":
        queryset = queryset.filter(enabled=True, expires_at__lte=now)
    elif status == "quota":
        queryset = queryset.filter(enabled=True, quota_bytes__gt=0).filter(used_bytes__gte=models_f("quota_bytes"))
    elif status == "online":
        queryset = queryset.filter(last_seen_at__gte=now - timedelta(seconds=60))

    sort = request.GET.get("sort", "name")
    sort_map = {
        "name": "name",
        "-name": "-name",
        "used": "used_bytes",
        "-used": "-used_bytes",
        "created": "created_at",
        "-created": "-created_at",
        "seen": "last_seen_at",
        "-seen": "-last_seen_at",
    }
    queryset = queryset.order_by(sort_map.get(sort, "name"))
    page = _page(request, queryset)
    usage = read_usage().get("users", {})
    for user in page:
        user.live = usage.get(user.name, {})
    return render(
        request,
        "console/users.html",
        {
            "active_nav": "users",
            "page": page,
            "query": query,
            "status": status,
            "sort": sort,
            "total": queryset.count(),
            "inbounds": Inbound.objects.filter(enabled=True),
        },
    )


def models_f(name: str):
    from django.db.models import F

    return F(name)


@staff_member_required(login_url="accounts:login")
@require_http_methods(["GET", "POST"])
def user_detail(request, user_id):
    user = get_object_or_404(ProxyUser, pk=user_id)
    revealed = False
    form = UserEditForm(instance=user)

    if request.method == "POST":
        action = request.POST.get("action", "save")
        if action == "save":
            form = UserEditForm(request.POST, instance=user)
            if form.is_valid():
                form.save()
                record_audit(action="user.updated", request=request, target=user.name)
                messages.success(request, "用户设置已保存，核心配置将在数秒内应用。")
                return redirect("console:user_detail", user_id=user.pk)
        elif action == "reveal":
            revealed = True
            record_audit(action="subscription.revealed", request=request, target=user.name)
        elif action == "rotate_subscription":
            user.rotate_subscription_token()
            record_audit(action="subscription.rotated", request=request, target=user.name)
            revealed = True
            messages.success(request, "订阅 token 已轮换，旧链接立即失效。")
            form = UserEditForm(instance=user)
        elif action == "rotate_credentials":
            user.rotate_credentials()
            record_audit(action="user.credentials_rotated", request=request, target=user.name)
            messages.success(request, "凭据已轮换，客户端需要重新导入订阅。")
            form = UserEditForm(instance=user)
        elif action == "reset_usage":
            user.reset_usage()
            record_audit(action="user.usage_reset", request=request, target=user.name)
            messages.success(request, "流量计数已重置。")
            form = UserEditForm(instance=user)
        elif action == "delete":
            name = user.name
            user.delete()
            record_audit(action="user.deleted", request=request, target=name)
            messages.success(request, f"用户 {name} 已删除。")
            return redirect("console:users")
        else:
            return HttpResponseBadRequest("Unknown action.")

    links = subscription_links(user, request) if revealed else []
    endpoints = build_endpoints(user, public_host(request)) if revealed else []
    context = {
        "active_nav": "users",
        "user": user,
        "form": form,
        "revealed": revealed,
        "token": user.reveal_subscription_token() if revealed else masked_token(user),
        "links": links,
        "endpoints": endpoints,
        "qr": qr_data_uri(subscription_url(user, "base64", request)) if revealed else "",
        "userinfo": userinfo_header(user),
        "series": _fill_series(30, user=user),
        "audit_events": AuditEvent.objects.filter(target=user.name)[:20],
        "live": read_usage().get("users", {}).get(user.name, {}),
    }
    return render(request, "console/user_detail.html", context)


@staff_member_required(login_url="accounts:login")
@require_http_methods(["GET", "POST"])
def inbounds(request):
    records = list(Inbound.objects.select_related("certificate").all())
    forms = {record.kind: InboundForm(instance=record, prefix=record.kind) for record in records}
    if request.method == "POST":
        kind = request.POST.get("kind")
        record = next((item for item in records if item.kind == kind), None)
        if record is None:
            raise Http404("Unknown inbound")
        if request.POST.get("action") == "rotate_keys":
            record.rotate_keys()
            record_audit(action="inbound.keys_rotated", request=request, target=kind)
            messages.success(request, f"{record.short_label} 密钥已轮换，客户端需要重新导入订阅。")
            return redirect("console:inbounds")
        form = InboundForm(request.POST, instance=record, prefix=kind)
        if form.is_valid():
            form.save()
            record_audit(action="inbound.updated", request=request, target=kind)
            messages.success(request, f"{record.short_label} 已保存，配置将在数秒内应用。")
            return redirect("console:inbounds")
        forms[kind] = form
    return render(
        request,
        "console/inbounds.html",
        {
            "active_nav": "inbounds",
            "records": records,
            "forms": forms,
            "state": RuntimeState.load(),
        },
    )


@staff_member_required(login_url="accounts:login")
def subscriptions(request):
    queryset = ProxyUser.objects.all().order_by("name")
    query = request.GET.get("q", "").strip()
    if query:
        queryset = queryset.filter(name__icontains=query)
    page = _page(request, queryset, per_page=25)
    for user in page:
        user.token_masked = masked_token(user)
        user.subscription_url = subscription_url(user, "base64", request)
    return render(
        request,
        "console/subscriptions.html",
        {
            "active_nav": "subscriptions",
            "page": page,
            "query": query,
            "enabled_inbounds": Inbound.objects.filter(enabled=True).count(),
        },
    )


@staff_member_required(login_url="accounts:login")
@require_http_methods(["GET", "POST"])
def connections(request):
    client = ClashClient()
    error = ""
    items: list[dict] = []
    if request.method == "POST":
        action = request.POST.get("action")
        try:
            if action == "close_all":
                client.close_all()
                record_audit(action="connections.closed_all", request=request)
                messages.success(request, "已关闭全部连接。")
            elif action == "close" and request.POST.get("connection_id"):
                client.close_connection(request.POST["connection_id"])
                record_audit(action="connection.closed", request=request, target=request.POST["connection_id"])
                messages.success(request, "连接已关闭。")
        except ClashError as exc:
            messages.error(request, f"核心 API 不可用：{exc}")
        return redirect("console:connections")

    query = request.GET.get("q", "").strip().lower()
    try:
        items = client.connections()
        if query:
            items = [
                item
                for item in items
                if query in (item["user"] + item["host"] + item["network"] + item["inbound"]).lower()
            ]
        items = items[:300]
    except ClashError as exc:
        error = str(exc)
    return render(
        request,
        "console/connections.html",
        {"active_nav": "connections", "connections": items, "error": error, "query": query},
    )


@staff_member_required(login_url="accounts:login")
@require_http_methods(["GET", "POST"])
def certificate_import(request):
    form = CertificateImportForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        try:
            certificate = import_certificate(
                domain=form.cleaned_data["domain"],
                cert_pem=form.cleaned_data["certificate"],
                key_pem=form.cleaned_data["private_key"],
                auto_renew=form.cleaned_data["auto_renew"],
                actor=request.user,
            )
        except Exception as exc:
            form.add_error(None, str(exc))
        else:
            record_audit(action="certificate.imported", request=request, target=certificate.domain)
            messages.success(request, f"证书 {certificate.domain} 已导入。")
            return redirect("console:certificates")
    return render(
        request,
        "console/certificate_import.html",
        {"active_nav": "certificates", "form": form},
    )


@staff_member_required(login_url="accounts:login")
@require_http_methods(["GET", "POST"])
def certificates(request):
    if request.method == "POST":
        if request.POST.get("action") == "sync_certbot":
            from ostium.certificates.services import sync_directory

            source = paths.imports_dir() / "letsencrypt"
            try:
                certificates = sync_directory(source)
            except Exception as exc:
                messages.error(request, f"certbot 证书同步失败：{exc}")
            else:
                record_audit(
                    action="certificate.certbot_synced",
                    request=request,
                    target=str(source),
                    detail={"domains": [item.domain for item in certificates]},
                )
                messages.success(request, f"已同步 {len(certificates)} 张 certbot 证书。")
            return redirect("console:certificates")

        certificate = get_object_or_404(Certificate, pk=request.POST.get("certificate_id"))
        from ostium.certificates.services import refresh_status

        refresh_status(certificate)
        record_audit(action="certificate.refreshed", request=request, target=certificate.domain)
        messages.success(request, "证书状态已刷新。")
        return redirect("console:certificates")
    records = list(Certificate.objects.all().prefetch_related("inbounds"))
    return render(
        request,
        "console/certificates.html",
        {
            "active_nav": "certificates",
            "records": records,
            "import_url": reverse("console:certificate_import"),
        },
    )


_LOG_LEVEL_RE = re.compile(r"\b(FATAL|ERROR|WARN|INFO|DEBUG|TRACE)\b")


@staff_member_required(login_url="accounts:login")
def logs(request):
    source = request.GET.get("source", "sing-box")
    if source not in {"sing-box", "ostium"}:
        raise Http404("Unknown log source")
    path = paths.singbox_log_path() if source == "sing-box" else paths.ostium_log_path()
    content = tail_file(path, max_bytes=2 * 1024 * 1024)
    if request.GET.get("download") == "1":
        response = HttpResponse(content, content_type="text/plain; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="{source}.log"'
        return response
    query = request.GET.get("q", "").strip()
    lines = content.splitlines()
    if query:
        lines = [line for line in lines if query.lower() in line.lower()]
    lines = lines[-2000:]
    rendered = []
    for line in lines:
        match = _LOG_LEVEL_RE.search(line)
        level = match.group(1).lower() if match else ""
        rendered.append({"text": line, "level": level})
    return render(
        request,
        "console/logs.html",
        {
            "active_nav": "logs",
            "source": source,
            "lines": rendered,
            "query": query,
            "bytes": len(content),
            "path": str(path),
        },
    )


@staff_member_required(login_url="accounts:login")
@require_http_methods(["GET", "POST"])
def jobs(request):
    if request.method == "POST" and request.POST.get("action") == "cancel":
        from ostium.operations.services import cancel_queued_job

        task_id = request.POST.get("task_id", "")
        if cancel_queued_job(task_id):
            record_audit(action="job.cancelled", request=request, target=task_id)
            messages.success(request, "任务已从队列移除。")
        else:
            messages.warning(request, "任务已经开始或不在队列中，无法取消。")
        return redirect("console:jobs")
    from django_q.models import OrmQ

    queryset = Task.objects.all().order_by("-started")
    queued = list(OrmQ.objects.all()[:100])
    return render(
        request,
        "console/jobs.html",
        {"active_nav": "jobs", "page": _page(request, queryset, 30), "queued": queued},
    )


@staff_member_required(login_url="accounts:login")
@require_http_methods(["GET", "POST"])
def system(request):
    if request.GET.get("download") == "diagnostics":
        payload = build_diagnostics()
        record_audit(action="diagnostics.exported", request=request)
        response = HttpResponse(payload, content_type="application/gzip")
        timestamp = timezone.now().strftime("%Y%m%d-%H%M%S")
        response["Content-Disposition"] = f'attachment; filename="ostium-diagnostics-{timestamp}.tar.gz"'
        return response

    form = BackupForm()
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "restart_core":
            mark_dirty()
            record_audit(action="engine.restart_requested", request=request)
            messages.success(request, "已请求应用最新配置。")
            return redirect("console:system")
        if action == "backup":
            form = BackupForm(request.POST)
            if form.is_valid():
                try:
                    backup = create_backup(
                        password=form.cleaned_data["password"],
                        note=form.cleaned_data["note"],
                        actor=request.user,
                    )
                except Exception as exc:
                    form.add_error(None, str(exc))
                else:
                    record_audit(action="backup.created", request=request, target=backup.filename)
                    messages.success(request, f"备份已创建：{backup.filename}")
                    return redirect("console:system")

    checks = run_doctor()
    memory = psutil.virtual_memory()
    disk = shutil.disk_usage(paths.data_dir())
    state = RuntimeState.load()
    return render(
        request,
        "console/system.html",
        {
            "active_nav": "system",
            "checks": checks,
            "summary": doctor_summary(checks),
            "state": state,
            "form": form,
            "backups": Backup.objects.all()[:10],
            "memory": memory,
            "disk": disk,
            "cpu_percent": psutil.cpu_percent(interval=0.05),
            "loadavg": psutil.getloadavg() if hasattr(psutil, "getloadavg") else (0, 0, 0),
            "uptime": time.time() - psutil.boot_time(),
            "singbox_version": binary_version(),
            "version": __version__,
            "build_commit": BUILD_COMMIT,
            "build_date": BUILD_DATE,
        },
    )


@staff_member_required(login_url="accounts:login")
@require_http_methods(["GET", "POST"])
def settings_view(request):
    if request.method == "POST":
        form = SettingsForm(request.POST)
        if form.is_valid():
            updated = form.save()
            mark_dirty()
            record_audit(action="settings.updated", request=request, detail={"keys": updated})
            messages.success(request, "设置已保存，核心配置将在数秒内应用。")
            return redirect("console:settings")
    else:
        form = SettingsForm()
    groups = {
        "General": ["server_name", "public_host", "public_base_url", "subscription_update_interval"],
        "Network": ["server_dns_mode", "server_dns_doh_url", "block_private_egress", "log_level"],
        "Security": ["maintenance_mode"],
        "Notifications": ["webhook_url", "webhook_secret"],
        "Maintenance": [
            "traffic_retention_days",
            "audit_retention_days",
            "auto_backup_enabled",
            "auto_backup_keep",
        ],
    }
    return render(
        request,
        "console/settings.html",
        {"active_nav": "settings", "form": form, "groups": groups, "state": RuntimeState.load()},
    )


@staff_member_required(login_url="accounts:login")
@require_http_methods(["POST"])
def alert_ack(request, alert_id):
    from ostium.operations.services import acknowledge_alert

    alert = get_object_or_404(Alert, pk=alert_id)
    acknowledge_alert(alert)
    record_audit(action="alert.acknowledged", request=request, target=alert.code)
    messages.success(request, "告警已确认。")
    return redirect("console:dashboard")


@staff_member_required(login_url="accounts:login")
def audit(request):
    queryset = AuditEvent.objects.select_related("actor")
    action_filter = request.GET.get("action", "").strip()
    actor = request.GET.get("actor", "").strip()
    target = request.GET.get("target", "").strip()
    if action_filter:
        queryset = queryset.filter(action__startswith=action_filter)
    if actor:
        queryset = queryset.filter(actor__username__icontains=actor)
    if target:
        queryset = queryset.filter(target__icontains=target)
    return render(
        request,
        "console/audit.html",
        {
            "active_nav": "audit",
            "page": _page(request, queryset, 50),
            "action_filter": action_filter,
            "actor": actor,
            "target": target,
            "actions": AuditEvent.objects.values_list("action", flat=True).distinct().order_by("action")[:50],
        },
    )
