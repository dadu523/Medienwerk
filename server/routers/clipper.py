"""Durable analyse/select/render workflow for Magic Clipper."""

from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import tempfile
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from config import ConfigValidationError, effective_config, sanitize_config, validate_provider_config
from pipeline_shorts import analyze_video, render_youtube_clips
from server.core.database import Job, Media, SessionLocal
from server.core.media_store import MediaValidationError, probe_media, register_media, resolve_media
from server.core.project_store import project_directory
from server.core.queue import (
    add_log, complete_job, create_job, get_job, get_job_status, get_stop_event,
    submit_awaiting_input_to_queue, submit_to_queue, update_job,
)

router = APIRouter()
MAX_UPLOAD_BYTES = int(os.environ.get("MEDIENWERK_CLIPPER_MAX_UPLOAD_BYTES", str(250 * 1024 * 1024)))
MAX_CLIPS = 20
MAX_CLIP_SECONDS = 120.0
_render_submission_lock = threading.RLock()
_FROZEN_CONFIGS: OrderedDict[str, dict[str, Any]] = OrderedDict()
_FROZEN_CONFIGS_LOCK = threading.RLock()


class ClipperRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2048)
    num_clips: int = Field(default=3, ge=1, le=MAX_CLIPS)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=255)


class RenderRequest(BaseModel):
    job_id: str
    video_path: str
    selected_clips: list[dict[str, Any]] = Field(min_length=1, max_length=MAX_CLIPS)


def _valid_youtube_url(value: str) -> str:
    url = value.strip()
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower().rstrip(".")
    allowed = host in {"youtu.be", "youtube.com", "www.youtube.com", "m.youtube.com"}
    if parsed.scheme not in {"https", "http"} or not allowed:
        raise ConfigValidationError("Clipper requires a YouTube video URL")
    return url


