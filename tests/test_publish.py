"""Local publish-catalog and registered-media boundary tests."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from fastapi import HTTPException

from server.core.database import init_database
from server.core.media_store import register_media
from server.core.project_store import create_project, project_directory
from server.routers import publish


@pytest.fixture(autouse=True)
def isolated_catalog():
    init_database()


def _video(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        "ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=160x120:r=24:d=1",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=1", "-shortest",
        "-c:v", "mpeg4", "-c:a", "aac", "-y", str(path),
    ], check=True, timeout=20)
    return path


def test_publish_library_uses_registered_final_media_only(tmp_path):
    project = create_project("Published-ready project", "director")
    root = project_directory(project["id"])
    final = _video(root / "output" / "final_master.mp4")
    source = _video(root / "source" / "source.mp4")
    registered = register_media(project["id"], final, role="final", kind="video")
    register_media(project["id"], source, role="source", kind="video")

    response = publish.get_publishing_library()
    item = next(item for item in response["projects"] if item["media_id"] == registered["id"])
    assert item["id"] == registered["id"]
    assert item["video_path"] == registered["id"]
    assert item["video_url"] == f"/api/projects/media/{registered['id']}/download"
    assert item["seo"]["title"] == "Published-ready project"
    project_rows = [row for row in response["projects"] if row["project_id"] == project["id"]]
    assert len(project_rows) == 1


def test_youtube_publish_rejects_arbitrary_paths_before_oauth_or_network():
    request = publish.PublishRequest(video_path="/etc/passwd", title="test", description="", tags="")
    with pytest.raises(HTTPException) as exc:
        publish.publish_to_youtube(request)
    assert exc.value.status_code == 400
    assert "registered final video" in exc.value.detail
