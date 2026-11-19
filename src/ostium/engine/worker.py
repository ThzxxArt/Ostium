"""Long-running data-plane worker.

The worker owns exactly one sing-box child. It observes a revision counter in
SQLite/PostgreSQL, regenerates configuration from the database, validates it
with the real binary, and applies it with rollback.
"""

from __future__ import annotations

import fcntl
import logging
import os
import signal
import threading
import time
from datetime import timedelta

from constance import config as runtime_config
from django.utils import timezone

from ostium import paths
from ostium.operations.models import RuntimeState
from ostium.operations.services import raise_alert, resolve_alert
from ostium.redaction import redact

from .config import ConfigError, check_config, generate_config, write_config
from .runtime import tail_file
from .stats import StatsSampler
from .supervisor import Supervisor, SupervisorError, disk_free_bytes, terminate_orphans, verify_binary

logger = logging.getLogger("ostium.engine.worker")


class Worker:
    def __init__(self) -> None:
        self.stop_event = threading.Event()
        self.supervisor = Supervisor()
        self.sampler = StatsSampler()
        self._lock_handle = None
        self.backoff_attempt = 0
        self.next_retry_at: float | None = None
        self.failed_revision: int | None = None
        self.last_flush = 0.0

    # -- lifecycle -------------------------------------------------------------

    def run(self) -> int:
        paths.ensure()
        if not self._acquire_lock():
            logger.error("another worker holds %s", paths.worker_lock_path())
            return 1

        ok, message = verify_binary()
        if not ok:
            raise_alert(
                code="singbox_binary_invalid",
                level="critical",
                message=f"The sing-box binary is not usable: {message}",
                fingerprint="singbox_binary_invalid",
            )
            logger.error("sing-box binary check failed: %s", message)
            self._release_lock()
            return 1

        logger.info("worker starting, %s", message)
        resolve_alert("singbox_binary_invalid")
        paths.worker_pid_path().write_text(str(os.getpid()), encoding="utf-8")
        self._install_signals()
        state = RuntimeState.load()
        state.last_error = ""
        state.save(update_fields=["last_error", "updated_at"])

        terminated = terminate_orphans()
        if terminated:
            logger.warning("terminated %d orphan sing-box process(es)", len(terminated))

        try:
            if not self._apply(force=True):
                logger.warning("initial configuration was not applied; retrying with backoff")
            self._loop()
        finally:
            self.shutdown()
        return 0

    def _install_signals(self) -> None:
        def handle(signum, frame):
            logger.info("received signal %s, stopping", signum)
            self.stop_event.set()

        signal.signal(signal.SIGTERM, handle)
        signal.signal(signal.SIGINT, handle)
        signal.signal(signal.SIGHUP, signal.SIG_IGN)

    def _loop(self) -> None:
        RuntimeState.load()
        last_heartbeat = 0.0
        last_sample = 0.0
        last_flush = 0.0
        last_limits = 0.0
        last_watchdog = 0.0
        last_maintenance = 0.0

        while not self.stop_event.wait(0.25):
            now_mono = time.monotonic()
            state = (
                RuntimeState.objects.filter(pk=1)
                .values("desired_revision", "applied_revision", "singbox_running")
                .first()
            )
            if state is None:
                continue

            if state["desired_revision"] > state["applied_revision"] or not paths.config_path().exists():
                if self._retry_allowed(state["desired_revision"]):
                    self._apply()
            elif not self.supervisor.running and now_mono - last_watchdog > 30:
                self._watchdog()
                last_watchdog = now_mono

            if now_mono - last_heartbeat >= 5:
                self._heartbeat()
                last_heartbeat = now_mono

            if now_mono - last_sample >= 5:
                self.sampler.sample()
                last_sample = now_mono

            if now_mono - last_flush >= 60:
                self.sampler.flush()
                last_flush = now_mono

            if now_mono - last_limits >= 30:
                from ostium.proxy.services import enforce_limits

                # Persist before enforcing so quota state, the database and the
                # generated configuration agree on the same counters.
                self.sampler.flush()
                enforce_limits()
                last_limits = now_mono

            if now_mono - last_maintenance >= 300:
                self._maintenance()
                last_maintenance = now_mono

            if self.sampler.failures >= 60 and self.sampler.failures % 60 == 0:
                raise_alert(
                    code="stats_unavailable",
                    level="critical",
                    message="Traffic statistics have been unavailable for more than five minutes.",
                    fingerprint="stats_unavailable",
                )

    def shutdown(self) -> None:
        logger.info("worker stopping")
        try:
            if self.sampler.initialized:
                self.sampler.sample()
        except Exception:
            logger.exception("final stats sample failed")
        try:
            self.sampler.flush()
        except Exception:
            logger.exception("final stats flush failed")
        try:
            self.supervisor.stop()
        finally:
            try:
                RuntimeState.objects.filter(pk=1).update(
                    singbox_running=False,
                    singbox_pid=None,
                    worker_heartbeat=timezone.now(),
                )
            except Exception:
                logger.exception("could not persist worker shutdown state")
            try:
                paths.worker_pid_path().unlink(missing_ok=True)
            except OSError:
                pass
            self._release_lock()

    # -- apply -----------------------------------------------------------------

    def _retry_allowed(self, desired_revision: int) -> bool:
        if self.next_retry_at is None or self.failed_revision != desired_revision:
            return True
        return time.monotonic() >= self.next_retry_at

    def _schedule_retry(self, desired_revision: int) -> None:
        self.backoff_attempt = min(self.backoff_attempt + 1, 6)
        delay = min(60, 2**self.backoff_attempt)
        self.next_retry_at = time.monotonic() + delay
        self.failed_revision = desired_revision
        logger.warning("configuration apply failed; retrying in %ss", delay)

    def _apply(self, *, force: bool = False) -> bool:
        if runtime_config.maintenance_mode:
            logger.info("maintenance mode enabled; configuration apply skipped")
            return False

        state = RuntimeState.load()
        desired = state.desired_revision
        if not force and state.applied_revision >= desired and paths.config_path().exists():
            return True

        logger.info("applying configuration revision %s", desired)
        try:
            result = generate_config(probe_dns=True)
        except ConfigError as exc:
            detail = "; ".join(exc.errors)
            self._record_failure(detail, desired)
            raise_alert(
                code="config_apply_failed",
                level="critical",
                message=f"Configuration generation failed: {detail}",
                fingerprint="config_apply_failed",
                detail={"errors": exc.errors[:20]},
            )
            self._schedule_retry(desired)
            return False

        next_path = paths.next_config_path()
        write_config(next_path, result)
        ok, output = check_config(str(self.supervisor.binary), next_path)
        if not ok:
            next_path.unlink(missing_ok=True)
            message = f"sing-box check rejected the configuration: {redact(output, max_length=1500)}"
            self._record_failure(message, desired)
            raise_alert(
                code="config_apply_failed",
                level="critical",
                message=message,
                fingerprint="config_apply_failed",
            )
            self._schedule_retry(desired)
            return False

        previous_path = paths.previous_config_path()
        config_path = paths.config_path()
        had_previous = config_path.exists()
        if had_previous:
            previous_path.write_bytes(config_path.read_bytes())
            paths.secure_file(previous_path)

        try:
            if self.sampler.initialized:
                self.sampler.sample()
            self.sampler.flush()
        except Exception:
            logger.exception("could not flush stats before restarting sing-box")
        self.supervisor.stop()
        try:
            pid = self.supervisor.start(next_path)
            time.sleep(1.0)
            if not self.supervisor.running:
                raise SupervisorError("sing-box exited immediately after startup.")
        except SupervisorError as exc:
            log_tail = redact(tail_file(paths.singbox_log_path(), max_bytes=8000)[-2000:])
            message = f"sing-box failed to start: {exc}. Log tail: {log_tail}"
            if had_previous:
                try:
                    self.supervisor.start(previous_path)
                    pid = self.supervisor.pid
                    message += " Rolled back to the previous configuration."
                except SupervisorError as rollback_exc:
                    message += f" Rollback also failed: {rollback_exc}"
                    pid = None
            else:
                pid = None
            next_path.unlink(missing_ok=True)
            self._record_failure(message, desired, pid=pid)
            raise_alert(
                code="config_apply_failed",
                level="critical",
                message=message[:2000],
                fingerprint="config_apply_failed",
            )
            self._schedule_retry(desired)
            return False

        os.replace(next_path, config_path)
        paths.secure_file(config_path)
        RuntimeState.objects.filter(pk=1).update(
            applied_revision=desired,
            config_sha256=result.sha256,
            singbox_pid=pid,
            singbox_running=True,
            singbox_started_at=timezone.now(),
            dns_mode_effective=result.effective_dns,
            last_error="",
            worker_heartbeat=timezone.now(),
        )
        resolve_alert("config_apply_failed")
        resolve_alert("singbox_down")
        self.backoff_attempt = 0
        self.next_retry_at = None
        self.failed_revision = None
        logger.info("configuration applied revision=%s sha256=%s dns=%s", desired, result.sha256, result.effective_dns)
        if result.warnings:
            for warning in result.warnings:
                logger.warning(warning)
                raise_alert(
                    code="dns_fallback",
                    level="warning",
                    message=warning,
                    fingerprint="dns_fallback",
                )
        else:
            resolve_alert("dns_fallback")
        return True

    def _record_failure(self, message: str, desired: int, *, pid: int | None = None) -> None:
        logger.error("configuration apply failed: %s", message)
        RuntimeState.load()
        RuntimeState.objects.filter(pk=1).update(
            last_error=message[:4000],
            singbox_running=self.supervisor.running,
            singbox_pid=self.supervisor.pid or pid,
            worker_heartbeat=timezone.now(),
        )

    # -- routine checks --------------------------------------------------------

    def _heartbeat(self) -> None:
        state = RuntimeState.load()
        RuntimeState.objects.filter(pk=1).update(
            worker_heartbeat=timezone.now(),
            singbox_running=self.supervisor.running,
            singbox_pid=self.supervisor.pid,
        )
        if state.last_error:
            logger.debug("last config error: %s", state.last_error[:200])

    def _watchdog(self) -> None:
        if self.supervisor.running:
            return
        logger.warning("sing-box is not running; attempting recovery")
        raise_alert(
            code="singbox_down",
            level="critical",
            message="The sing-box process is not running.",
            fingerprint="singbox_down",
        )
        config_path = paths.config_path()
        if config_path.exists():
            try:
                self.supervisor.start(config_path)
                RuntimeState.load()
                RuntimeState.objects.filter(pk=1).update(
                    singbox_running=True,
                    singbox_pid=self.supervisor.pid,
                    singbox_started_at=timezone.now(),
                )
                resolve_alert("singbox_down")
                return
            except SupervisorError as exc:
                logger.error("recovery failed: %s", exc)
        RuntimeState.mark_desired()

    def _maintenance(self) -> None:
        self._check_certificates()
        self._check_disk()
        self._check_inbounds()
        self._retention()
        self._maybe_backup()

    def _check_inbounds(self) -> None:
        state = RuntimeState.load()
        if not state.singbox_running:
            return
        started = state.singbox_started_at
        if started and (timezone.now() - started).total_seconds() < 15:
            return
        from ostium.proxy.health import check_inbounds

        for health in check_inbounds(singbox_running=True):
            fingerprint = f"inbound_health:{health.kind}"
            if health.status != "fail":
                resolve_alert(fingerprint)
                continue
            raise_alert(
                code="inbound_unhealthy",
                level="warning",
                message=f"{health.label} 线路异常：{health.detail}",
                fingerprint=fingerprint,
                detail={"kind": health.kind, "detail": health.detail, "fix": health.fix},
            )

    def _check_certificates(self) -> None:
        from ostium.certificates.models import Certificate
        from ostium.certificates.services import refresh_status

        for certificate in Certificate.objects.all():
            refresh_status(certificate)
            expired_fingerprint = f"certificate_expired:{certificate.pk}"
            expiring_fingerprint = f"certificate_expiring:{certificate.pk}"
            if certificate.is_expired:
                resolve_alert(expiring_fingerprint)
                raise_alert(
                    code="certificate_expired",
                    level="critical",
                    message=f"Certificate for {certificate.domain} has expired.",
                    fingerprint=expired_fingerprint,
                )
            else:
                resolve_alert(expired_fingerprint)
                if certificate.days_remaining <= 30:
                    raise_alert(
                        code="certificate_expiring",
                        level="warning",
                        message=f"Certificate for {certificate.domain} expires in {certificate.days_remaining} days.",
                        fingerprint=expiring_fingerprint,
                    )
                else:
                    resolve_alert(expiring_fingerprint)

    def _check_disk(self) -> None:
        free = disk_free_bytes()
        if free < 1024**3:
            raise_alert(
                code="disk_low",
                level="critical",
                message=f"Less than 1 GiB free under {paths.data_dir()}.",
                fingerprint="disk_low",
                detail={"free_bytes": free},
            )
        else:
            resolve_alert("disk_low")

    def _retention(self) -> None:
        from datetime import timedelta

        from ostium.operations.models import AuditEvent, Backup
        from ostium.proxy.models import TrafficDaily

        traffic_days = max(1, int(runtime_config.traffic_retention_days or 90))
        audit_days = max(1, int(runtime_config.audit_retention_days or 365))
        keep = max(1, int(runtime_config.auto_backup_keep or 7))
        TrafficDaily.objects.filter(day__lt=timezone.localdate() - timedelta(days=traffic_days)).delete()
        AuditEvent.objects.filter(created_at__lt=timezone.now() - timedelta(days=audit_days)).delete()
        automatic = list(Backup.objects.filter(note__startswith="auto:").order_by("-created_at", "-id"))
        for old_backup in automatic[keep:]:
            try:
                (paths.backups_dir() / old_backup.filename).unlink(missing_ok=True)
            except OSError:
                pass
            old_backup.delete()

    def _maybe_backup(self) -> None:
        if not runtime_config.auto_backup_enabled:
            return
        from ostium.operations.backup import create_backup, get_backup_password

        password = get_backup_password()
        if not password:
            raise_alert(
                code="backup_failed",
                level="warning",
                message="Automatic backup is enabled but no backup password is configured.",
                fingerprint="backup_failed:password",
            )
            return
        resolve_alert("backup_failed:password")

        last = None
        from ostium.operations.models import Backup

        last = Backup.objects.filter(note__startswith="auto:").order_by("-created_at").first()
        if last and timezone.now() - last.created_at < timedelta(hours=23):
            return
        from ostium.operations.services import record_audit

        try:
            backup = create_backup(password=password, note="auto:worker")
            record_audit(
                action="backup.created",
                target=backup.filename,
                detail={"note": "auto:worker", "size": backup.size},
            )
            resolve_alert("backup_failed:run")
        except Exception as exc:
            logger.exception("automatic backup failed")
            record_audit(
                action="backup.failed",
                detail={"note": "auto:worker", "error": str(exc)[:500]},
            )
            raise_alert(
                code="backup_failed",
                level="critical",
                message=f"Automatic backup failed: {exc}",
                fingerprint="backup_failed:run",
            )

    # -- locking ---------------------------------------------------------------

    def _acquire_lock(self) -> bool:
        paths.ensure()
        self._lock_handle = paths.worker_lock_path().open("a+")
        try:
            fcntl.flock(self._lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self._lock_handle.close()
            self._lock_handle = None
            return False
        return True

    def _release_lock(self) -> None:
        if self._lock_handle is None:
            return
        try:
            fcntl.flock(self._lock_handle.fileno(), fcntl.LOCK_UN)
        finally:
            self._lock_handle.close()
            self._lock_handle = None


def run_worker() -> int:
    return Worker().run()


__all__ = ["Worker", "run_worker"]
