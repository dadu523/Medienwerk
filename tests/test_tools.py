import asyncio
import io
import subprocess
from pathlib import Path

import pytest
from fastapi import HTTPException, UploadFile

import config
from server.core.media_store import register_media
from server.core.project_store import project_directory
from server.core.queue import claim_job, create_job, get_job
from server.core.database import init_database
from server.routers import tools


@pytest.fixture(autouse=True)
def initialize_isolated_database():
    init_database()


def _fixture_video(path: Path) -> None:
    subprocess.run([
        "ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=blue:s=64x64:d=0.5",
        "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
        "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(path),
    ], check=True, capture_output=True, timeout=30)


@pytest.mark.parametrize("ratio, expected", [("9:16", (1080, 1920)), ("1:1", (1080, 1080))])
def test_convert_job_registers_real_ffmpeg_output(ratio, expected):
    job_id = create_job("conversion fixture", workflow=f"tools-test-{ratio}")
    job = get_job(job_id)
    project_path = project_directory(job["project_id"])
    source = project_path / "source" / "source.mp4"
    _fixture_video(source)
    register_media(job["project_id"], source, role="source", kind="video")
    assert claim_job(job_id)

    tools.run_convert_job(job_id, job["project_id"], str(source), ratio)

    completed = get_job(job_id)
    assert completed["status"] == "completed", completed["error"]
    details = completed["result_media"][0]["metadata"]
    assert (details["width"], details["height"]) == expected
    assert any(media["role"] == "final" for media in completed["result_media"])


def test_convert_rejects_unsupported_aspect_ratio():
    with pytest.raises(HTTPException) as exc:
        asyncio.run(tools.convert_aspect_ratio(UploadFile(filename="source.mp4", file=io.BytesIO(b"x")), "4:3"))
    assert exc.value.status_code == 400


def test_receive_video_enforces_upload_limit(monkeypatch):
    monkeypatch.setattr(tools, "MAX_UPLOAD_BYTES", 3)
    upload = UploadFile(filename="source.mp4", file=io.BytesIO(b"four"), headers={"content-type": "video/mp4"})

    with pytest.raises(HTTPException) as exc:
        asyncio.run(tools._receive_video(upload))
    assert exc.value.status_code == 413


def test_tts_endpoint_validates_provider_before_creating_job(monkeypatch):
    monkeypatch.setattr(tools, "effective_config", lambda: {"AUDIO_ENGINE": "WaveSpeed AI", "WAVESPEED_API_KEY": ""})

    with pytest.raises(HTTPException) as exc:
        tools.generate_tts(tools.TTSRequest(text="no call", voice="Brian"))
    assert exc.value.status_code == 400


def test_tts_endpoint_queues_job_with_secret_free_snapshot(monkeypatch):
    config_snapshot = {
        "AUDIO_ENGINE": "WaveSpeed AI",
        "WAVESPEED_API_KEY": "fixture-provider-secret",
        "WAVESPEED_AUDIO_MODEL": "example/tts",
    }
    calls = []
    monkeypatch.setattr(tools, "effective_config", lambda: config_snapshot)
    monkeypatch.setattr(tools, "validate_provider_config", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(tools, "submit_to_queue", lambda *args, **kwargs: calls.append(args))

    response = tools.generate_tts(tools.TTSRequest(text="fixture", voice="Brian", idempotency_key="tts-fixture"))
    job = get_job(response["job_id"])

    assert response["status"] == "queued"
    assert len(calls) == 1
    assert "WAVESPEED_API_KEY" not in repr(job["settings"])
    assert "fixture-provider-secret" not in repr(job["settings"])


def test_tools_idempotency_rejects_changed_target_aspect_ratio():
    create_job(
        "conversion", workflow="video_tools.convert",
        settings={"target_aspect_ratio": "16:9"}, idempotency_key="convert-key",
    )

    with pytest.raises(HTTPException) as exc:
        tools._existing_idempotent_job(
            "video_tools.convert", "convert-key",
            expected_settings={"target_aspect_ratio": "9:16"},
        )

    assert exc.value.status_code == 409
