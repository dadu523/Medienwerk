"""Project-backed adapter for the existing Director editing engine."""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from config import ConfigValidationError, effective_config, sanitize_config
from server.core.media_store import MediaValidationError, probe_media
from server.core.project_store import project_directory
from server.core.queue import (
    add_log, complete_job, create_job, get_job, get_job_status, get_stop_event,
    submit_to_queue, update_job,
)
from server.core.director_engine import run_director_pipeline

router = APIRouter()


class DirectorRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2048)
    remove_silence: bool = True
    add_punch_ins: bool = True
    add_sfx: bool = True
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=255)


def _validate_url(value: str) -> str:
    url = value.strip()
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme not in {"http", "https"} or host not in {
        "youtu.be", "youtube.com", "www.youtube.com", "m.youtube.com"
    }:
        raise ConfigValidationError("Director currently supports YouTube video URLs")
    return url


def start_director(req: DirectorRequest) -> dict[str, Any]:
    url = _validate_url(req.url)
    snapshot = effective_config()
    request_fingerprint = hashlib.sha256(json.dumps({
        "url": url, "remove_silence": req.remove_silence,
        "add_punch_ins": req.add_punch_ins, "add_sfx": req.add_sfx,
        "config": snapshot,
    }, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    settings = {
        **sanitize_config(snapshot),
        "remove_silence": req.remove_silence,
        "add_punch_ins": req.add_punch_ins,
        "add_sfx": req.add_sfx,
        "source_url": url,
        "request_fingerprint": request_fingerprint,
    }
    job_id = create_job(
        f"Director: {url[:100]}", workflow="director", settings=settings,
        idempotency_key=req.idempotency_key,
    )
    job = get_job(job_id)
    if not job:
        raise RuntimeError("Could not read the Director job")
    if (job.get("settings") or {}).get("request_fingerprint") != request_fingerprint:
        raise HTTPException(status_code=409, detail="Idempotency key was already used for different Director options")
    if job["status"] == "queued":
        try:
            submit_to_queue(run_director_task, job_id, req, snapshot, job["project_id"])
        except RuntimeError as exc:
            update_job(job_id, status="failed", error="The local worker queue is full. Start a new attempt later.")
            raise RuntimeError("The local worker queue is full; try again later") from exc
    return {
        "job_id": job_id,
        "project_id": job["project_id"],
        "status": get_job_status(job_id),
        "message": "Director job queued successfully." if job["status"] == "queued" else "Existing job returned.",
    }


def run_director_task(
    job_id: str,
    req: DirectorRequest,
    config_snapshot: dict[str, Any] | None = None,
    project_id: str | None = None,
) -> None:
    stop_event = get_stop_event(job_id)
    try:
        job = get_job(job_id)
        if job is None:
            raise ValueError("Director job no longer exists")
        project_id = project_id or job["project_id"]
        root = project_directory(project_id)
        source_dir = root / "source"
        work_dir = root / "intermediate" / job_id
        output_dir = root / "output"
        work_dir.mkdir(parents=True, exist_ok=True)
        final_path = output_dir / "final_master.mp4"

        def progress(_job_id: str, step: str, progress: float, result=None, error=None):
            add_log(job_id, step)
            if error:
                update_job(job_id, status="failed", step=step, error=error)
            else:
                update_job(job_id, progress=progress, step=step)

        produced = run_director_pipeline(
            _validate_url(req.url), job_id, progress,
            remove_silence=req.remove_silence,
            add_punch_ins=req.add_punch_ins,
            add_sfx=req.add_sfx,
            output_dir=str(work_dir), source_dir=str(source_dir),
            final_path=str(final_path), stop_event=stop_event,
            config=config_snapshot or effective_config(),
        )
        if stop_event.is_set():
            update_job(job_id, status="cancelled")
            return
        result_path = Path(produced).resolve(strict=True)
        if not result_path.is_file() or result_path.stat().st_size == 0:
            raise RuntimeError("Director did not produce a readable final video")
        probe_media(result_path, expected_kind="video")
        source_candidates = [path for path in source_dir.iterdir() if path.is_file() and path.suffix.lower() in {".mp4", ".mkv", ".webm", ".mov"}]
        if not source_candidates:
            raise RuntimeError("Director source video is missing")
        source_path = max(source_candidates, key=lambda path: path.stat().st_mtime).resolve(strict=True)
        probe_media(source_path, expected_kind="video")
        complete_job(
            job_id,
            result={"path": "output/final_master.mp4", "options": {
                "remove_silence": req.remove_silence,
                "add_punch_ins": req.add_punch_ins,
                "add_sfx": req.add_sfx,
            }},
            media_records=[
                {"path": source_path, "role": "source", "kind": "video"},
                {"path": result_path, "role": "final", "kind": "video",
                 "require_audio": any(stream.get("type") == "audio" for stream in probe_media(result_path, expected_kind="video")["metadata"]["streams"])},
            ],
        )
    except InterruptedError:
        update_job(job_id, status="cancelled")
    except Exception as exc:
        if stop_event.is_set() or get_job_status(job_id) == "cancel_requested":
            update_job(job_id, status="cancelled")
        else:
            logging.exception("Director job %s failed", job_id)
            update_job(job_id, status="failed", error=str(exc))


@router.post("/process", status_code=202)
def start_director_route(req: DirectorRequest):
    try:
        return start_director(req)
    except ConfigValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
