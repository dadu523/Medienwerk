"""Project-backed adapter for the existing Explainer engine."""

from __future__ import annotations

import logging
import hashlib
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from config import ConfigValidationError, effective_config, sanitize_config, validate_provider_config
from server.core.media_store import probe_media, register_media
from server.core.project_store import project_directory
from server.core.queue import add_log, complete_job, create_job, get_job, get_job_status, get_stop_event, submit_to_queue, update_job
from server.core.explainer_engine import ExplainerEngine

router = APIRouter()
_DURATIONS = {"1 minute", "3 minutes", "5 minutes", "10 minutes"}


class ExplainerRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2048)
    target_duration: str = "5 minutes"
    language: str = "English"
    voice: str = "Kore"
    text_engine: str = "Gemini API"
    audio_engine: str = "Gemini API"
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=255)


def _validate_request(req: ExplainerRequest, config: dict[str, Any]) -> str:
    url = req.url.strip()
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme not in {"http", "https"} or host not in {
        "youtu.be", "youtube.com", "www.youtube.com", "m.youtube.com"
    }:
        raise ConfigValidationError("Explainer currently supports YouTube video URLs")
    if req.target_duration not in _DURATIONS:
        raise ConfigValidationError("Target duration must be 1, 3, 5, or 10 minutes")
    config["TEXT_ENGINE"] = req.text_engine
    config["AUDIO_ENGINE"] = req.audio_engine
    config["VOICE_NAME"] = req.voice
    config["SPEAKER1"] = req.voice
    validate_provider_config(config, kind="text")
    validate_provider_config(config, kind="tts")
    if not req.language.strip() or len(req.language) > 80:
        raise ConfigValidationError("Language must contain 1 to 80 characters")
    if not req.voice.strip() or len(req.voice) > 80:
        raise ConfigValidationError("Voice must contain 1 to 80 characters")
    return url


def start_explainer(req: ExplainerRequest) -> dict[str, Any]:
    snapshot = effective_config()
    url = _validate_request(req, snapshot)
    request_fingerprint = hashlib.sha256(json.dumps({
        "url": url, "target_duration": req.target_duration, "language": req.language,
        "voice": req.voice, "text_engine": req.text_engine, "audio_engine": req.audio_engine,
        "config": snapshot,
    }, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    settings = {
        **sanitize_config(snapshot), "source_url": url,
        "target_duration": req.target_duration, "language": req.language,
        "voice": req.voice, "text_engine": req.text_engine, "audio_engine": req.audio_engine,
        "request_fingerprint": request_fingerprint,
    }
    job_id = create_job(
        "Movie explainer", workflow="explainer", settings=settings,
        idempotency_key=req.idempotency_key,
    )
    job = get_job(job_id)
    if not job:
        raise RuntimeError("Could not read the Explainer job")
    if (job.get("settings") or {}).get("request_fingerprint") != request_fingerprint:
        raise HTTPException(status_code=409, detail="Idempotency key was already used for different Explainer options")
    if job["status"] == "queued":
        try:
            submit_to_queue(run_explainer_task, job_id, req, snapshot, job["project_id"])
        except RuntimeError as exc:
            update_job(job_id, status="failed", error="The local worker queue is full. Start a new attempt later.")
            raise RuntimeError("The local worker queue is full; try again later") from exc
    return {
        "job_id": job_id, "project_id": job["project_id"],
        "status": get_job_status(job_id),
        "message": "Explainer job queued successfully." if job["status"] == "queued" else "Existing job returned.",
    }


def run_explainer_task(
    job_id: str,
    req: ExplainerRequest,
    config_snapshot: dict[str, Any] | None = None,
    project_id: str | None = None,
) -> None:
    stop_event = get_stop_event(job_id)
    try:
        job = get_job(job_id)
        if job is None:
            raise ValueError("Explainer job no longer exists")
        project_id = project_id or job["project_id"]
        snapshot = dict(config_snapshot or effective_config())
        _validate_request(req, snapshot)
        root = project_directory(project_id)
        source_dir = root / "source"
        work_dir = root / "intermediate" / job_id
        final_path = root / "output" / "final_explainer.mp4"
        work_dir.mkdir(parents=True, exist_ok=True)

        def on_progress(step: str, progress: float):
            add_log(job_id, step)
            update_job(job_id, step=step, progress=progress)

        engine = ExplainerEngine(
            job_id=job_id,
            url=req.url.strip(),
            target_duration=req.target_duration,
            language=req.language,
            voice=req.voice,
            text_engine=req.text_engine,
            audio_engine=req.audio_engine,
            on_progress=on_progress,
            config=snapshot,
            output_dir=str(work_dir),
            source_dir=str(source_dir),
            final_path=str(final_path),
            stop_event=stop_event,
        )
        produced = engine.process()
        if stop_event.is_set():
            update_job(job_id, status="cancelled")
            return
        path = Path(produced).resolve(strict=True)
        if not path.is_file() or path.stat().st_size == 0:
            raise RuntimeError("Explainer did not produce a readable final video")
        probe_media(path, expected_kind="video")
        source_path = Path(engine.video_path).resolve(strict=True)
        probe_media(source_path, expected_kind="video")
        complete_job(
            job_id,
            result={"path": "output/final_explainer.mp4", "language": req.language,
                    "voice": req.voice, "target_duration": req.target_duration},
            media_records=[
                {"path": source_path, "role": "source", "kind": "video"},
                {"path": path, "role": "final", "kind": "video"},
            ],
        )
    except InterruptedError:
        update_job(job_id, status="cancelled")
    except Exception as exc:
        if stop_event.is_set() or get_job_status(job_id) == "cancel_requested":
            update_job(job_id, status="cancelled")
        else:
            logging.exception("Explainer job %s failed", job_id)
            update_job(job_id, status="failed", error=str(exc))


@router.post("/process", status_code=202)
def start_explainer_route(req: ExplainerRequest):
    try:
        return start_explainer(req)
    except ConfigValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
