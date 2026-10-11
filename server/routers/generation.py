"""Quick Creator jobs backed by the shared project, media, and queue stores."""

from __future__ import annotations

import logging
import hashlib
import json
import shutil
import threading
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

import pipeline
from agents import TrendAgent
from config import (
    ConfigFileError,
    ConfigValidationError,
    effective_config,
    load_config,
    public_config,
    sanitize_config,
    update_config as persist_config_update,
    validate_provider_config,
)
from server.core.database import Job, Media, Project, SessionLocal
from server.core.media_store import MediaValidationError, resolve_media
from server.core.project_store import delete_project as delete_project_record, get_history
from server.core.project_store import project_directory
from server.core.queue import (
    add_log,
    claim_job,
    complete_job,
    create_job,
    current_job_id,
    get_job,
    get_job_events,
    get_job_status,
    get_steps,
    list_jobs,
    manager,
    submit_to_queue,
    stop_job,
    update_job,
    update_step,
    get_stop_event,
)

router = APIRouter()
_QUICK_START_LOCK = threading.RLock()


class IdempotencyConflictError(ValueError):
    """An idempotency key was reused for a different request."""


class JobUI:
    def __init__(self, job_id: str | None = None):
        self.job_id = job_id

    def log_to_agent_console(self, msg: str) -> None:
        if self.job_id:
            add_log(self.job_id, msg)
        else:
            logging.info("[TrendAgent] %s", msg)

    def update_agent_node(self, name: str, status: str, state: str) -> None:
        if self.job_id:
            add_log(self.job_id, f"{name}: {status} ({state})")


class GenerationRequest(BaseModel):
    topic: str = Field(min_length=1, max_length=500)
    style: str = "Cinematic Documentary"
    voice: Optional[str] = "Kore"
    aspect_ratio: Optional[str] = "16:9"
    bg_mode: Optional[str] = "AI Video"
    bg_music: Optional[bool] = True
    fact_check: Optional[bool] = False
    auto_captions: Optional[bool] = True
    omnichannel: Optional[bool] = False
    start_point: Optional[str] = "Deep Research"
    content_style: Optional[str] = "Podcast"
    image_count: Optional[int] = Field(default=8, ge=1, le=100)
    video_count: Optional[int] = Field(default=1, ge=1, le=40)
    generate_thumbnail: Optional[bool] = False
    generate_seo: Optional[bool] = False
    generate_timestamps: Optional[bool] = False
    generate_snippets: Optional[bool] = False
    script_length: Optional[str] = "Medium (~5 minutes)"
    audio_engine: Optional[str] = "Gemini API"
    video_engine: Optional[str] = "WaveSpeed AI"
    idempotency_key: Optional[str] = Field(default=None, min_length=1, max_length=255)
    project_id: Optional[str] = Field(default=None, min_length=1, max_length=80)


def _request_config(req: GenerationRequest, config: dict[str, Any] | None = None) -> dict[str, Any]:
    if req.omnichannel:
        raise ConfigValidationError("Omnichannel generation is not available yet")
    if req.start_point not in (None, "Deep Research"):
        raise ConfigValidationError("Quick Creator currently starts at Deep Research")
    overrides: dict[str, Any] = {
        "CONTENT_STYLE": req.content_style,
        "VISUAL_STYLE": req.style,
        "VOICE_NAME": req.voice,
        "SPEAKER1": req.voice,
        "AUDIO_ENGINE": req.audio_engine,
        "VIDEO_ENGINE": req.video_engine,
        "VIDEO_ASPECT_RATIO": req.aspect_ratio,
        "BG_MODE": req.bg_mode,
        "ADD_MUSIC": req.bg_music,
        "FACT_CHECK_ENABLED": req.fact_check,
        "CAPTION_ENABLED": req.auto_captions,
        "IMAGE_COUNT": req.image_count,
        "VIDEO_CLIP_COUNT": req.video_count,
        "GENERATE_THUMBNAIL": req.generate_thumbnail,
        "GENERATE_SEO": req.generate_seo,
        "GENERATE_TIMESTAMPS": req.generate_timestamps,
        "GENERATE_SNIPPETS": req.generate_snippets,
        "SCRIPT_LENGTH": req.script_length,
    }
    overrides = {key: value for key, value in overrides.items() if value is not None}
    snapshot = effective_config(overrides) if config is None else {**config, **overrides}
    from server.core.config_schema import normalize_config
    return normalize_config(snapshot, fill_defaults=True)


