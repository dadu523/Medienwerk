"""Registered media storage with path-boundary checks and media probing."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import uuid
from pathlib import Path
from typing import Any

from server.core.database import Job, Media, Project, SessionLocal, utcnow
from server.core.project_store import project_directory


class MediaValidationError(ValueError):
    pass


def _assert_no_symlink(root: Path, candidate: Path) -> None:
    if root.is_symlink():
        raise MediaValidationError("Storage root cannot be a symlink")
    root_real = root.resolve(strict=True)
    if root_real != root.absolute():
        raise MediaValidationError("Registered storage root changed through a symlink")
    if not candidate.is_absolute() or not candidate.is_relative_to(root):
        raise MediaValidationError("Media path is outside its registered storage root")
    current = root
    relative = candidate.relative_to(root)
    for segment in relative.parts:
        current = current / segment
        if current.is_symlink():
            raise MediaValidationError("Symlinks are not allowed in registered media paths")
    resolved = candidate.resolve(strict=True)
    if not resolved.is_relative_to(root_real):
        raise MediaValidationError("Media path escaped its registered storage root")
    if not resolved.is_file():
        raise MediaValidationError("Media path is not a regular file")


def probe_media(path: Path, *, expected_kind: str | None = None, require_audio_for_video: bool = False) -> dict[str, Any]:
    """Read the file with ffprobe and require a valid audio or video stream."""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
            check=False, capture_output=True, text=True, timeout=30,
        )
    except FileNotFoundError as exc:
        raise MediaValidationError("ffprobe is required to register audio or video") from exc
    except subprocess.TimeoutExpired as exc:
        raise MediaValidationError("Media probe timed out") from exc
    if result.returncode != 0:
        raise MediaValidationError("File could not be read as valid audio or video")
    try:
        probe = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise MediaValidationError("ffprobe returned invalid media metadata") from exc
    streams = probe.get("streams") or []
    media_streams = [stream for stream in streams if stream.get("codec_type") in {"audio", "video"}]
    if not media_streams:
        raise MediaValidationError("File has no readable audio or video streams")
    format_info = probe.get("format") or {}
    raw_duration = format_info.get("duration")
    if raw_duration is None:
        durations = [stream.get("duration") for stream in media_streams if stream.get("duration")]
        raw_duration = max(durations, default=None)
    try:
        duration = float(raw_duration) if raw_duration is not None else 0.0
    except (TypeError, ValueError):
        duration = 0.0
    if duration <= 0:
        raise MediaValidationError("Media stream has no valid positive duration")
    video_stream = next((s for s in media_streams if s.get("codec_type") == "video"), None)
    audio_streams = [s for s in media_streams if s.get("codec_type") == "audio"]
    kind = "video" if video_stream else "audio"
    if expected_kind and kind != expected_kind:
        raise MediaValidationError(f"Expected {expected_kind} media but found {kind}")
    if require_audio_for_video and kind == "video" and not audio_streams:
        raise MediaValidationError("Final video must contain readable video and audio streams")
    metadata: dict[str, Any] = {
        "duration_seconds": duration,
        "format_name": format_info.get("format_name"),
        "size_bytes": path.stat().st_size,
        "streams": [{"type": s.get("codec_type"), "codec": (s.get("codec_name"))} for s in media_streams],
    }
    if video_stream:
        width, height = video_stream.get("width"), video_stream.get("height")
        if not isinstance(width, int) or not isinstance(height, int) or width <= 0 or height <= 0:
            raise MediaValidationError("Video stream has invalid dimensions")
        metadata.update({"width": width, "height": height, "video_codec": video_stream.get("codec_name")})
    if audio_streams:
        metadata.update({
            "audio_codec": audio_streams[0].get("codec_name"),
            "sample_rate": audio_streams[0].get("sample_rate"),
            "channels": audio_streams[0].get("channels"),
        })
    return {"media_type": f"{kind}/{(video_stream or audio_streams[0]).get('codec_name') or 'unknown'}", "metadata": metadata}


def _origin_key(root: Path, relative: Path) -> str:
    # Source location is the stable idempotency key for imports. File metadata
    # can change without causing duplicate rows on every repeat import.
    raw = f"{root}|{relative.as_posix()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def register_media(
    project_id: str,
    path: str | os.PathLike[str],
    role: str = "final",
    kind: str | None = None,
    *,
    origin: str = "native",
    origin_key: str | None = None,
    import_root: str | os.PathLike[str] | None = None,
    require_audio: bool | None = None,
    session=None,
) -> dict[str, Any]:
    """Probe and register a file owned by the project or an explicitly selected import root.

    ``import_root`` is intended for preview/apply legacy imports. It is persisted
    so a registered file can be resolved after a restart. Imported files never
    become owned by the project and are not deleted by normal project cleanup.
    """
    project_id = str(uuid.UUID(str(project_id)))
    source_path = Path(path).expanduser()
    if not source_path.is_absolute():
        source_path = Path.cwd() / source_path
    source_path = source_path.absolute()
    if import_root is None:
        with SessionLocal() as db:
            if db.get(Project, project_id) is None:
                raise ValueError("Project not found")
        storage_root = project_directory(project_id, create=True)
        origin = "native"
    else:
        storage_root = Path(import_root).expanduser()
        if not storage_root.is_absolute():
            storage_root = Path.cwd() / storage_root
        if storage_root.is_symlink() or not storage_root.is_dir():
            raise MediaValidationError("Selected import root must be an existing real directory")
        storage_root = storage_root.resolve(strict=True)
        origin = "imported"
    try:
        relative = source_path.relative_to(storage_root)
    except ValueError as exc:
        raise MediaValidationError("Media file is outside the project or selected import root") from exc
    _assert_no_symlink(storage_root, source_path)
    detected_kind = kind
    if detected_kind is None:
        # Probe first to select the actual audio/video category.
        details = probe_media(source_path)
        detected_kind = details["media_type"].split("/", 1)[0]
        if role == "final" and detected_kind == "video" and require_audio is not False and not any(
            stream.get("type") == "audio" for stream in details["metadata"].get("streams", [])
        ):
            raise MediaValidationError("Final video must contain readable video and audio streams")
    else:
        details = probe_media(
            source_path, expected_kind=detected_kind,
            require_audio_for_video=(role == "final" and detected_kind == "video" and require_audio is not False),
        )
    origin_key = origin_key or _origin_key(storage_root, relative)

    def persist(db):
        project = db.get(Project, project_id)
        if project is None:
            raise ValueError("Project not found")
        existing = db.query(Media).filter(Media.origin == origin, Media.origin_key == origin_key).first()
        if existing:
            # Keep identity stable by origin while refreshing properties for a
            # changed file at the same imported path.
            existing.media_type = details["media_type"]
            existing.metadata_json = json.dumps(details["metadata"], separators=(",", ":"))
            return _media_dict(existing)
        item = Media(
            id=str(uuid.uuid4()), project_id=project_id, role=role,
            relative_path=relative.as_posix(), storage_root=str(storage_root),
            media_type=details["media_type"],
            metadata_json=json.dumps(details["metadata"], separators=(",", ":")),
            origin=origin, origin_key=origin_key, created_at=utcnow(),
        )
        db.add(item)
        db.flush()
        return _media_dict(item)

    if session is not None:
        return persist(session)
    with SessionLocal.begin() as db:
        return persist(db)


def _media_dict(item: Media) -> dict[str, Any]:
    try:
        metadata = json.loads(item.metadata_json or "{}")
    except json.JSONDecodeError:
        metadata = {}
    return {
        "id": item.id, "project_id": item.project_id, "role": item.role,
        "path": item.relative_path, "relative_path": item.relative_path,
        "url": f"/api/projects/media/{item.id}/download",
        "media_type": item.media_type, "metadata": metadata,
        "origin": item.origin, "created_at": item.created_at.isoformat() if item.created_at else None,
    }


def get_media(media_id: str) -> dict[str, Any] | None:
    with SessionLocal() as db:
        item = db.get(Media, str(media_id))
        return _media_dict(item) if item else None


def resolve_media(media_id: str) -> Path:
    """Resolve only registered IDs, checking every path component for symlinks."""
    with SessionLocal() as db:
        item = db.get(Media, str(media_id))
        if item is None:
            raise FileNotFoundError("Registered media not found")
        root = Path(item.storage_root)
        relative = Path(item.relative_path)
    if not root.is_absolute() or relative.is_absolute() or ".." in relative.parts:
        raise MediaValidationError("Invalid registered media path")
    candidate = root / relative
    _assert_no_symlink(root, candidate)
    return candidate


def list_media(project_id: str) -> list[dict[str, Any]]:
    with SessionLocal() as db:
        items = db.query(Media).filter(Media.project_id == str(project_id)).order_by(Media.created_at.desc()).all()
        return [_media_dict(item) for item in items]


def unregister_media(media_id: str, *, project_id: str | None = None, delete_file: bool = False) -> bool:
    """Unregister media; only native project files can be explicitly removed."""
    with SessionLocal() as db:
        query = db.query(Media).filter(Media.id == str(media_id))
        if project_id is not None:
            query = query.filter(Media.project_id == str(project_id))
        item = query.first()
        if item is None:
            return False
        active_job = db.query(Project.id).join(Project.jobs).filter(
            Project.id == item.project_id,
            Job.status.in_(
                ("queued", "running", "awaiting_input", "cancel_requested")
            ),
        ).first()
        if active_job:
            raise ValueError("Project has an active job and its media cannot be removed")
        path_to_delete = None
        if delete_file and item.origin == "native":
            root = project_directory(item.project_id, create=False)
            candidate = resolve_media(item.id)
            if candidate.is_relative_to(root):
                path_to_delete = candidate
        db.delete(item)
        db.commit()
    if path_to_delete and path_to_delete.exists():
        path_to_delete.unlink()
    return True


def import_candidates(root: str | os.PathLike[str]) -> list[dict[str, str]]:
    """List known final outputs at the selected root and one folder level below."""
    selected = Path(root).expanduser()
    if not selected.is_absolute():
        selected = Path.cwd() / selected
    if selected.is_symlink() or not selected.is_dir():
        raise MediaValidationError("Selected import root must be an existing real directory")
    selected = selected.resolve(strict=True)
    known = {
        "final_podcast.mp4", "final_podcast_video.mp4", "final_explainer.mp4",
        "final_master.mp4", "magic_master.mp4", "final_video.mp4", "final_output.mp4",
    }
    found: list[Path] = []
    parents = [selected]
    parents.extend(
        p for p in sorted(selected.iterdir())
        if p.is_dir() and not p.is_symlink() and p.name not in {"projects", "node_modules", ".git"}
    )
    for parent in parents:
        for candidate in sorted(parent.iterdir()):
            if candidate.is_symlink() or not candidate.is_file():
                continue
            if candidate.name.lower() in known or (candidate.name.startswith("Final_") and candidate.suffix.lower() == ".mp4"):
                found.append(candidate)
    results = []
    for candidate in found:
        rel = candidate.relative_to(selected)
        key = _origin_key(selected, rel)
        results.append({
            "path": str(candidate), "relative_path": rel.as_posix(),
            "title": candidate.parent.name if candidate.parent != selected else selected.name,
            "kind": _legacy_kind(candidate.name), "origin_key": key,
        })
    return results


def _legacy_kind(filename: str) -> str:
    name = filename.lower()
    if "explainer" in name:
        return "explainer"
    if name in {"final_master.mp4", "magic_master.mp4"}:
        return "director"
    if name.startswith("final_") and name.endswith(".mp4") and name not in {
        "final_podcast.mp4", "final_podcast_video.mp4", "final_video.mp4", "final_output.mp4"
    }:
        return "clipper"
    if name in {"final_podcast.mp4", "final_podcast_video.mp4"}:
        return "quick_creator"
    return "legacy"


def preview_legacy_import(roots: list[str | os.PathLike[str]]) -> dict[str, Any]:
    candidates = []
    for root in roots:
        for candidate in import_candidates(root):
            existing = None
            with SessionLocal() as db:
                existing = db.query(Media).filter(
                    Media.origin == "imported", Media.origin_key == candidate["origin_key"]
                ).first()
            candidate["already_registered"] = existing is not None
            if existing:
                candidate["media_id"] = existing.id
                candidate["project_id"] = existing.project_id
            candidate["selected_root"] = str(Path(root).expanduser().resolve())
            candidates.append(candidate)
    return {"count": len(candidates), "already_registered": sum(c["already_registered"] for c in candidates), "items": candidates}


def apply_legacy_import(roots: list[str | os.PathLike[str]]) -> dict[str, Any]:
    preview = preview_legacy_import(roots)
    imported, skipped, errors = [], [], []
    for candidate in preview["items"]:
        if candidate["already_registered"]:
            skipped.append(candidate)
            continue
        try:
            project = None
            # Existing registration wins, avoiding duplicate project records on reruns.
            with SessionLocal() as db:
                prior = db.query(Media).filter(
                    Media.origin == "imported", Media.origin_key == candidate["origin_key"]
                ).first()
                if prior:
                    skipped.append({**candidate, "media_id": prior.id, "project_id": prior.project_id})
                    continue
            project = _find_or_create_import_project(candidate["selected_root"], candidate["relative_path"], candidate["title"], candidate["kind"])
            media = register_media(
                project["id"], candidate["path"], role="final", kind="video",
                origin="imported", origin_key=candidate["origin_key"], import_root=candidate["selected_root"],
            )
            imported.append({**candidate, "media_id": media["id"], "project_id": project["id"]})
        except Exception as exc:
            errors.append({"path": candidate["path"], "error": str(exc)})
    return {"imported": imported, "skipped": skipped, "errors": errors}


def _find_or_create_import_project(root: str, relative_path: str, title: str, kind: str) -> dict[str, Any]:
    """Reuse a generated project for a legacy folder based on a deterministic media origin scope."""
    # Existing project association is the authoritative idempotency record.
    with SessionLocal() as db:
        existing = db.query(Media).filter(
            Media.origin == "imported", Media.storage_root == root,
            Media.relative_path == Path(relative_path).as_posix(),
        ).first()
        if existing:
            project = db.get(Project, existing.project_id)
            if project:
                return {"id": project.id, "title": project.title, "kind": project.kind}
        folder = Path(relative_path).parent.as_posix()
        scope = {"root": root, "relative_folder": folder}
        for project in db.query(Project).all():
            try:
                config = json.loads(project.config_json or "{}")
            except json.JSONDecodeError:
                continue
            if config.get("legacy_import_scope") == scope:
                return {"id": project.id, "title": project.title, "kind": project.kind}
    from server.core.project_store import create_project
    label = title.strip() or Path(relative_path).stem
    scope = {"root": root, "relative_folder": Path(relative_path).parent.as_posix()}
    return create_project(f"{label} (imported)", kind, {"legacy_import_scope": scope})


def reconcile_project_outputs(project_id: str, *, role: str = "final") -> list[dict[str, Any]]:
    """Register known final outputs already written inside a project's output folder."""
    project = project_directory(project_id, create=False)
    output = project / "output"
    if output.is_symlink() or not output.is_dir():
        return []
    known_video = {
        "final_podcast.mp4", "final_podcast_video.mp4", "final_explainer.mp4",
        "final_master.mp4", "magic_master.mp4", "final_video.mp4", "final_output.mp4",
    }
    known_audio = {"final_audio.mp3", "final_tts.mp3", "voiceover.mp3"}
    registered = []
    for path in sorted(output.iterdir()):
        if path.is_symlink() or not path.is_file():
            continue
        name = path.name.lower()
        is_clip = path.name.startswith("Final_") and path.suffix.lower() == ".mp4"
        if name not in known_video and name not in known_audio and not is_clip:
            continue
        expected_kind = "audio" if name in known_audio else "video"
        try:
            registered.append(register_media(project_id, path, role=role, kind=expected_kind))
        except (MediaValidationError, ValueError):
            continue
    return registered