def _find_existing(workflow: str, key: str | None):
    if not key:
        return None
    with SessionLocal() as db:
        row = db.query(Job).filter(Job.workflow == workflow, Job.idempotency_key == key).first()
        return get_job(row.id) if row else None


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _start_analysis(url: str, count: int, *, local_path: Path | None, key: str | None) -> dict:
    snapshot = effective_config()
    validate_provider_config(snapshot, kind="text")
    workflow = "clipper.local" if local_path else "clipper.youtube"
    source_key = str(local_path.name) if local_path else url
    source_fingerprint = _file_sha256(local_path) if local_path else url
    request_fingerprint = hashlib.sha256(json.dumps({
        "workflow": workflow, "source": source_fingerprint, "num_clips": count,
        "language": snapshot.get("PODCAST_LANGUAGE", "English"),
        "config": snapshot,
    }, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    existing = _find_existing(workflow, key)
    if existing:
        if (existing.get("settings") or {}).get("request_fingerprint") != request_fingerprint:
            raise HTTPException(status_code=409, detail="Idempotency key was already used for different Clipper input")
        return {"job_id": existing["id"], "project_id": existing["project_id"],
                "status": existing["status"], "message": "Existing job returned."}

    settings = {**sanitize_config(snapshot), "source": source_key, "num_clips": count,
                "language": snapshot.get("PODCAST_LANGUAGE", "English"),
                "request_fingerprint": request_fingerprint}
    job_id = create_job(
        f"Clipper: {source_key[:100]}", workflow=workflow, settings=settings,
        idempotency_key=key,
    )
    job = get_job(job_id)
    if not job:
        raise RuntimeError("Could not read the Clipper job")
    if (job.get("settings") or {}).get("request_fingerprint") != request_fingerprint:
        raise HTTPException(status_code=409, detail="Idempotency key was already used for different Clipper input")
    with _FROZEN_CONFIGS_LOCK:
        _FROZEN_CONFIGS[job_id] = dict(snapshot)
        _FROZEN_CONFIGS.move_to_end(job_id)
        while len(_FROZEN_CONFIGS) > 256:
            _FROZEN_CONFIGS.popitem(last=False)
    root = project_directory(job["project_id"])
    source_dir = root / "source"
    if local_path:
        suffix = local_path.suffix.lower() or ".mp4"
        owned_source = source_dir / f"{job_id}{suffix}"
        if not owned_source.exists():
            shutil.move(str(local_path), owned_source)
            register_media(job["project_id"], owned_source, role="source", kind="video")
        source = str(owned_source)
        is_local = True
    else:
        source = url
        is_local = False
    if job["status"] == "queued":
        try:
            submit_to_queue(
                run_analyze_task, job_id, source, is_local, count, snapshot, job["project_id"]
            )
        except RuntimeError as exc:
            update_job(job_id, status="failed", error="The local worker queue is full. Start a new attempt later.")
            raise RuntimeError("The local worker queue is full; try again later") from exc
    return {"job_id": job_id, "project_id": job["project_id"], "status": get_job_status(job_id),
            "message": "Analysis queued successfully."}


def run_analyze_task(
    job_id: str,
    source: str,
    is_local: bool,
    num_clips: int = 3,
    config_snapshot: dict[str, Any] | None = None,
    project_id: str | None = None,
) -> None:
    stop_event = get_stop_event(job_id)
    try:
        job = get_job(job_id)
        if not job:
            raise ValueError("Clipper job no longer exists")
        project_id = project_id or job["project_id"]
        snapshot = dict(config_snapshot or effective_config())
        validate_provider_config(snapshot, kind="text")
        root = project_directory(project_id)
        source_dir = root / "source"
        work_dir = root / "intermediate" / job_id
        work_dir.mkdir(parents=True, exist_ok=True)
        language = str(snapshot.get("PODCAST_LANGUAGE") or "English")

        def callback(_job_id, step, progress, result=None, error=None):
            add_log(job_id, step)
            if error:
                update_job(job_id, status="failed", step=step, error=error)
                return
            if result is not None and step == "Awaiting Selection":
                payload = json.loads(result) if isinstance(result, str) else dict(result)
                path = Path(payload.get("video_path", source)).resolve(strict=True)
                if not is_local:
                    # Downloaded sources are project-owned and registered before
                    # selection becomes visible to the client.
                    target = source_dir / path.name
                    if path != target.resolve(strict=False):
                        shutil.copy2(path, target)
                    path = target.resolve(strict=True)
                    register_media(project_id, path, role="source", kind="video")
                details = probe_media(path, expected_kind="video")
                source_duration = float(details["metadata"]["duration_seconds"])
                if not math.isfinite(source_duration) or source_duration <= 0:
                    raise RuntimeError("Clipper source video has an invalid duration")
                with SessionLocal() as db:
                    media = db.query(Media).filter(
                        Media.project_id == project_id,
                        Media.role == "source",
                        Media.relative_path == path.relative_to(root).as_posix(),
                    ).first()
                if media is None:
                    raise RuntimeError("Clipper source video was not registered")
                clips = payload.get("clips", [])
                if not isinstance(clips, list) or not 1 <= len(clips) <= num_clips:
                    raise RuntimeError("Clipper analysis returned an invalid number of segments")
                for index, clip in enumerate(clips):
                    if not isinstance(clip, dict):
                        raise RuntimeError("Clipper analysis returned a malformed segment")
                    try:
                        candidate_start = float(clip["start"])
                        candidate_end = float(clip["end"])
                    except (KeyError, TypeError, ValueError) as exc:
                        raise RuntimeError("Clipper analysis returned invalid segment times") from exc
                    if (
                        not math.isfinite(candidate_start) or not math.isfinite(candidate_end)
                        or candidate_start < 0 or candidate_end <= candidate_start
                        or candidate_end > source_duration
                        or candidate_end - candidate_start > MAX_CLIP_SECONDS
                    ):
                        raise RuntimeError("Clipper analysis returned segment times outside the source bounds")
                    clip["clip_id"] = f"clip-{index}"
                durable = {
                    "type": "selection", "clips": clips,
                    "video_path": str(path), "source_media_id": media.id,
                    "source_duration": source_duration,
                    "language": language,
                }
                update_job(job_id, status="awaiting_input", step="Awaiting Selection",
                           progress=min(float(progress), 0.75), result=durable)
                return
            update_job(job_id, progress=progress, step=step)

        analyze_video(
            source, is_local, job_id, callback, num_clips,
            config=snapshot, output_dir=str(work_dir), language=language, stop_event=stop_event,
        )
        if stop_event.is_set():
            update_job(job_id, status="cancelled")
    except InterruptedError:
        update_job(job_id, status="cancelled")
    except Exception as exc:
        if stop_event.is_set() or get_job_status(job_id) == "cancel_requested":
            update_job(job_id, status="cancelled")
        else:
            add_log(job_id, f"Clipper analysis failed: {exc}")
            update_job(job_id, status="failed", error=str(exc))


@router.post("/analyze", status_code=202)
def start_analyze(req: ClipperRequest):
    try:
        return _start_analysis(_valid_youtube_url(req.url), req.num_clips, local_path=None, key=req.idempotency_key)
    except ConfigValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/analyze_local", status_code=202)
async def start_analyze_local(
    num_clips: int = Form(..., ge=1, le=MAX_CLIPS),
    file: UploadFile = File(...),
    idempotency_key: str | None = Form(default=None, max_length=255),
):
    suffix = Path(file.filename or "video.mp4").suffix.lower()
    if suffix not in {".mp4", ".mov", ".mkv", ".webm", ".avi"}:
        raise HTTPException(status_code=415, detail="Upload must be a supported video file")
    fd, temp_name = tempfile.mkstemp(suffix=suffix)
    os.close(fd)
    temp = Path(temp_name)
    size = 0
    try:
        with temp.open("wb") as out:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail="Upload exceeds the configured size limit")
                out.write(chunk)
        if not size:
            raise HTTPException(status_code=400, detail="Upload is empty")
        probe_media(temp, expected_kind="video")
        result = _start_analysis("local upload", num_clips, local_path=temp, key=idempotency_key)
        return result
    except MediaValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ConfigValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    finally:
        temp.unlink(missing_ok=True)
        await file.close()


def _selection_payload(job: dict) -> dict:
    result = job.get("result")
    if isinstance(result, str):
        try:
            result = json.loads(result)
        except ValueError:
            result = None
    return result if isinstance(result, dict) else {}


def _validated_render(req: RenderRequest, job: dict) -> tuple[Path, list[dict], str]:
    payload = _selection_payload(job)
    analysis = payload.get("analysis", payload)
    if job["status"] not in {"awaiting_input", "running", "completed"} or analysis.get("type") not in {"selection", "render_queued"}:
        raise HTTPException(status_code=409, detail="This Clipper job is not waiting for a clip selection")
    stored_path = analysis.get("video_path")
    source_media_id = analysis.get("source_media_id")
    if not stored_path or not source_media_id or req.video_path != stored_path:
        raise HTTPException(status_code=400, detail="The selected source does not match this Clipper job")
    with SessionLocal() as db:
        source_media = db.get(Media, source_media_id)
        if source_media is None or source_media.project_id != job["project_id"] or source_media.role != "source":
            raise HTTPException(status_code=400, detail="The registered source video is unavailable")
    try:
        source_path = resolve_media(source_media_id)
        expected_path = Path(stored_path).resolve(strict=True)
        if source_path.resolve(strict=True) != expected_path:
            raise HTTPException(status_code=400, detail="The registered source path changed")
        duration = float(probe_media(source_path, expected_kind="video")["metadata"]["duration_seconds"])
    except (FileNotFoundError, MediaValidationError, OSError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="The registered source video is invalid") from exc

    candidates = analysis.get("clips", [])
    selected = req.selected_clips
    if not selected or len(selected) > MAX_CLIPS:
        raise HTTPException(status_code=400, detail=f"Select between 1 and {MAX_CLIPS} clips")
    validated = []
    seen_clip_ids = set()
    for clip in selected:
        try:
            start = float(clip["start"])
            end = float(clip["end"])
        except (KeyError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail="Each clip requires numeric start and end times") from exc
        if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end <= start:
            raise HTTPException(status_code=400, detail="Clip times must be finite, non-negative, and ordered")
        if end > duration or end - start > MAX_CLIP_SECONDS:
            raise HTTPException(status_code=400, detail="Clip exceeds the source duration or maximum length")
        clip_id = clip.get("clip_id")
        if clip_id in seen_clip_ids:
            raise HTTPException(status_code=400, detail="A clip cannot be selected more than once")
        seen_clip_ids.add(clip_id)
        candidate = next((item for item in candidates if item.get("clip_id") == clip_id), None)
        if candidate is None:
            raise HTTPException(status_code=409, detail="Clip selection does not match this analysis")
        try:
            candidate_start, candidate_end = float(candidate["start"]), float(candidate["end"])
        except (KeyError, TypeError, ValueError):
            raise HTTPException(status_code=409, detail="Stored clip selection is invalid")
        if not math.isfinite(candidate_start) or not math.isfinite(candidate_end) or candidate_start < 0 or candidate_end <= candidate_start:
            raise HTTPException(status_code=409, detail="Stored clip selection is invalid")
        if start < candidate_start or end > candidate_end:
            raise HTTPException(status_code=400, detail="Edited clip times must stay within the analyzed segment")
        validated.append({**clip, "start": start, "end": end})
    fingerprint = hashlib.sha256(json.dumps(validated, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return source_path, validated, fingerprint


def run_render_task(job_id: str, source_path: str, selected_clips: list[dict], config: dict, project_id: str, fingerprint: str, analysis: dict):
    stop_event = get_stop_event(job_id)
    root = project_directory(project_id)
    output_dir = root / "output" / "clips"
    output_dir.mkdir(parents=True, exist_ok=True)
    try:
        def callback(_job_id, step, progress, result=None, error=None):
            add_log(job_id, step)
            if error:
                update_job(job_id, status="failed", error=error)
            else:
                update_job(job_id, progress=progress, step=step)

        outputs = render_youtube_clips(
            job_id, source_path, selected_clips, callback, config=config,
            output_dir=str(output_dir), language=str(config.get("PODCAST_LANGUAGE") or "English"),
            stop_event=stop_event,
        )
        if stop_event.is_set():
            update_job(job_id, status="cancelled")
            return
        if len(outputs) != len(selected_clips):
            raise RuntimeError("Clipper did not produce every selected clip")
        records = []
        public_clips = []
        for output in outputs:
            path = Path(output["path"]).resolve(strict=True)
            if not path.is_file() or not path.stat().st_size:
                raise RuntimeError("A selected clip output is missing or empty")
            probe_media(path, expected_kind="video")
            records.append({"path": path, "role": "final", "kind": "video"})
            public_clips.append({key: value for key, value in output.items() if key != "path"})
        complete_job(
            job_id,
            result={"type": "finished", "clips": public_clips, "render_fingerprint": fingerprint, "analysis": analysis},
            media_records=records,
        )
    except InterruptedError:
        update_job(job_id, status="cancelled")
    except Exception as exc:
        if stop_event.is_set() or get_job_status(job_id) == "cancel_requested":
            update_job(job_id, status="cancelled")
        else:
            add_log(job_id, f"Clipper rendering failed: {exc}")
            update_job(job_id, status="failed", error=str(exc))


@router.post("/render", status_code=202)
def start_render(req: RenderRequest):
    job = get_job(req.job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Clipper job not found")
    source_path, selected, fingerprint = _validated_render(req, job)
    payload = _selection_payload(job)
    saved_fingerprint = payload.get("render_fingerprint")
    if job["status"] in {"running", "completed"}:
        if saved_fingerprint == fingerprint:
            return {"job_id": job["id"], "project_id": job["project_id"], "status": job["status"], "message": "Matching render already submitted."}
        raise HTTPException(status_code=409, detail="A different render is already running or complete")
    if job["status"] != "awaiting_input":
        raise HTTPException(status_code=409, detail="Clipper job is not awaiting a selection")
    if saved_fingerprint:
        if saved_fingerprint == fingerprint:
            return {"job_id": job["id"], "project_id": job["project_id"], "status": job["status"],
                    "message": "Matching render already submitted."}
        raise HTTPException(status_code=409, detail="A different clip selection is already submitted")

    with _render_submission_lock:
        current = get_job(req.job_id)
        current_payload = _selection_payload(current or {})
        if not current or current["status"] != "awaiting_input":
            if current and current_payload.get("render_fingerprint") == fingerprint:
                return {"job_id": current["id"], "project_id": current["project_id"], "status": current["status"], "message": "Matching render already submitted."}
            raise HTTPException(status_code=409, detail="Clipper job changed while submitting the render")
        current_fingerprint = current_payload.get("render_fingerprint")
        if current_fingerprint:
            if current_fingerprint == fingerprint:
                return {"job_id": current["id"], "project_id": current["project_id"],
                        "status": current["status"], "message": "Matching render already submitted."}
            raise HTTPException(status_code=409, detail="A different clip selection is already submitted")
        if not current_payload.get("render_fingerprint"):
            current_payload["type"] = "render_queued"
            current_payload["render_fingerprint"] = fingerprint
            current_payload["selected_clips"] = selected
            update_job(req.job_id, result=current_payload)
        with _FROZEN_CONFIGS_LOCK:
            frozen = dict(_FROZEN_CONFIGS.get(req.job_id, {}))
        if not frozen:
            # A server restart preserves the selection but loses in-memory
            # credentials; restore frozen public options and only read current
            # local secret values for this explicit render.
            frozen = effective_config(job.get("settings") or {})
        try:
            future = submit_awaiting_input_to_queue(
                run_render_task, req.job_id, str(source_path), selected, frozen,
                job["project_id"], fingerprint, current_payload.get("analysis", current_payload)
            )
        except RuntimeError as exc:
            current_payload.pop("render_fingerprint", None)
            current_payload.pop("selected_clips", None)
            current_payload["type"] = "selection"
            update_job(req.job_id, result=current_payload)
            raise HTTPException(status_code=503, detail="The local worker queue is full; try again later") from exc
        if future is None:
            if get_job_status(req.job_id) == "awaiting_input":
                current_payload.pop("render_fingerprint", None)
                current_payload.pop("selected_clips", None)
                current_payload["type"] = "selection"
                update_job(req.job_id, result=current_payload)
            raise HTTPException(status_code=409, detail="Clipper render could not be claimed")
    return {"job_id": job["id"], "project_id": job["project_id"], "status": get_job_status(req.job_id),
            "message": "Selected clips queued for rendering."}
