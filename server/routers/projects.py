"""Project catalog and ID-based access to registered media."""

from __future__ import annotations

import os
import uuid
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from server.core import media_store, project_store
from server.core.media_store import MediaValidationError
from server.core.project_store import project_directory


router = APIRouter()
MAX_UPLOAD_BYTES = int(os.environ.get("MEDIENWERK_MAX_UPLOAD_BYTES", str(5 * 1024 * 1024 * 1024)))
UPLOAD_EXTENSIONS = {
    ".mp4", ".mov", ".mkv", ".webm", ".avi", ".mp3", ".wav", ".m4a",
    ".aac", ".flac", ".ogg", ".opus",
}


class ProjectCreate(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    kind: str = Field(min_length=1, max_length=80)
    config: dict = Field(default_factory=dict)


class LegacyImportRequest(BaseModel):
    roots: list[str] = Field(min_length=1, max_length=20)


@router.get("/summary")
def summary():
    return project_store.get_summary()


@router.get("/history")
def history(limit: int = Query(100, ge=1, le=500)):
    return project_store.get_history(limit=limit)


@router.get("/media/{media_id}/download")
def download_media(media_id: str):
    try:
        path = media_store.resolve_media(media_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Registered media not found") from exc
    except (MediaValidationError, ValueError) as exc:
        raise HTTPException(status_code=404, detail="Registered media path is unavailable") from exc
    return FileResponse(path, filename=path.name)


@router.post("/import/preview")
def preview_import(request: LegacyImportRequest):
    try:
        return media_store.preview_legacy_import(request.roots)
    except (MediaValidationError, OSError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/import/apply")
def apply_import(request: LegacyImportRequest):
    try:
        return media_store.apply_legacy_import(request.roots)
    except (MediaValidationError, OSError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("")
def create_project(request: ProjectCreate):
    try:
        return project_store.create_project(request.title, request.kind, request.config)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("")
def list_projects(limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0)):
    return project_store.list_projects(limit=limit, offset=offset)


@router.get("/{project_id}")
def get_project(project_id: str):
    project = project_store.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return {**project, "media": media_store.list_media(project_id)}


@router.get("/{project_id}/media")
def list_project_media(project_id: str):
    if project_store.get_project(project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return media_store.list_media(project_id)


@router.post("/{project_id}/media", status_code=201)
async def upload_media(project_id: str, file: UploadFile = File(...), role: str = "source"):
    if project_store.get_project(project_id) is None:
        raise HTTPException(status_code=404, detail="Project not found")
    extension = Path(file.filename or "").suffix.lower()
    content_type = (file.content_type or "").lower()
    if extension not in UPLOAD_EXTENSIONS or (content_type and not (content_type.startswith("video/") or content_type.startswith("audio/") or content_type == "application/octet-stream")):
        raise HTTPException(status_code=415, detail="Upload must be a supported audio or video file")
    upload_id = str(uuid.uuid4())
    target = project_directory(project_id) / "source" / f"{upload_id}{extension}"
    size = 0
    try:
        with target.open("xb") as output:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail="Upload exceeds the configured size limit")
                output.write(chunk)
        if size == 0:
            raise HTTPException(status_code=400, detail="Upload is empty")
        media = media_store.register_media(project_id, target, role=role)
        media["upload_name"] = file.filename
        return media
    except HTTPException:
        target.unlink(missing_ok=True)
        raise
    except (MediaValidationError, ValueError) as exc:
        target.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except OSError as exc:
        target.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail="Could not save uploaded media") from exc
    finally:
        await file.close()


@router.delete("/{project_id}/media/{media_id}")
def delete_media(project_id: str, media_id: str):
    try:
        if not media_store.unregister_media(media_id, project_id=project_id, delete_file=True):
            raise HTTPException(status_code=404, detail="Media not found for project")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"deleted": True}


@router.delete("/{project_id}")
def delete_project(project_id: str):
    try:
        if not project_store.delete_project(project_id):
            raise HTTPException(status_code=404, detail="Project not found")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"deleted": True}
