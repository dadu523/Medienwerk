"""Publish registered final videos; never resolve caller-supplied file paths."""

from __future__ import annotations

import pickle
import traceback
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from server.core.database import Media, SessionLocal
from server.core.media_store import MediaValidationError, probe_media, resolve_media
from server.core.project_store import list_projects

router = APIRouter()


class PublishRequest(BaseModel):
    # ``video_path`` is retained for the existing UI, but now carries the
    # registered media ID. Arbitrary paths are rejected.
    video_path: str | None = None
    media_id: str | None = None
    title: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=5000)
    tags: str = Field(default="", max_length=500)
    privacy_status: str = "private"


def get_publishing_library() -> dict[str, list[dict[str, Any]]]:
    projects = []
    for project in list_projects(limit=500):
        with SessionLocal() as db:
            media = db.query(Media).filter(
                Media.project_id == project["id"],
                Media.role == "final",
                Media.media_type.like("video/%"),
            ).order_by(Media.created_at.desc()).all()
            rows = [{
                "id": item.id,
                "name": project["title"],
                "project_id": project["id"],
                "video_path": item.id,
                "media_id": item.id,
                "video_url": f"/api/projects/media/{item.id}/download",
                "seo": {"title": project["title"], "description": "", "tags": ""},
            } for item in media]
        projects.extend(rows)
    return {"projects": projects}


def _registered_video(media_id: str):
    with SessionLocal() as db:
        item = db.get(Media, media_id)
        if item is None or item.role != "final" or not item.media_type.startswith("video/"):
            raise HTTPException(status_code=400, detail="Select a registered final video")
    try:
        path = resolve_media(media_id)
        probe_media(path, expected_kind="video")
    except (FileNotFoundError, MediaValidationError, OSError) as exc:
        raise HTTPException(status_code=400, detail="The registered video is missing or invalid") from exc
    return path


@router.get("/library")
def get_publishing_library_route():
    return get_publishing_library()


@router.post("/youtube")
def publish_to_youtube(req: PublishRequest):
    media_id = req.media_id or req.video_path
    if not media_id:
        raise HTTPException(status_code=400, detail="A registered media_id is required")
    video_path = _registered_video(media_id)
    if req.privacy_status not in {"private", "unlisted", "public"}:
        raise HTTPException(status_code=400, detail="Invalid YouTube privacy status")
    if not Path("client_secrets.json").is_file():
        raise HTTPException(status_code=400, detail="YouTube OAuth client secrets are not configured")

    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaFileUpload

        credentials = None
        token_path = Path("token.pickle")
        if token_path.is_file():
            with token_path.open("rb") as token:
                credentials = pickle.load(token)
        if not credentials or not credentials.valid:
            if credentials and credentials.expired and credentials.refresh_token:
                credentials.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    "client_secrets.json", scopes=["https://www.googleapis.com/auth/youtube.upload"],
                    redirect_uri="http://localhost:8080/",
                )
                credentials = flow.run_local_server(port=8080)
            with token_path.open("wb") as token:
                pickle.dump(credentials, token)

        youtube = build("youtube", "v3", credentials=credentials)
        body = {
            "snippet": {
                "title": req.title,
                "description": req.description,
                "tags": [tag.strip() for tag in req.tags.split(",") if tag.strip()],
                "categoryId": "22",
            },
            "status": {"privacyStatus": req.privacy_status},
        }
        upload = MediaFileUpload(str(video_path), chunksize=-1, resumable=True)
        request = youtube.videos().insert(part=",".join(body.keys()), body=body, media_body=upload)
        response = None
        while response is None:
            _, response = request.next_chunk()
        return {"message": "Video uploaded successfully!", "video_id": response.get("id")}
    except HTTPException:
        raise
    except Exception as exc:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Upload failed: {exc}") from exc