def _request_fingerprint(req: GenerationRequest) -> str:
    payload = req.model_dump(mode="json", exclude={"idempotency_key"})
    payload["topic"] = req.topic.strip()
    if payload.get("aspect_ratio") is not None:
        from server.core.config_schema import normalize_config
        payload["aspect_ratio"] = normalize_config({"VIDEO_ASPECT_RATIO": payload["aspect_ratio"]})[
            "VIDEO_ASPECT_RATIO"
        ]
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _legacy_request_matches(req: GenerationRequest, existing: dict[str, Any]) -> bool:
    """Conservatively compare a pre-fingerprint job using its saved request settings."""
    if str(existing.get("topic") or "").strip() != req.topic.strip():
        return False
    if req.project_id and existing.get("project_id") != req.project_id:
        return False
    saved = existing.get("settings")
    if not isinstance(saved, dict):
        return False
    try:
        expected = _request_config(req)
    except (ConfigValidationError, ConfigFileError):
        return False

    fields = {
        "style": ("VISUAL_STYLE",),
        "voice": ("VOICE_NAME", "SPEAKER1"),
        "aspect_ratio": ("VIDEO_ASPECT_RATIO",),
        "bg_mode": ("BG_MODE",),
        "bg_music": ("ADD_MUSIC",),
        "fact_check": ("FACT_CHECK_ENABLED",),
        "auto_captions": ("CAPTION_ENABLED",),
        "content_style": ("CONTENT_STYLE",),
        "image_count": ("IMAGE_COUNT",),
        "video_count": ("VIDEO_CLIP_COUNT",),
        "generate_thumbnail": ("GENERATE_THUMBNAIL",),
        "generate_seo": ("GENERATE_SEO",),
        "generate_timestamps": ("GENERATE_TIMESTAMPS",),
        "generate_snippets": ("GENERATE_SNIPPETS",),
        "script_length": ("SCRIPT_LENGTH",),
        "audio_engine": ("AUDIO_ENGINE",),
        "video_engine": ("VIDEO_ENGINE",),
    }
    request_values = req.model_dump(exclude={"idempotency_key", "project_id", "topic"})
    for field, keys in fields.items():
        if request_values.get(field) is None:
            continue
        if any(key not in saved or saved[key] != expected[key] for key in keys):
            return False
    return True


def _existing_idempotent_response(
    req: GenerationRequest,
    existing: dict[str, Any],
    fingerprint: str,
) -> dict[str, Any]:
    saved_fingerprint = (existing.get("settings") or {}).get("_request_fingerprint")
    if saved_fingerprint is not None:
        if saved_fingerprint != fingerprint:
            raise IdempotencyConflictError("Idempotency key was already used for a different Quick Creator request")
    elif not _legacy_request_matches(req, existing):
        raise IdempotencyConflictError(
            "Idempotency key belongs to an older job whose request cannot be verified as identical"
        )
    return {
        "job_id": existing["id"],
        "project_id": existing["project_id"],
        "status": existing["status"],
        "message": "Existing job returned.",
    }


