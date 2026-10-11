"""Durable SQLite-backed job state and a small in-process worker pool.

SQLite owns job state and event history. The in-memory map below contains only
process-local cancellation signals and Future handles; a process restart can
therefore recover visible state without pretending that Python workers survived.
"""

from __future__ import annotations

import asyncio
import contextvars
import datetime as dt
import json
import logging
import re
import threading
from pathlib import Path
import time
import uuid
from threading import BoundedSemaphore
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Iterable

from fastapi import WebSocket
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from server.core.database import Job, JobEvent, JobStep, Project, SessionLocal, session_scope, utcnow


MAX_EVENTS_PER_JOB = 1000
MAX_LOGS_IN_SNAPSHOT = 250
WORKER_COUNT = 2
MAX_IN_FLIGHT = 32
MAX_TRACKED_SIGNALS = 256

_JOBS: dict[str, dict[str, Any]] = {}
_jobs_lock = threading.RLock()
_state_lock = threading.RLock()
current_job_id = contextvars.ContextVar("current_job_id", default=None)

worker_pool = ThreadPoolExecutor(max_workers=WORKER_COUNT, thread_name_prefix="medienwerk-job")
_inflight = BoundedSemaphore(MAX_IN_FLIGHT)
_redaction_local = threading.local()
_redaction_lock = threading.Lock()
_redaction_cache: tuple[str, tuple[str, ...]] = ("", ())

TERMINAL_STATES = frozenset({"completed", "failed", "cancelled", "interrupted"})
KNOWN_STATES = frozenset({
    "queued", "running", "awaiting_input", "cancel_requested", *TERMINAL_STATES,
})
_STATUS_ALIASES = {
    "pending": "queued",
    "processing": "running",
    "succeeded": "completed",
    "success": "completed",
}


def _canonical_status(status: str | None) -> str | None:
    if status is None:
        return None
    canonical = _STATUS_ALIASES.get(status, status)
    if canonical not in KNOWN_STATES:
        raise ValueError(f"Unsupported job status: {status}")
    return canonical


def _json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def _json_load(value: str | None, fallback: Any = None) -> Any:
    if value is None:
        return fallback
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return fallback


def _format_timestamp(value: dt.datetime) -> str:
    if value.tzinfo is None:
        return value.isoformat(timespec="microseconds") + "Z"
    return value.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def _secret_values() -> tuple[str, ...]:
    """Read configured secret values lazily; never let a config error break jobs."""
    global _redaction_cache
    if getattr(_redaction_local, "active", False):
        return _redaction_cache[1]
    try:
        from config import CONFIG_FILE, load_config
        from server.core.config_schema import SECRET_KEYS

        config_path = str(CONFIG_FILE)
        try:
            stamp = str(Path(CONFIG_FILE).stat().st_mtime_ns)
        except OSError:
            stamp = "missing"
        cache_key = f"{config_path}:{stamp}"
        with _redaction_lock:
            if _redaction_cache[0] == cache_key:
                return _redaction_cache[1]
            _redaction_local.active = True
        if stamp == "missing":
            with _redaction_lock:
                _redaction_cache = (cache_key, ())
            return ()
        config = load_config()
        values = {str(config.get(key, "")) for key in SECRET_KEYS}
        result = tuple(sorted((value for value in values if len(value) >= 4), key=len, reverse=True))
        with _redaction_lock:
            _redaction_cache = (cache_key, result)
        return result
    except Exception:
        logging.getLogger(__name__).debug("Could not load secret values for job redaction", exc_info=True)
        return ()
    finally:
        _redaction_local.active = False


def _redact_text(value: str) -> str:
    for secret in _secret_values():
        value = value.replace(secret, "[redacted]")
    # Redact common inline credential forms even when the value is not in config.
    value = re.sub(
        r"(?i)\b(api[_-]?key|access[_-]?token|refresh[_-]?token|client[_-]?secret|password)\s*([=:])\s*([^\s,;&]+)",
        r"\1\2[redacted]",
        value,
    )
    return value


