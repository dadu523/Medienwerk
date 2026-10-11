from pathlib import Path

import pytest
from fastapi import HTTPException

import config
import pipeline
from server.core.media_store import register_media
from server.core.project_store import create_project, project_directory
from server.core.queue import claim_job, create_job, get_job, get_job_status, update_job
from server.core.database import init_database
from server.routers import generation


@pytest.fixture(autouse=True)
def initialize_isolated_database():
    init_database()


def _valid_config(**overrides):
    return {
        "GEMINI_API_KEY": "fixture-gemini-key",
        "WAVESPEED_API_KEY": "fixture-wavespeed-key",
        "TEXT_ENGINE": "Gemini API",
        "AUDIO_ENGINE": "Gemini API",
        "VIDEO_ENGINE": "WaveSpeed AI",
        "IMAGE_ENGINE": "Gemini API",
        **overrides,
    }


def test_quick_start_freezes_effective_config_and_sanitizes_job_settings(monkeypatch):
    calls = []
    snapshot = _valid_config()
    monkeypatch.setattr(generation, "effective_config", lambda overrides=None: {**snapshot, **(overrides or {})})
    monkeypatch.setattr(generation, "validate_provider_config", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(generation, "submit_to_queue", lambda *args, **kwargs: calls.append((args, kwargs)))

    response = generation.start_quick_generation(generation.GenerationRequest(topic="A new topic", idempotency_key="quick-1"))
    job = get_job(response["job_id"])

    assert response["status"] == "queued"
    assert len(calls) == 1
    # Queue arguments are (task, job_id, request, frozen_config, project_id).
    assert calls[0][0][3]["GEMINI_API_KEY"] == "fixture-gemini-key"
    assert "GEMINI_API_KEY" not in job["settings"]
    assert job["project_id"] == response["project_id"]


def test_config_snapshot_does_not_change_after_settings_are_edited(monkeypatch):
    saved_config = _valid_config(VISUAL_STYLE="Documentary")
    calls = []
    monkeypatch.setattr(generation, "effective_config", lambda overrides=None: {**saved_config, **(overrides or {})})
    monkeypatch.setattr(generation, "validate_provider_config", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(generation, "submit_to_queue", lambda *args, **kwargs: calls.append(args))

    generation.start_quick_generation(generation.GenerationRequest(topic="Frozen settings"))
    saved_config["GEMINI_API_KEY"] = "later-key"
    saved_config["VISUAL_STYLE"] = "Later style"

    frozen = calls[0][3]
    assert frozen["GEMINI_API_KEY"] == "fixture-gemini-key"
    assert frozen["VISUAL_STYLE"] == "Cinematic Documentary"


def test_quick_idempotency_returns_existing_job_without_resubmitting(monkeypatch):
    calls = []
    monkeypatch.setattr(generation, "effective_config", lambda overrides=None: _valid_config(**(overrides or {})))
    monkeypatch.setattr(generation, "validate_provider_config", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(generation, "submit_to_queue", lambda *args, **kwargs: calls.append(args))

    first = generation.start_quick_generation(generation.GenerationRequest(topic="first", idempotency_key="same-key"))
    second = generation.start_quick_generation(generation.GenerationRequest(topic="first", idempotency_key="same-key"))

    assert first["job_id"] == second["job_id"]
    assert len(calls) == 1
    assert get_job(first["job_id"])["topic"] == "first"


@pytest.mark.parametrize("changed", [
    {"topic": "different topic"},
    {"style": "Different style"},
])
def test_quick_idempotency_rejects_a_changed_request(changed, monkeypatch):
    monkeypatch.setattr(generation, "effective_config", lambda overrides=None: _valid_config(**(overrides or {})))
    monkeypatch.setattr(generation, "validate_provider_config", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(generation, "submit_to_queue", lambda *_args, **_kwargs: None)
    key = f"changed-request-{changed.get('topic', changed.get('style'))}"
    generation.start_quick_generation(generation.GenerationRequest(topic="same topic", idempotency_key=key))

    with pytest.raises(generation.IdempotencyConflictError):
        generation.start_quick_generation(generation.GenerationRequest(
            topic=changed.get("topic", "same topic"),
            style=changed.get("style", "Cinematic Documentary"),
            idempotency_key=key,
        ))


def test_quick_idempotency_conflict_maps_to_http_409(monkeypatch):
    monkeypatch.setattr(generation, "effective_config", lambda overrides=None: _valid_config(**(overrides or {})))
    monkeypatch.setattr(generation, "validate_provider_config", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(generation, "submit_to_queue", lambda *_args, **_kwargs: None)
    generation.start_quick_generation(generation.GenerationRequest(topic="first", idempotency_key="http-key"))

    with pytest.raises(HTTPException) as exc:
        generation.start_quick_generation_route(generation.GenerationRequest(topic="changed", idempotency_key="http-key"))
    assert exc.value.status_code == 409


def test_legacy_idempotency_replay_requires_matching_saved_request_options(monkeypatch):
    req = generation.GenerationRequest(topic="legacy exact", idempotency_key="legacy-key")
    monkeypatch.setattr(generation, "effective_config", lambda overrides=None: _valid_config(**(overrides or {})))
    saved_settings = config.sanitize_config(generation._request_config(req))
    old_job_id = create_job(
        "legacy exact", workflow="quick_creator", settings=saved_settings,
        idempotency_key="legacy-key",
    )

    replay = generation.start_quick_generation(req)
    assert replay["job_id"] == old_job_id
    with pytest.raises(generation.IdempotencyConflictError, match="older job"):
        generation.start_quick_generation(generation.GenerationRequest(
            topic="legacy exact", style="Changed legacy option", idempotency_key="legacy-key",
        ))


def test_quick_rejects_unimplemented_omnichannel_before_job_creation(monkeypatch):
    monkeypatch.setattr(generation, "effective_config", lambda overrides=None: _valid_config(**(overrides or {})))
    with pytest.raises(config.ConfigValidationError, match="Omnichannel"):
        generation.start_quick_generation(generation.GenerationRequest(topic="No external run", omnichannel=True))


def test_quick_retry_reuses_only_inactive_quick_creator_project(monkeypatch):
    calls = []
    monkeypatch.setattr(generation, "effective_config", lambda overrides=None: _valid_config(**(overrides or {})))
    monkeypatch.setattr(generation, "validate_provider_config", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(generation, "submit_to_queue", lambda *args, **kwargs: calls.append(args))
    project = create_project("Retryable", "quick_creator")

    first = generation.start_quick_generation(generation.GenerationRequest(topic="First", project_id=project["id"]))
    with pytest.raises(config.ConfigValidationError, match="active job"):
        generation.start_quick_generation(generation.GenerationRequest(topic="Blocked", project_id=project["id"]))
    update_job(first["job_id"], status="failed", error="fixture terminal state")
    second = generation.start_quick_generation(generation.GenerationRequest(topic="Retry", project_id=project["id"]))

    assert first["project_id"] == second["project_id"] == project["id"]
    assert first["job_id"] != second["job_id"]
    assert len(calls) == 2
    assert calls[0][1] != calls[1][1]


def test_quick_retry_rejects_other_workflow_projects(monkeypatch):
    monkeypatch.setattr(generation, "effective_config", lambda overrides=None: _valid_config(**(overrides or {})))
    monkeypatch.setattr(generation, "validate_provider_config", lambda *_args, **_kwargs: None)
    project = create_project("Wrong workflow", "video_tools.convert")

    with pytest.raises(config.ConfigValidationError, match="Quick Creator"):
        generation.start_quick_generation(generation.GenerationRequest(topic="Retry", project_id=project["id"]))


def _install_fake_pipeline_providers(monkeypatch):
    import struct
    import subprocess
    import wave

    class FakeGoogleClient:
        def __init__(self, _config):
            pass

        def deep_research(self, *_args):
            return "Controlled fixture research."

        def generate_podcast_script(self, *_args):
            return "A short controlled narration for the pipeline fixture."

        def generate_tts(self, _text, output_path, _config):
            with wave.open(output_path, "wb") as audio:
                audio.setnchannels(1)
                audio.setsampwidth(2)
                audio.setframerate(16000)
                audio.writeframes(struct.pack("<h", 0) * 16000)

        def generate_video_prompt(self, *_args):
            return "A simple blue background."

    class FakeWaveSpeedClient:
        def __init__(self, *_args, **_kwargs):
            pass

        def text_to_video(self, _model, _prompt, output_path, _aspect):
            subprocess.run([
                "ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=blue:s=64x64:r=24:d=1",
                "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", output_path,
            ], check=True, capture_output=True, timeout=30)

    monkeypatch.setattr(pipeline, "GoogleClient", FakeGoogleClient)
    monkeypatch.setattr(pipeline, "WaveSpeedClient", FakeWaveSpeedClient)
    monkeypatch.setattr(pipeline, "NewsApiClient", lambda *_args: object())
    monkeypatch.setattr(pipeline, "PixabayClient", lambda *_args: object())
    monkeypatch.setattr(pipeline, "generate_captions", lambda *_args, **_kwargs: [{"word": "fixture", "start": 0.0, "end": 0.5}])


def _run_controlled_pipeline_job(tmp_path, config_snapshot):
    project = create_project("Controlled pipeline", "quick_creator")
    job_id = create_job("Controlled pipeline", project_id=project["id"], workflow="quick_creator")
    assert claim_job(job_id)
    req = generation.GenerationRequest(
        topic="Fixture topic",
        auto_captions=config_snapshot.get("CAPTION_ENABLED", True),
        bg_music=config_snapshot.get("ADD_MUSIC", True),
    )
    generation.run_pipeline_task(job_id, req, config_snapshot, project["id"])
    return job_id, project["id"], get_job(job_id)


def test_real_pipeline_muxes_and_registers_controlled_provider_media(tmp_path, monkeypatch):
    import shutil
    from server.core.media_store import resolve_media
    from server.core.database import Media, SessionLocal

    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("FFmpeg and ffprobe are required for this integration check")
    _install_fake_pipeline_providers(monkeypatch)
    config_snapshot = _valid_config(
        API_DELAY=0,
        PODCAST_LANGUAGE="English",
        FACT_CHECK_ENABLED=False,
        GENERATE_THUMBNAIL=False,
        GENERATE_TIMED_IMAGES=False,
        TIMED_IMAGES_AS_SLIDESHOW=False,
        CAPTION_ENABLED=False,
        GENERATE_TIMESTAMPS=False,
        GENERATE_SNIPPETS=False,
        ADD_MUSIC=True,
        BACKGROUND_MUSIC_PATH=str(tmp_path / "missing-music.mp3"),
        BG_MODE="AI Video",
        VIDEO_ASPECT_RATIO="16:9",
        VIDEO_CLIP_COUNT=1,
    )

    job_id, project_id, job = _run_controlled_pipeline_job(tmp_path, config_snapshot)

    assert job["status"] == "completed"
    assert any("music asset is missing" in warning for warning in job["result"]["warnings"])
    with SessionLocal() as db:
        final_media = db.query(Media).filter(Media.project_id == project_id, Media.role == "final").one()
    final_path = resolve_media(final_media.id)
    assert final_path.name == "final_video.mp4"
    assert final_path.parent.name == job_id


def test_enabled_captions_without_a_valid_ass_file_fail_the_job(tmp_path, monkeypatch):
    import shutil

    if not shutil.which("ffmpeg"):
        pytest.skip("FFmpeg is required for this integration check")
    _install_fake_pipeline_providers(monkeypatch)
    monkeypatch.setattr(pipeline, "generate_captions", lambda *_args, **_kwargs: [])
    config_snapshot = _valid_config(
        API_DELAY=0,
        PODCAST_LANGUAGE="English",
        FACT_CHECK_ENABLED=False,
        GENERATE_THUMBNAIL=False,
        GENERATE_TIMED_IMAGES=False,
        TIMED_IMAGES_AS_SLIDESHOW=False,
        CAPTION_ENABLED=True,
        GENERATE_TIMESTAMPS=False,
        GENERATE_SNIPPETS=False,
        ADD_MUSIC=False,
        BG_MODE="AI Video",
        VIDEO_ASPECT_RATIO="16:9",
        VIDEO_CLIP_COUNT=1,
    )

    _, _, job = _run_controlled_pipeline_job(tmp_path, config_snapshot)

    assert job["status"] == "failed"
    assert "no usable subtitle file" in job["error"]


def test_media_route_rejects_unregistered_paths():
    with pytest.raises(Exception) as exc:
        generation.serve_media_file("/etc/passwd")
    assert getattr(exc.value, "status_code", None) == 404


def test_cancel_route_confirms_awaiting_input_jobs():
    job_id = create_job("awaiting cancellation", workflow="quick_creator")
    update_job(job_id, status="awaiting_input")

    response = generation.cancel_job(job_id)

    assert get_job_status(job_id) == "cancelled"
    assert "Cancellation requested" in response["message"]


def test_media_route_serves_only_registered_media(tmp_path):
    pytest.importorskip("shutil")
    import subprocess
    from server.core.database import SessionLocal, Media

    project = create_project("test media", "fixture")
    output = project_directory(project["id"]) / "output" / "fixture.mp4"
    subprocess.run([
        "ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=blue:s=64x64:d=0.5",
        "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
        "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(output),
    ], check=True, capture_output=True, timeout=30)
    media = register_media(project["id"], output, role="final", kind="video")

    response = generation.serve_media_file(media["id"])
    assert Path(response.path) == output
    with pytest.raises(Exception) as exc:
        generation.serve_media_file(str(output.parent / "missing.mp4"))
    assert getattr(exc.value, "status_code", None) == 404