def start_quick_generation(
    req: GenerationRequest,
    *,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """Create or return one frozen-config Quick Creator attempt and enqueue it once."""
    key = idempotency_key or req.idempotency_key
    fingerprint = _request_fingerprint(req)
    with _QUICK_START_LOCK:
        if key:
            with SessionLocal() as db:
                existing_id = db.query(Job.id).filter(
                    Job.workflow == "quick_creator", Job.idempotency_key == key,
                ).scalar()
            if existing_id:
                existing = get_job(existing_id)
                if existing is not None:
                    return _existing_idempotent_response(req, existing, fingerprint)

        snapshot = _request_config(req)
        validate_provider_config(snapshot, kind="quick")
        if req.project_id:
            with SessionLocal() as db:
                project = db.get(Project, req.project_id)
                if project is None:
                    raise ConfigValidationError("Retry project was not found")
                if project.kind != "quick_creator":
                    raise ConfigValidationError("Retry project must belong to Quick Creator")
                if project.status in {"queued", "running", "awaiting_input", "cancel_requested"}:
                    raise ConfigValidationError("Retry project already has an active job")
                active_job = db.query(Job.id).filter(
                    Job.project_id == project.id,
                    Job.status.in_(("queued", "running", "awaiting_input", "cancel_requested")),
                ).first()
                if active_job:
                    raise ConfigValidationError("Retry project already has an active job")
        saved_settings = sanitize_config(snapshot)
        saved_settings["_request_fingerprint"] = fingerprint
        job_id = create_job(
            req.topic.strip(),
            project_id=req.project_id,
            workflow="quick_creator",
            settings=saved_settings,
            idempotency_key=key,
        )
        job = get_job(job_id)
        if job is None:
            raise RuntimeError("Could not read the newly created Quick Creator job")
        try:
            submit_to_queue(run_pipeline_task, job_id, req, snapshot, job["project_id"])
        except Exception as exc:
            update_job(job_id, status="failed", error=f"Could not submit job to the worker queue: {exc}")
            raise
        return {
            "job_id": job_id,
            "project_id": job["project_id"],
            "status": get_job_status(job_id),
            "message": "Generation queued successfully.",
        }


def run_pipeline_task(
    job_id: str,
    req: GenerationRequest,
    config_snapshot: dict[str, Any] | None = None,
    project_id: str | None = None,
) -> None:
    """Run a single project-isolated pipeline attempt and register its final file."""
    token = current_job_id.set(job_id)
    stop_event = get_stop_event(job_id)
    try:
        job = get_job(job_id)
        if job is None:
            raise ValueError("Quick Creator job no longer exists")
        project_id = project_id or job["project_id"]
        config = _request_config(req, config_snapshot or effective_config())
        validate_provider_config(config, kind="quick")
        project_path = project_directory(project_id)
        attempt_dir = project_path / "intermediate" / job_id
        attempt_dir.mkdir(parents=True, exist_ok=False)

        def update_progress(step_index: int, status_label: str, value: float) -> None:
            titles = pipeline.PIPELINE_STEPS
            title = titles[step_index] if 0 <= step_index < len(titles) else status_label
            label = str(status_label)
            if "⏭" in label:
                status = "skipped"
            elif "❌" in label:
                status = "failed"
            elif float(value) >= 1.0:
                status = "completed"
            else:
                status = "running"
            update_step(
                job_id,
                f"pipeline.{step_index:02d}",
                title=f"{title}: {label}",
                status=status,
                progress=float(value),
                total_steps=len(titles),
            )

        runner = pipeline.Pipeline(config, stop_event, update_progress)
        produced_path = runner.run(req.topic.strip(), start_point="Deep Research", output_dir=str(attempt_dir))
        if stop_event.is_set():
            update_job(job_id, status="cancelled")
            return
        source = Path(produced_path).resolve(strict=True)
        if not source.is_file() or source.stat().st_size == 0:
            raise RuntimeError("Pipeline did not produce a readable final video")
        final_path = project_path / "output" / job_id / "final_video.mp4"
        final_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, final_path)
        warnings = list(getattr(runner, "optional_failures", []))
        complete_job(
            job_id,
            result={"path": str(final_path), "warnings": warnings, "pipeline_version": "stabilized-1"},
            media_records=[{"path": final_path, "role": "final", "kind": "video"}],
        )
    except (InterruptedError, FileNotFoundError):
        if stop_event.is_set() or get_job_status(job_id) == "cancel_requested":
            update_job(job_id, status="cancelled")
        else:
            update_job(job_id, status="failed", error="Required pipeline input or output was missing.")
    except Exception as exc:
        if stop_event.is_set() or get_job_status(job_id) == "cancel_requested":
            update_job(job_id, status="cancelled")
        else:
            logging.exception("Quick Creator job %s failed", job_id)
            update_job(job_id, status="failed", error=str(exc))
    finally:
        current_job_id.reset(token)


