"""Queued video tools whose results share the project and media registry."""

from __future__ import annotations

import os
import hashlib
import re
import shutil
import tempfile
import threading
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

import pipeline
from api_clients import STYLE_PROFILES
from config import (
    ConfigFileError,
    ConfigValidationError,
    effective_config,
    sanitize_config,
    validate_provider_config,
)
from server.core.database import Job, SessionLocal
from server.core.media_store import MediaValidationError, probe_media, register_media
from server.core.process_runner import ProcessCancelledError, run_process
from server.core.project_store import project_directory
from server.core.provider_adapters import synthesize_speech
from server.core.queue import complete_job, create_job, get_job, get_job_status, get_stop_event, submit_to_queue, update_job

router = APIRouter()
_TOOL_JOB_LOCK = threading.RLock()
MAX_UPLOAD_BYTES = int(os.environ.get("MEDIENWERK_TOOLS_MAX_UPLOAD_BYTES", str(250 * 1024 * 1024)))
ALLOWED_VIDEO_SUFFIXES = {".mp4", ".mov", ".mkv", ".webm", ".avi"}


class TTSRequest(BaseModel):
    text: str = Field(min_length=1, max_length=100_000)
    voice: str = Field(default="Kore", min_length=1, max_length=80)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=255)


async def _receive_video(file: UploadFile) -> tuple[Path, str]:
    suffix = Path(file.filename or "video.mp4").suffix.lower()
    if suffix not in ALLOWED_VIDEO_SUFFIXES:
        raise HTTPException(status_code=415, detail="Upload must be a supported video file")
    content_type = (file.content_type or "").lower()
    if content_type and not (content_type.startswith("video/") or content_type == "application/octet-stream"):
        raise HTTPException(status_code=415, detail="Upload content type must be video")
    temporary = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    temp_path = Path(temporary.name)
    size = 0
    try:
        with temporary:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail="Upload exceeds the configured size limit")
                temporary.write(chunk)
        if size == 0:
            raise HTTPException(status_code=400, detail="Upload is empty")
        probe_media(temp_path, expected_kind="video")
        return temp_path, suffix
    except HTTPException:
        temp_path.unlink(missing_ok=True)
        raise
    except MediaValidationError as exc:
        temp_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except OSError as exc:
        temp_path.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail="Could not receive the uploaded video") from exc
    finally:
        await file.close()