_SENSITIVE_KEY = re.compile(r"(?:api[_-]?key|token|secret|password|credential)", re.IGNORECASE)


def _sanitize_value(value: Any) -> Any:
    if isinstance(value, dict):
        sanitized = {}
        for key, item in value.items():
            key_text = str(key)
            if _SENSITIVE_KEY.search(key_text):
                continue
            sanitized[key_text] = _sanitize_value(item)
        return sanitized
    if isinstance(value, (list, tuple)):
        return [_sanitize_value(item) for item in value]
    if isinstance(value, str):
        return _redact_text(value)
    return value


def _sanitize_settings(value: Any) -> Any:
    if isinstance(value, dict):
        try:
            from config import sanitize_config

            value = sanitize_config(value)
        except Exception:
            pass
    return _sanitize_value(value)


def _set_project_status_in_session(db, project_id: str, status: str) -> None:
    project = db.get(Project, project_id)
    if project is not None:
        project.status = status
        project.updated_at = utcnow()


def _record_event(
    db,
    job_id: str,
    event_type: str,
    data: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    job = db.get(Job, job_id)
    if job is None:
        return None
    latest = db.scalar(select(func.max(JobEvent.seq)).where(JobEvent.job_id == job_id)) or 0
    occurred_at = utcnow()
    safe_data = _sanitize_value(data or {})
    event = JobEvent(
        job_id=job_id,
        seq=latest + 1,
        occurred_at=occurred_at,
        event_type=event_type,
        payload_json=_json_dump(safe_data),
    )
    db.add(event)
    db.flush()
    old_event_ids = db.scalars(
        select(JobEvent.id)
        .where(JobEvent.job_id == job_id)
        .order_by(JobEvent.seq.desc())
        .offset(MAX_EVENTS_PER_JOB)
    ).all()
    if old_event_ids:
        db.query(JobEvent).filter(JobEvent.id.in_(old_event_ids)).delete(synchronize_session=False)
    return {
        "job_id": job_id,
        "seq": latest + 1,
        "timestamp": _format_timestamp(occurred_at),
        "type": event_type,
        "data": safe_data,
    }


def _ensure_signal(job_id: str) -> threading.Event:
    with _jobs_lock:
        state = _JOBS.get(job_id)
        if state is None:
            state = {"stop_event": threading.Event(), "future": None}
            _JOBS[job_id] = state
        event = state["stop_event"]
    try:
        if get_job_status(job_id) in {"cancel_requested", "cancelled", "interrupted"}:
            event.set()
    except Exception:
        pass
    with _jobs_lock:
        excess = max(0, len(_JOBS) - MAX_TRACKED_SIGNALS)
        candidates = list(_JOBS.items())
    for candidate_id, candidate_state in candidates:
        if not excess or candidate_id == job_id:
            continue
        try:
            if get_job_status(candidate_id) in TERMINAL_STATES:
                with _jobs_lock:
                    if _JOBS.get(candidate_id) is candidate_state:
                        _JOBS.pop(candidate_id, None)
                        excess -= 1
        except Exception:
            continue
    return event


def get_stop_event(job_id: str) -> threading.Event:
    """Return the process-local cancellation signal, lazily restoring it."""
    return _ensure_signal(job_id)


class ConnectionManager:
    """Broadcast persisted event envelopes and ephemeral frames to WebSockets."""

    def __init__(self):
        self.active_connections: dict[str, list[WebSocket]] = {}
        self.loop: asyncio.AbstractEventLoop | None = None
        self._connection_lock = threading.RLock()

    async def connect(self, websocket: WebSocket, job_id: str):
        await websocket.accept()
        with self._connection_lock:
            self.active_connections.setdefault(job_id, []).append(websocket)
            self.loop = asyncio.get_running_loop()
        job_state = get_job(job_id)
        if job_state:
            await websocket.send_text(json.dumps({
                "job_id": job_id,
                "seq": job_state["latest_seq"],
                "timestamp": _format_timestamp(dt.datetime.now(dt.timezone.utc)),
                "type": "full_state",
                "data": job_state,
            }, ensure_ascii=False))

    def disconnect(self, websocket: WebSocket, job_id: str):
        with self._connection_lock:
            connections = self.active_connections.get(job_id)
            if not connections:
                return
            try:
                connections.remove(websocket)
            except ValueError:
                return
            if not connections:
                self.active_connections.pop(job_id, None)

    async def _send_message_async(self, job_id: str, message: dict[str, Any]):
        with self._connection_lock:
            connections = list(self.active_connections.get(job_id, ()))
        for connection in connections:
            try:
                await connection.send_text(json.dumps(message, ensure_ascii=False))
            except Exception:
                logging.getLogger(__name__).debug("WebSocket send failed", exc_info=True)
                self.disconnect(connection, job_id)

    def broadcast(self, job_id: str, message: dict[str, Any]):
        """Persist log-like legacy messages before broadcasting them."""
        kind = message.get("type")
        if kind in {"log", "status", "step"} and not message.get("job_id"):
            data = {key: value for key, value in message.items() if key != "type"}
            event = _append_event(job_id, str(kind), data)
            if event is None:
                return
            message = event
        elif "job_id" not in message:
            message = {
                "job_id": job_id,
                "timestamp": _format_timestamp(dt.datetime.now(dt.timezone.utc)),
                "type": str(kind or "message"),
                "data": _sanitize_value({key: value for key, value in message.items() if key != "type"}),
            }

        with self._connection_lock:
            if not self.active_connections.get(job_id):
                return
            loop = self.loop
        if loop is None or not loop.is_running():
            return
        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            running_loop = None
        if running_loop is loop:
            loop.create_task(self._send_message_async(job_id, message))
        else:
            asyncio.run_coroutine_threadsafe(self._send_message_async(job_id, message), loop)


manager = ConnectionManager()


def _append_event(job_id: str, event_type: str, data: dict[str, Any]) -> dict[str, Any] | None:
    with _state_lock, session_scope() as db:
        envelope = _record_event(db, job_id, event_type, data)
    if envelope:
        manager.broadcast(job_id, envelope)
    return envelope


class JobLogHandler(logging.Handler):
    def emit(self, record):
        job_id = current_job_id.get()
        if not job_id:
            return
        try:
            message = _redact_text(self.format(record))
            _append_event(job_id, "log", {"message": message})
        except Exception:
            self.handleError(record)


job_handler = JobLogHandler()
job_handler.setFormatter(logging.Formatter("%(message)s"))
_root_logger = logging.getLogger()
if not any(isinstance(handler, JobLogHandler) for handler in _root_logger.handlers):
    _root_logger.addHandler(job_handler)
_root_logger.setLevel(logging.INFO)


def _record_project(title: str, workflow: str, settings: Any) -> str:
    from server.core.project_store import create_project

    project = create_project(title=title or workflow, kind=workflow, config=_sanitize_settings(settings or {}))
    return project["id"]


def create_job(
    topic: str,
    project_id: str | None = None,
    workflow: str = "quick",
    settings: dict[str, Any] | None = None,
    idempotency_key: str | None = None,
) -> str:
    """Create a durable queued job, optionally deduplicated by workflow/key."""
    safe_settings = _sanitize_settings(settings or {})
    safe_topic = _redact_text(str(topic))
    with _state_lock:
        if idempotency_key:
            with SessionLocal() as db:
                existing = db.scalar(select(Job).where(
                    Job.workflow == workflow,
                    Job.idempotency_key == idempotency_key,
                ))
                if existing:
                    return existing.id

        if project_id is None:
            project_id = _record_project(safe_topic or workflow, workflow, safe_settings)
        job_id = str(uuid.uuid4())
        now = utcnow()
        try:
            with session_scope() as db:
                job = Job(
                    id=job_id,
                    project_id=project_id,
                    workflow=workflow,
                    topic=safe_topic,
                    status="queued",
                    step="Waiting in queue...",
                    idempotency_key=idempotency_key,
                    settings_json=_json_dump(safe_settings),
                    progress=0.0,
                    created_at=now,
                )
                db.add(job)
                db.flush()
                _set_project_status_in_session(db, project_id, "queued")
                envelope = _record_event(db, job_id, "status", {"status": "queued", "step": job.step})
        except IntegrityError:
            if idempotency_key:
                with SessionLocal() as db:
                    existing = db.scalar(select(Job).where(
                        Job.workflow == workflow,
                        Job.idempotency_key == idempotency_key,
                    ))
                    if existing:
                        return existing.id
            raise
    if envelope:
        manager.broadcast(job_id, envelope)
    return job_id


def _job_fields(job: Job, latest_seq: int, logs: list[str], log_entries: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    result = _sanitize_value(_json_load(job.result_json))
    result_ids: list[str] = []
    result_media: list[dict[str, Any]] = []
    if isinstance(result, dict) and "_job_result_value" in result:
        result_ids = [str(value) for value in result.get("_media_ids", [])]
        result_media = _sanitize_value(result.get("_media_results", []))
        for item in result_media:
            if isinstance(item, dict) and item.get("id"):
                item["url"] = f"/api/projects/media/{item['id']}/download"
        result = result["_job_result_value"]
    if isinstance(result, dict):
        candidate = result.get("result_ids", result.get("media_ids", []))
        if isinstance(candidate, (list, tuple)):
            result_ids = [str(value) for value in candidate]
        for key in ("result_id", "media_id"):
            if result.get(key) is not None:
                result_ids.append(str(result[key]))
    elif isinstance(result, list):
        result_ids = [str(item.get("id")) for item in result if isinstance(item, dict) and item.get("id")]
    return {
        "id": job.id,
        "topic": job.topic,
        "project_id": job.project_id,
        "workflow": job.workflow,
        "status": job.status,
        "progress": float(job.progress or 0.0),
        "step": job.step,
        "result": result,
        "result_ids": result_ids,
        "result_media": result_media,
        "error": _redact_text(job.error) if job.error else None,
        "logs": logs,
        "log_entries": list(log_entries or []),
        "settings": _sanitize_settings(_json_load(job.settings_json, {})),
        "created_at": _format_timestamp(job.created_at) if job.created_at else None,
        "started_at": _format_timestamp(job.started_at) if job.started_at else None,
        "finished_at": _format_timestamp(job.finished_at) if job.finished_at else None,
        "latest_seq": int(latest_seq or 0),
    }


def get_job(job_id: str) -> dict[str, Any] | None:
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        if job is None:
            return None
        latest_seq = db.scalar(select(func.max(JobEvent.seq)).where(JobEvent.job_id == job_id)) or 0
        events = db.scalars(
            select(JobEvent)
            .where(JobEvent.job_id == job_id, JobEvent.event_type == "log")
            .order_by(JobEvent.seq.desc())
            .limit(MAX_LOGS_IN_SNAPSHOT)
        ).all()
        logs = []
        log_entries = []
        for event in reversed(events):
            payload = _json_load(event.payload_json, {})
            log_message = payload.get("message") if isinstance(payload, dict) else payload
            if log_message is None:
                log_message = payload
            message = _redact_text(str(log_message))
            logs.append(message)
            log_entries.append({
                "seq": event.seq,
                "timestamp": _format_timestamp(event.occurred_at),
                "message": message,
            })
        return _job_fields(job, latest_seq, logs, log_entries)


def get_job_status(job_id: str) -> str | None:
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        return job.status if job else None


def get_latest_seq(job_id: str) -> int:
    with SessionLocal() as db:
        return int(db.scalar(select(func.max(JobEvent.seq)).where(JobEvent.job_id == job_id)) or 0)


def get_job_events(job_id: str, after_seq: int = 0, limit: int = MAX_EVENTS_PER_JOB) -> list[dict[str, Any]]:
    """Return ordered persisted event envelopes for replay after reconnect."""
    with SessionLocal() as db:
        events = db.scalars(
            select(JobEvent)
            .where(JobEvent.job_id == job_id, JobEvent.seq > after_seq)
            .order_by(JobEvent.seq.asc())
            .limit(max(1, min(limit, MAX_EVENTS_PER_JOB)))
        ).all()
        return [{
            "job_id": event.job_id,
            "seq": event.seq,
            "timestamp": _format_timestamp(event.occurred_at),
            "type": event.event_type,
            "data": _sanitize_value(_json_load(event.payload_json, {})),
        } for event in events]


def _emit_transition(job_id: str, updates: dict[str, Any], event_type: str, data: dict[str, Any]) -> bool:
    envelope = None
    resulting_status = None
    with _state_lock, session_scope() as db:
        job = db.get(Job, job_id)
        if job is None:
            return False
        current = job.status
        next_status = updates.get("status")
        if current in TERMINAL_STATES:
            return False
        if current == "cancel_requested" and next_status not in ("cancel_requested", "cancelled"):
            # A late callback must not change cancellation into completion/failure.
            return False
        if current == "awaiting_input" and next_status == "running":
            # Resume only through the compare-and-set claim path.
            return False
        if next_status and next_status != current:
            job.status = next_status
            if next_status == "running" and job.started_at is None:
                job.started_at = utcnow()
            if next_status in TERMINAL_STATES:
                job.finished_at = utcnow()
        if "progress" in updates and updates["progress"] is not None:
            progress = max(0.0, min(1.0, float(updates["progress"])))
            if job.status != "completed":
                progress = min(0.99, progress)
            job.progress = progress
        if "step" in updates and updates["step"] is not None:
            job.step = _redact_text(str(updates["step"]))
        if "result_json" in updates:
            job.result_json = _json_dump(_sanitize_value(updates["result_json"]))
        if "error" in updates:
            job.error = _redact_text(str(updates["error"])) if updates["error"] else None
        resulting_status = job.status
        if next_status is not None and next_status != current:
            _set_project_status_in_session(db, job.project_id, resulting_status)
        envelope = _record_event(db, job_id, event_type, data)
    if envelope:
        manager.broadcast(job_id, envelope)
    return True


def update_job(
    job_id: str,
    status: str | None = None,
    progress: float | None = None,
    step: str | None = None,
    result: Any = None,
    error: str | None = None,
):
    canonical = _canonical_status(status)
    updates: dict[str, Any] = {}
    event_data: dict[str, Any] = {}
    if canonical is not None:
        updates["status"] = canonical
        event_data["status"] = canonical
    if progress is not None:
        updates["progress"] = progress
        event_data["progress"] = max(0.0, min(0.99 if canonical != "completed" else 1.0, float(progress)))
    if step is not None:
        updates["step"] = step
        event_data["step"] = _redact_text(str(step))
    if result is not None:
        updates["result_json"] = result
        event_data["result"] = _sanitize_value(result)
    if error is not None:
        updates["error"] = error
        event_data["error"] = _redact_text(str(error))
    if not updates:
        return False
    if canonical == "completed":
        updates.setdefault("progress", 1.0)
        event_data.setdefault("progress", 1.0)
    if canonical in TERMINAL_STATES and canonical != "completed" and progress is not None:
        updates["progress"] = min(0.99, float(progress))
        event_data["progress"] = updates["progress"]
    return _emit_transition(job_id, updates, "update", event_data)


def complete_job(
    job_id: str,
    result: Any = None,
    *,
    media_records: list[dict[str, Any]] | None = None,
) -> bool:
    """Complete a job and register any final outputs in the same DB transaction.

    Each media record accepts ``path`` plus optional ``role``, ``kind``,
    ``origin_key`` and ``import_root``. For new project-owned outputs, the caller
    should first place the file below ``project_directory(project_id)/output``.
    Imported legacy files must supply their explicitly selected ``import_root``.
    """
    from server.core.media_store import register_media

    media_records = list(media_records or [])
    registered: list[dict[str, Any]] = []
    with _state_lock, SessionLocal.begin() as db:
        job = db.get(Job, job_id)
        if job is None or job.status in TERMINAL_STATES or job.status == "cancel_requested":
            return False
        for record in media_records:
            if "path" not in record:
                raise ValueError("Each media record requires a path")
            registered.append(register_media(
                job.project_id,
                record["path"],
                role=record.get("role", "final"),
                kind=record.get("kind"),
                require_audio=record.get("require_audio"),
                origin_key=record.get("origin_key"),
                import_root=record.get("import_root"),
                session=db,
            ))
        result_to_store = result
        if registered:
            result_to_store = {
                "_job_result_value": result,
                "_media_ids": [item["id"] for item in registered],
                "_media_results": registered,
            }
        job.status = "completed"
        job.progress = 1.0
        job.finished_at = utcnow()
        job.result_json = _json_dump(_sanitize_value(result_to_store))
        job.error = None
        job.step = "Completed"
        _set_project_status_in_session(db, job.project_id, "completed")
        envelope = _record_event(db, job_id, "status", {
            "status": "completed",
            "progress": 1.0,
            "result": _sanitize_value(result),
            "result_ids": [item["id"] for item in registered],
        })
    if envelope:
        manager.broadcast(job_id, envelope)
    return True


def claim_job(job_id: str, expected: Iterable[str] = ("queued",)) -> bool:
    """Atomically claim a queued job so duplicate submissions cannot run twice."""
    expected_states = tuple(_canonical_status(value) for value in expected)
    if not expected_states:
        return False
    with _state_lock, session_scope() as db:
        job = db.get(Job, job_id)
        if job is None or job.status not in expected_states:
            return False
        previous = job.status
        result = db.execute(
            update(Job)
            .where(Job.id == job_id, Job.status.in_(expected_states))
            .values(status="running", started_at=func.coalesce(Job.started_at, utcnow()))
        )
        if result.rowcount != 1:
            return False
        job.status = "running"
        if job.started_at is None:
            job.started_at = utcnow()
        envelope = _record_event(db, job_id, "status", {"status": "running", "previous_status": previous})
        _set_project_status_in_session(db, job.project_id, job.status)
    if envelope:
        manager.broadcast(job_id, envelope)
    _ensure_signal(job_id)
    return True


def request_cancel(job_id: str) -> bool:
    """Record a cancellation request without claiming that the worker has stopped."""
    status = get_job_status(job_id)
    if status is None or status in TERMINAL_STATES or status == "cancel_requested":
        return False
    get_stop_event(job_id).set()
    changed = _emit_transition(
        job_id,
        {"status": "cancel_requested"},
        "status",
        {"status": "cancel_requested"},
    )
    return changed


def stop_job(job_id: str) -> bool:
    """Request cancellation; mark cancelled only after a queued Future is cancelled."""
    if not request_cancel(job_id):
        return False
    with _jobs_lock:
        state = _JOBS.get(job_id)
        future: Future | None = state.get("future") if state else None
    if future is not None and future.cancel():
        update_job(job_id, status="cancelled")
        return True
    if future is None or future.done():
        # awaiting_input jobs and finished analysis tasks have no live worker to
        # acknowledge a stop, so the server can confirm them immediately.
        update_job(job_id, status="cancelled")
    return True


def _extract_job_id(args: tuple[Any, ...], kwargs: dict[str, Any]) -> str | None:
    candidate = kwargs.get("job_id")
    if candidate is None and args and isinstance(args[0], str):
        candidate = args[0]
    if not isinstance(candidate, str):
        return None
    return candidate if get_job_status(candidate) is not None else None


def _run_queued_task(
    job_id: str | None,
    claim_from: tuple[str, ...],
    func,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
):
    token = current_job_id.set(job_id)
    stop_event = get_stop_event(job_id) if job_id else None
    try:
        if job_id:
            status = get_job_status(job_id)
            if status == "cancel_requested" or (stop_event and stop_event.is_set()):
                update_job(job_id, status="cancelled")
                return None
            if not claim_job(job_id, expected=claim_from):
                return None
        result = func(*args, **kwargs)
        if job_id and stop_event and stop_event.is_set():
            update_job(job_id, status="cancelled")
        return result
    except BaseException as exc:
        if job_id:
            status = get_job_status(job_id)
            if status == "cancel_requested" or (stop_event and stop_event.is_set()):
                update_job(job_id, status="cancelled")
            elif status not in TERMINAL_STATES:
                update_job(job_id, status="failed", error=str(exc))
        raise
    finally:
        current_job_id.reset(token)


def _submit_with_claim(func, args: tuple[Any, ...], kwargs: dict[str, Any], claim_from: tuple[str, ...]):
    job_id = _extract_job_id(args, kwargs)
    if job_id:
        signal = _ensure_signal(job_id)
        if signal.is_set() or get_job_status(job_id) == "cancel_requested":
            update_job(job_id, status="cancelled")
            return None
    if not _inflight.acquire(blocking=False):
        raise RuntimeError("Job queue is full; try again after a running job finishes")
    context = contextvars.copy_context()
    try:
        future = worker_pool.submit(context.run, _run_queued_task, job_id, claim_from, func, args, kwargs)
    except BaseException:
        _inflight.release()
        raise
    if job_id:
        with _jobs_lock:
            state = _JOBS.setdefault(job_id, {"stop_event": threading.Event(), "future": None})
            state["future"] = future
    future.add_done_callback(lambda done: _on_future_done(job_id, done))
    return future


def submit_to_queue(func, *args, **kwargs):
    """Submit a new job; dispatch can claim only its initial queued state."""
    return _submit_with_claim(func, args, kwargs, ("queued",))


def submit_awaiting_input_to_queue(func, job_id: str, *args, **kwargs):
    """Submit one follow-up stage that must atomically claim awaiting_input.

    Use this only for a user-selected continuation such as clip rendering. A
    duplicate submit is harmless: only one queued Future can claim the state.
    """
    return _submit_with_claim(func, (job_id, *args), kwargs, ("awaiting_input",))


def _on_future_done(job_id: str | None, future: Future) -> None:
    _inflight.release()
    if not job_id:
        return
    if future.cancelled() and get_job_status(job_id) == "cancel_requested":
        update_job(job_id, status="cancelled")
    if get_job_status(job_id) not in TERMINAL_STATES:
        return
    with _jobs_lock:
        state = _JOBS.get(job_id)
        if state and state.get("future") is future:
            _JOBS.pop(job_id, None)


def add_log(job_id: str, msg: str):
    _append_event(job_id, "log", {"message": _redact_text(str(msg))})


def update_step(
    job_id: str,
    step_id: str,
    title: str | None = None,
    status: str = "running",
    progress: float = 0.0,
    result: Any = None,
    error: str | None = None,
    total_steps: int | None = None,
) -> bool:
    """Upsert a stable step and recompute durable, bounded overall progress."""
    if total_steps is not None and (isinstance(total_steps, bool) or not isinstance(total_steps, int) or total_steps < 1):
        raise ValueError("total_steps must be a positive integer when provided")
    step_status = _STATUS_ALIASES.get(status, status)
    if step_status not in {"queued", "running", "awaiting_input", "completed", "failed", "cancelled", "skipped"}:
        raise ValueError(f"Unsupported job step status: {status}")
    now = utcnow()
    with _state_lock, session_scope() as db:
        job = db.get(Job, job_id)
        if job is None or job.status in TERMINAL_STATES or job.status == "cancel_requested":
            return False
        step = db.scalar(select(JobStep).where(JobStep.job_id == job_id, JobStep.step_id == step_id))
        if step is None:
            step = JobStep(job_id=job_id, step_id=step_id, title=title, status=step_status, progress=0.0)
            db.add(step)
        if title is not None:
            step.title = _redact_text(str(title))
        step.status = step_status
        step.progress = max(0.0, min(1.0, float(progress)))
        if step.started_at is None and step_status in {"running", "completed"}:
            step.started_at = now
        if step_status in TERMINAL_STATES or step_status == "skipped":
            step.finished_at = now
        if result is not None:
            step.result_json = _json_dump(_sanitize_value(result))
        if error is not None:
            step.error = _redact_text(str(error))
        db.flush()
        steps = db.scalars(select(JobStep).where(JobStep.job_id == job_id)).all()
        denominator = max(len(steps), total_steps or 0)
        aggregate = sum(
            1.0 if row.status == "skipped" else float(row.progress or 0)
            for row in steps
        ) / denominator if denominator else 0.0
        bounded_progress = min(0.99, aggregate)
        # A fixed pipeline denominator treats steps not yet started as zero,
        # so adding a later step cannot lower the overall progress snapshot.
        # Workflows without a declared total retain the observed-step behavior.
        if total_steps is not None:
            bounded_progress = max(float(job.progress or 0.0), bounded_progress)
        job.progress = bounded_progress
        if title is not None:
            job.step = _redact_text(str(title))
        envelope = _record_event(db, job_id, "step", {
            "step_id": step_id,
            "title": step.title,
            "status": step_status,
            "progress": step.progress,
            "overall_progress": job.progress,
            "result": _sanitize_value(result),
            "error": _redact_text(str(error)) if error else None,
        })
        project_id = job.project_id
        _set_project_status_in_session(db, project_id, job.status)
    if envelope:
        manager.broadcast(job_id, envelope)
    return True


def recover_interrupted_jobs() -> int:
    """Mark work from a previous process interrupted; preserve user-input jobs."""
    now = utcnow()
    changed: list[tuple[str, str]] = []
    with _state_lock, session_scope() as db:
        jobs = db.scalars(select(Job).where(Job.status.in_(("queued", "running", "cancel_requested")))).all()
        for job in jobs:
            previous = job.status
            job.status = "interrupted"
            job.finished_at = now
            job.error = "The application restarted before this job finished. Start a new attempt to continue."
            envelope = _record_event(db, job.id, "status", {
                "status": "interrupted",
                "previous_status": previous,
                "error": job.error,
            })
            _set_project_status_in_session(db, job.project_id, "interrupted")
            changed.append((job.id, job.project_id))
    for job_id, project_id in changed:
        with _jobs_lock:
            _JOBS.pop(job_id, None)
    return len(changed)


def get_steps(job_id: str) -> list[dict[str, Any]]:
    with SessionLocal() as db:
        steps = db.scalars(select(JobStep).where(JobStep.job_id == job_id).order_by(JobStep.id.asc())).all()
        return [{
            "step_id": step.step_id,
            "title": step.title,
            "status": step.status,
            "progress": float(step.progress or 0),
            "result": _json_load(step.result_json),
            "error": _redact_text(step.error) if step.error else None,
            "started_at": _format_timestamp(step.started_at) if step.started_at else None,
            "finished_at": _format_timestamp(step.finished_at) if step.finished_at else None,
        } for step in steps]


def list_jobs(limit: int = 100) -> list[dict[str, Any]]:
    with SessionLocal() as db:
        job_ids = db.scalars(select(Job.id).order_by(Job.created_at.desc()).limit(max(1, min(limit, 500)))).all()
    return [job for job_id in job_ids if (job := get_job(job_id)) is not None]