@router.post("/quick", status_code=202)
def start_quick_generation_route(req: GenerationRequest):
    try:
        return start_quick_generation(req)
    except ConfigValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except IdempotencyConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.websocket("/ws/{job_id}")
async def websocket_endpoint(websocket: WebSocket, job_id: str):
    if get_job(job_id) is None:
        await websocket.close(code=4404)
        return
    await manager.connect(websocket, job_id)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket, job_id)


@router.get("/viral-topics")
def get_viral_topics():
    config = load_config()
    try:
        validate_provider_config(config, kind="text")
        trend_agent = TrendAgent(config, JobUI(), "TrendAgent")
        topics = trend_agent.find_viral_topics()
        return {"topics": topics}
    except ConfigValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/jobs")
def get_generation_jobs(limit: int = Query(100, ge=1, le=500)):
    return list_jobs(limit=limit)


@router.get("/jobs/{job_id}/steps")
def get_generation_job_steps(job_id: str):
    if get_job(job_id) is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"steps": get_steps(job_id)}


@router.get("/jobs/{job_id}/events")
def get_generation_job_events(job_id: str, after: int = Query(0, ge=0)):
    if get_job(job_id) is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"events": get_job_events(job_id, after_seq=after)}


@router.get("/status/{job_id}")
def get_job_status_route(job_id: str):
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.post("/cancel/{job_id}")
def cancel_job(job_id: str):
    if not stop_job(job_id):
        if get_job(job_id) is None:
            raise HTTPException(status_code=404, detail="Job not found")
        return {"message": "Job is already finished or cancellation was already requested."}
    return {"message": f"Cancellation requested for {job_id}"}


@router.get("/settings")
def get_app_settings():
    try:
        return public_config()
    except ConfigFileError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except ConfigValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/settings")
def update_app_settings(new_config: dict[str, Any]):
    try:
        return persist_config_update(new_config)
    except ConfigFileError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except ConfigValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/history")
def get_generation_history(limit: int = Query(100, ge=1, le=500)):
    return get_history(limit=limit)


@router.delete("/history/{project_id}")
def delete_generation_project(project_id: str):
    try:
        if not delete_project_record(project_id):
            raise HTTPException(status_code=404, detail="Project not found")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"message": "Project deleted."}


def _resolve_registered_path(value: str) -> Path:
    """Resolve a media ID or an exact path already present in the media registry."""
    try:
        return resolve_media(value)
    except (FileNotFoundError, MediaValidationError, ValueError):
        pass
    candidate = Path(value).expanduser()
    matches: list[str] = []
    with SessionLocal() as db:
        rows = db.query(Media).all()
        for row in rows:
            root = Path(row.storage_root)
            relative = Path(row.relative_path)
            registered = root / relative
            if value == row.relative_path or candidate == registered or (
                candidate.is_absolute() and candidate == registered.resolve(strict=False)
            ):
                matches.append(row.id)
    if len(matches) != 1:
        raise FileNotFoundError("Path is not a uniquely registered media item")
    return resolve_media(matches[0])


@router.get("/media")
def serve_media_file(path: str = Query(..., min_length=1, max_length=4096)):
    try:
        resolved = _resolve_registered_path(path)
    except (FileNotFoundError, MediaValidationError, ValueError):
        raise HTTPException(status_code=404, detail="Registered media file not found")
    return FileResponse(resolved, filename=resolved.name)