def _existing_idempotent_job(
    workflow: str,
    key: str | None,
    expected_settings: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if not key:
        return None
    with SessionLocal() as db:
        row = db.query(Job).filter(Job.workflow == workflow, Job.idempotency_key == key).first()
        job = get_job(row.id) if row is not None else None
    if job is not None and expected_settings is not None:
        saved_settings = job.get("settings") or {}
        expected = sanitize_config(expected_settings)
        if any(saved_settings.get(field) != value for field, value in expected.items()):
            raise HTTPException(status_code=409, detail="Idempotency key was already used for different Video Tools options")
    return job


def _create_tool_job(
    workflow: str,
    title: str,
    settings: dict[str, Any],
    idempotency_key: str | None,
) -> dict[str, Any]:
    job_id = create_job(
        title,
        workflow=workflow,
        settings=sanitize_config(settings),
        idempotency_key=idempotency_key,
    )
    job = get_job(job_id)
    if job is None:
        raise RuntimeError("Could not read the newly created Video Tools job")
    return job


async def _queue_uploaded_file_job(
    workflow: str,
    title: str,
    file: UploadFile,
    *,
    settings: dict[str, Any],
    idempotency_key: str | None,
    task,
    task_options: dict[str, Any],
) -> dict[str, Any]:
    try:
        existing = _existing_idempotent_job(workflow, idempotency_key, expected_settings=settings)
    except HTTPException:
        await file.close()
        raise
    if existing:
        await file.close()
        return {"job_id": existing["id"], "project_id": existing["project_id"], "status": existing["status"], "message": "Existing job returned."}

    temporary_path, suffix = await _receive_video(file)
    try:
        return _finalize_uploaded_file_job(
            workflow, title, temporary_path, suffix, settings=settings,
            idempotency_key=idempotency_key, task=task, task_options=task_options,
        )
    finally:
        temporary_path.unlink(missing_ok=True)


def _finalize_uploaded_file_job(
    workflow: str,
    title: str,
    temporary_path: Path,
    suffix: str,
    *,
    settings: dict[str, Any],
    idempotency_key: str | None,
    task,
    task_options: dict[str, Any],
) -> dict[str, Any]:
    with _TOOL_JOB_LOCK:
        existing = _existing_idempotent_job(workflow, idempotency_key, expected_settings=settings)
        if existing:
            return {"job_id": existing["id"], "project_id": existing["project_id"], "status": existing["status"], "message": "Existing job returned."}
        job = _create_tool_job(workflow, title, settings, idempotency_key)
        try:
            source = project_directory(job["project_id"]) / "source" / f"{job['id']}{suffix}"
            with source.open("xb") as output, temporary_path.open("rb") as input_file:
                shutil.copyfileobj(input_file, output, length=1024 * 1024)
            register_media(job["project_id"], source, role="source", kind="video")
            submit_to_queue(task, job["id"], job["project_id"], str(source), **task_options)
            return {
                "job_id": job["id"], "project_id": job["project_id"], "status": "queued",
                "message": "Video tool job queued successfully.",
            }
        except Exception as exc:
            update_job(job["id"], status="failed", error=str(exc))
            raise


def _run_ffmpeg(args: list[str], stop_event, timeout: int = 1200) -> None:
    try:
        run_process(args, stop_event=stop_event, timeout=timeout, check=True, capture_output=True)
    except ProcessCancelledError as exc:
        raise InterruptedError("Video tool job was cancelled") from exc


def run_convert_job(job_id: str, project_id: str, input_path: str, target_ar: str) -> None:
    stop_event = get_stop_event(job_id)
    try:
        source = Path(input_path)
        project_path = project_directory(project_id)
        output = project_path / "output" / f"converted_{target_ar.replace(':', 'x')}.mp4"
        sizes = {"16:9": (1920, 1080), "9:16": (1080, 1920), "1:1": (1080, 1080)}
        width, height = sizes[target_ar]
        probe = probe_media(source, expected_kind="video")
        has_audio = any(stream.get("type") == "audio" for stream in probe["metadata"]["streams"])
        vf = f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1"
        args = ["ffmpeg", "-y", "-i", str(source)]
        if not has_audio:
            args.extend(["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100"])
            args.extend(["-map", "0:v:0", "-map", "1:a:0", "-shortest"])
        else:
            args.extend(["-map", "0:v:0", "-map", "0:a:0?"])
        args.extend(["-vf", vf, "-c:v", "libx264", "-preset", "fast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-movflags", "+faststart", str(output)])
        _run_ffmpeg(args, stop_event)
        if stop_event.is_set():
            update_job(job_id, status="cancelled")
            return
        complete_job(job_id, result={"target_aspect_ratio": target_ar}, media_records=[{"path": output, "role": "final", "kind": "video"}])
    except InterruptedError:
        update_job(job_id, status="cancelled")
    except Exception as exc:
        if stop_event.is_set():
            update_job(job_id, status="cancelled")
        else:
            update_job(job_id, status="failed", error=str(exc))


def run_caption_job(job_id: str, project_id: str, input_path: str, *, style: str, language: str) -> None:
    stop_event = get_stop_event(job_id)
    try:
        project_path = project_directory(project_id)
        caption_file = project_path / "intermediate" / "captions.ass"
        output = project_path / "output" / "captioned_video.mp4"
        style_opts = STYLE_PROFILES.get(style, STYLE_PROFILES["Podcast"])
        source_probe = probe_media(Path(input_path), expected_kind="video")
        if not any(stream.get("type") == "audio" for stream in source_probe["metadata"]["streams"]):
            raise MediaValidationError("Caption generation requires a video with an audio stream")
        pipeline.generate_captions(input_path, str(caption_file), language, style_opts=style_opts)
        if stop_event.is_set():
            update_job(job_id, status="cancelled")
            return
        subs_path = str(caption_file.resolve()).replace("\\", "/").replace(":", "\\:")
        args = [
            "ffmpeg", "-y", "-i", input_path, "-vf", f"subtitles='{subs_path}'",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "copy", str(output),
        ]
        _run_ffmpeg(args, stop_event)
        if stop_event.is_set():
            update_job(job_id, status="cancelled")
            return
        complete_job(job_id, result={"style": style, "language": language}, media_records=[{"path": output, "role": "final", "kind": "video"}])
    except InterruptedError:
        update_job(job_id, status="cancelled")
    except Exception as exc:
        if stop_event.is_set():
            update_job(job_id, status="cancelled")
        else:
            update_job(job_id, status="failed", error=str(exc))


def run_tts_job(job_id: str, project_id: str, text: str, config: dict[str, Any], voice: str) -> None:
    stop_event = get_stop_event(job_id)
    try:
        extension = ".mp3" if config.get("AUDIO_ENGINE") == "WaveSpeed AI" else ".wav"
        output = project_directory(project_id) / "output" / f"voiceover{extension}"
        synthesize_speech(config, text, str(output), voice=voice, stop_event=stop_event)
        if stop_event.is_set():
            update_job(job_id, status="cancelled")
            return
        complete_job(job_id, result={"voice": voice}, media_records=[{"path": output, "role": "final", "kind": "audio"}])
    except Exception as exc:
        if stop_event.is_set():
            update_job(job_id, status="cancelled")
        else:
            update_job(job_id, status="failed", error=str(exc))


@router.post("/caption", status_code=202)
async def generate_captions(
    file: UploadFile = File(...),
    style: str = Form("Podcast"),
    language: str = Form("English"),
    idempotency_key: str | None = Form(default=None, max_length=255),
):
    workflow = "video_tools.caption"
    settings = {"style": style, "language": language}
    try:
        return await _queue_uploaded_file_job(
            workflow, file.filename or "Captioned Video", file,
            settings=settings, idempotency_key=idempotency_key,
            task=run_caption_job, task_options={"style": style, "language": language},
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/convert", status_code=202)
async def convert_aspect_ratio(
    file: UploadFile = File(...),
    target_ar: str = Form("16:9"),
    idempotency_key: str | None = Form(default=None, max_length=255),
):
    if target_ar not in {"16:9", "9:16", "1:1"}:
        raise HTTPException(status_code=400, detail="Target aspect ratio must be 16:9, 9:16, or 1:1")
    workflow = "video_tools.convert"
    try:
        return await _queue_uploaded_file_job(
            workflow, file.filename or "Converted Video", file,
            settings={"target_aspect_ratio": target_ar}, idempotency_key=idempotency_key,
            task=run_convert_job, task_options={"target_ar": target_ar},
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/tts", status_code=202)
def generate_tts(req: TTSRequest):
    try:
        config = effective_config()
        validate_provider_config(config, kind="tts")
        if config.get("AUDIO_ENGINE") == "Gemini API":
            from config import VOICE_OPTIONS
            if req.voice not in VOICE_OPTIONS:
                raise ConfigValidationError("Selected voice is not supported by Gemini TTS")
        text_fingerprint = hashlib.sha256(req.text.encode("utf-8")).hexdigest()
        settings = {
            "voice": req.voice,
            "text_fingerprint": text_fingerprint,
            "config": sanitize_config(config),
        }
        request_settings = {"voice": req.voice, "text_fingerprint": text_fingerprint}
        with _TOOL_JOB_LOCK:
            existing = _existing_idempotent_job("video_tools.tts", req.idempotency_key, expected_settings=request_settings)
            if existing:
                return {"job_id": existing["id"], "project_id": existing["project_id"], "status": existing["status"], "message": "Existing job returned."}
            job = _create_tool_job("video_tools.tts", "Text to speech", settings, req.idempotency_key)
            try:
                submit_to_queue(run_tts_job, job["id"], job["project_id"], req.text, config, req.voice)
            except Exception as exc:
                update_job(job["id"], status="failed", error=f"Could not submit TTS job: {exc}")
                raise
            return {"job_id": job["id"], "project_id": job["project_id"], "status": job["status"], "message": "TTS job queued successfully."}
    except ConfigValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ConfigFileError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
