"""Project CRUD and compatibility views over the shared SQLite catalog."""

from __future__ import annotations

import json
import os
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func

from server.core.database import Job, Media, Project, SessionLocal, WORKSPACE, utcnow


ACTIVE_JOB_STATES = {"queued", "running", "awaiting_input", "cancel_requested"}
SECRET_KEY_PARTS = ("api_key", "secret", "token", "password", "credential")


def _sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _sanitize(item)
            for key, item in value.items()
            if not any(part in str(key).lower() for part in SECRET_KEY_PARTS)
        }
    if isinstance(value, (list, tuple)):
        return [_sanitize(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def project_directory(project_id: str, *, create: bool = True) -> Path:
    """Resolve a registered project's dedicated directory under workspace/projects."""
    try:
        normalized = str(uuid.UUID(str(project_id)))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError("Invalid project ID") from exc
    projects_root = WORKSPACE / "projects"
    if projects_root.exists() and projects_root.is_symlink():
        raise ValueError("Project storage root cannot be a symlink")
    projects_root.mkdir(parents=True, exist_ok=True)
    projects_root = projects_root.resolve(strict=True)
    directory = projects_root / normalized
    if directory.exists() and directory.is_symlink():
        raise ValueError("Project directory cannot be a symlink")
    if create:
        directory.mkdir(parents=True, exist_ok=True)
        for child in ("source", "intermediate", "output"):
            child_path = directory / child
            if child_path.exists() and child_path.is_symlink():
                raise ValueError("Project subdirectories cannot be symlinks")
            child_path.mkdir(exist_ok=True)
    resolved = directory.resolve(strict=create)
    if not resolved.is_relative_to(projects_root):
        raise ValueError("Project path escaped the workspace")
    return resolved


def _project_dict(project: Project) -> dict[str, Any]:
    try:
        config = json.loads(project.config_json or "{}")
    except (TypeError, json.JSONDecodeError):
        config = {}
    return {
        "id": project.id,
        "title": project.title,
        "kind": project.kind,
        "type": project.kind,
        "status": project.status,
        "created_at": project.created_at.isoformat() if project.created_at else None,
        "updated_at": project.updated_at.isoformat() if project.updated_at else None,
        "config": config,
    }


def create_project(title: str, kind: str, config: dict | None = None) -> dict[str, Any]:
    title = str(title).strip()
    kind = str(kind).strip()
    if not title or len(title) > 500:
        raise ValueError("Project title must contain 1 to 500 characters")
    if not kind or len(kind) > 80:
        raise ValueError("Project kind must contain 1 to 80 characters")
    project = Project(
        id=str(uuid.uuid4()), title=title, kind=kind, status="created",
        config_json=json.dumps(_sanitize(config or {}), ensure_ascii=False, separators=(",", ":")),
    )
    with SessionLocal.begin() as db:
        db.add(project)
        db.flush()
        payload = _project_dict(project)
    project_directory(payload["id"])
    return payload


def get_project(project_id: str) -> dict[str, Any] | None:
    with SessionLocal() as db:
        project = db.get(Project, str(project_id))
        return _project_dict(project) if project else None


def list_projects(*, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit), 500))
    offset = max(0, int(offset))
    with SessionLocal() as db:
        projects = (
            db.query(Project).order_by(Project.updated_at.desc(), Project.id).offset(offset).limit(limit).all()
        )
        return [_project_dict(project) for project in projects]


def set_project_status(project_id: str, status: str) -> bool:
    with SessionLocal.begin() as db:
        project = db.get(Project, str(project_id))
        if not project:
            return False
        project.status = str(status)
        project.updated_at = utcnow()
        return True


def get_history(*, limit: int = 100) -> list[dict[str, Any]]:
    """Return the legacy history envelope, populated only from registered media."""
    limit = max(1, min(int(limit), 500))
    with SessionLocal() as db:
        projects = db.query(Project).order_by(Project.updated_at.desc()).limit(limit).all()
        result = []
        for project in projects:
            media = (
                db.query(Media).filter(Media.project_id == project.id)
                .order_by(Media.created_at.desc()).all()
            )
            videos = []
            audios = []
            scripts = []
            for item in media:
                if item.media_type.startswith("video/") and item.role == "final":
                    videos.append({
                        "id": item.id,
                        "title": Path(item.relative_path).name,
                        "path": item.relative_path,
                        "url": f"/api/projects/media/{item.id}/download",
                    })
                elif item.media_type.startswith("audio/") and item.role == "final":
                    audios.append({
                        "id": item.id,
                        "title": Path(item.relative_path).name,
                        "path": item.relative_path,
                        "url": f"/api/projects/media/{item.id}/download",
                        "media_type": item.media_type,
                    })
                elif item.role == "script":
                    scripts.append({"id": item.id, "path": item.relative_path})
            result.append({
                "id": project.id, "title": project.title, "type": project.kind,
                "kind": project.kind, "status": project.status,
                "created_at": project.created_at.isoformat() if project.created_at else None,
                "videos": videos, "audios": audios, "scripts": scripts,
            })
        return result


def get_summary() -> dict[str, Any]:
    with SessionLocal() as db:
        projects = db.query(func.count(Project.id)).scalar() or 0
        media_count = db.query(func.count(Media.id)).scalar() or 0
        jobs_by_status = dict(
            db.query(Job.status, func.count(Job.id)).group_by(Job.status).all()
        )
        return {"projects": projects, "media": media_count, "jobs_by_status": jobs_by_status}


def delete_project(project_id: str) -> bool:
    """Delete a project and native files; imported legacy files are only unregistered."""
    with SessionLocal() as db:
        project = db.get(Project, str(project_id))
        if not project:
            return False
        active = db.query(Job.id).filter(
            Job.project_id == project.id, Job.status.in_(ACTIVE_JOB_STATES)
        ).first()
        if active:
            raise ValueError("Project has an active job and cannot be deleted")
        media_rows = db.query(Media).filter(Media.project_id == project.id).all()
        paths = []
        native_root = project_directory(project.id, create=False)
        for media in media_rows:
            if media.origin == "native":
                media_path = _path_for_media(media.storage_root, media.relative_path)
                if media_path.is_relative_to(native_root):
                    paths.append(media_path)
        db.delete(project)
        db.commit()
    # Remove only paths that were verified under this project's UUID directory.
    for path in paths:
        if path.exists() and path.is_file() and not path.is_symlink():
            path.unlink()
    _remove_tree_without_following_symlinks(native_root)
    return True


def _path_for_media(storage_root: str, relative_path: str) -> Path:
    root = Path(storage_root)
    relative = Path(relative_path)
    if not root.is_absolute() or relative.is_absolute() or ".." in relative.parts:
        raise ValueError("Invalid stored media path")
    return root / relative


def _remove_tree_without_following_symlinks(root: Path) -> None:
    if not root.exists() or root.is_symlink():
        return
    for current, dirs, files in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        kept_dirs = []
        for name in dirs:
            child = current_path / name
            if child.is_symlink():
                child.unlink()
            else:
                kept_dirs.append(name)
        dirs[:] = kept_dirs
        for name in files:
            child = current_path / name
            if child.is_symlink() or child.is_file():
                child.unlink()
    shutil.rmtree(root, ignore_errors=True)
