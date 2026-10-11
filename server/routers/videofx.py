"""Local browser automation adapter for the VideoFX workflow."""

from __future__ import annotations

import logging
import hashlib
import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from config import effective_config, sanitize_config
from server.core.media_store import probe_media
from server.core.project_store import project_directory
from server.core.queue import add_log, complete_job, create_job, get_job, get_job_status, get_stop_event, manager, stop_job, submit_to_queue, update_job
from server.core.videofx_client import VideoFXClient

router = APIRouter()


class VideoFXRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=2000)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=255)


def start_videofx(req: VideoFXRequest) -> dict:
    snapshot = effective_config()
    fingerprint = hashlib.sha256(json.dumps({"prompt": req.prompt.strip()}, sort_keys=True,
                                            separators=(",", ":")).encode()).hexdigest()
    job_id = create_job(
        "VideoFX generation", workflow="videofx",
        settings={**sanitize_config(snapshot), "prompt": req.prompt.strip(), "request_fingerprint": fingerprint},
        idempotency_key=req.idempotency_key,
    )
    job = get_job(job_id)
    if not job:
        raise RuntimeError("Could not read the VideoFX job")
    if (job.get("settings") or {}).get("request_fingerprint") != fingerprint:
        raise HTTPException(status_code=409, detail="Idempotency key was already used for a different VideoFX prompt")
    if job["status"] == "queued":
        try:
            submit_to_queue(run_videofx_task, job_id, req, job["project_id"])
        except RuntimeError as exc:
            update_job(job_id, status="failed", error="The local worker queue is full. Start a new attempt later.")
            raise RuntimeError("The local worker queue is full; try again later") from exc
    return {"job_id": job_id, "project_id": job["project_id"], "status": get_job_status(job_id),
            "message": "VideoFX browser job queued." if job["status"] == "queued" else "Existing job returned."}


def run_videofx_task(job_id: str, req: VideoFXRequest, project_id: str | None = None) -> None:
    stop_event = get_stop_event(job_id)
    try:
        job = get_job(job_id)
        if not job:
            raise ValueError("VideoFX job no longer exists")
        project_id = project_id or job["project_id"]
        root = project_directory(project_id)
        output_path = root / "output" / "videofx.mp4"
        profile_path = str(Path(__file__).resolve().parent.parent / "core" / "videofx_profile")
        client = VideoFXClient(profile_path)
        add_log(job_id, "Opening the VideoFX browser workflow")

        def frame_callback(frame: str):
            # Frames are transient and can be large; the job's durable event log
            # remains bounded and contains state/log events only.
            manager.broadcast(job_id, {"type": "browser_frame", "data": frame})

        client.generate_video(req.prompt.strip(), str(output_path), on_frame_callback=frame_callback, stop_event=stop_event)
        if stop_event.is_set():
            update_job(job_id, status="cancelled")
            return
        path = output_path.resolve(strict=True)
        if not path.is_file() or path.stat().st_size == 0:
            raise RuntimeError("VideoFX did not produce a readable output")
        probe_media(path, expected_kind="video")
        complete_job(job_id, result={"path": "output/videofx.mp4", "workflow": "browser_automation"},
                     media_records=[{"path": path, "role": "final", "kind": "video", "require_audio": False}])
    except InterruptedError:
        update_job(job_id, status="cancelled")
    except Exception as exc:
        if stop_event.is_set() or get_job_status(job_id) == "cancel_requested":
            update_job(job_id, status="cancelled")
        else:
            logging.exception("VideoFX job %s failed", job_id)
            update_job(job_id, status="failed", error=str(exc))


@router.post("/generate", status_code=202)
def start_videofx_route(req: VideoFXRequest):
    try:
        return start_videofx(req)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.delete("/job/{job_id}")
def stop_videofx_job(job_id: str):
    if get_job(job_id) is None:
        raise HTTPException(status_code=404, detail="Job not found")
    stop_job(job_id)
    return {"message": "Job cancellation requested."}


@router.post("/login")
def start_login():
    profile_path = str(Path(__file__).resolve().parent.parent / "core" / "videofx_profile")
    import threading

    def open_login_browser():
        try:
            VideoFXClient(profile_path).login_if_needed()
        except Exception:
            logging.exception("VideoFX login browser failed")

    threading.Thread(target=open_login_browser, name="videofx-login", daemon=True).start()
    # Starting the browser only lets the user inspect/sign in; it does not
    # verify or persist an authenticated session.
    return {"status": "browser_opened", "authenticated": False,
            "message": "Browser opened. Sign in there if needed; authentication is not verified by this action."}


@router.websocket("/ws/{job_id}")
async def videofx_websocket_endpoint(websocket: WebSocket, job_id: str):
    if get_job(job_id) is None:
        await websocket.close(code=4404)
        return
    await manager.connect(websocket, job_id)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket, job_id)
