"""Local contract tests for project-backed workflow adapters."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest
from fastapi import HTTPException

from config import ConfigValidationError
from server.core import queue
from server.core.database import Job, Media, OAuthToken, SessionLocal, utcnow
from server.core import project_store
from server.routers import clipper, director, explainer, social, videofx
from server.core.explainer_engine import _timestamp_seconds


@pytest.fixture(autouse=True)
def isolated_database():
    from server.core.database import init_database
    init_database()


def _selection_job(monkeypatch, tmp_path):
    project = project_store.create_project("Clipper source", "clipper.youtube")
    root = project_store.project_directory(project["id"])
    source = root / "source" / "source.mp4"
    source.write_bytes(b"local fixture, probe is mocked")
    media_id = str(uuid.uuid4())
    with SessionLocal.begin() as db:
        db.add(Media(
            id=media_id, project_id=project["id"], role="source",
            relative_path="source/source.mp4", storage_root=str(root),
            media_type="video/h264", metadata_json='{"duration_seconds":60,"streams":[{"type":"video"},{"type":"audio"}]}',
            origin="native", origin_key=f"test-{media_id}", created_at=utcnow(),
        ))
    job_id = queue.create_job("clipper", project_id=project["id"], workflow="clipper.youtube")
    queue.claim_job(job_id)
    queue.update_job(job_id, status="awaiting_input", result={
        "type": "selection", "video_path": str(source), "source_media_id": media_id,
        "source_duration": 60.0, "clips": [
            {"clip_id": "clip-0", "start": 5.0, "end": 35.0, "title": "segment"},
        ],
    })
    monkeypatch.setattr(clipper, "resolve_media", lambda _media_id: source)
    monkeypatch.setattr(clipper, "probe_media", lambda *args, **kwargs: {
        "media_type": "video/h264",
        "metadata": {"duration_seconds": 60.0, "streams": [{"type": "video"}, {"type": "audio"}]},
    })
    return job_id, source


def test_clipper_rejects_nonfinite_out_of_bounds_and_unknown_segments(monkeypatch, tmp_path):
    job_id, source = _selection_job(monkeypatch, tmp_path)
    cases = [
        {"clip_id": "clip-0", "start": float("nan"), "end": 20},
        {"clip_id": "clip-0", "start": 4, "end": 20},
        {"clip_id": "unknown", "start": 5, "end": 20},
        {"clip_id": "clip-0", "start": 5, "end": 35.1},
    ]
    for selected in cases:
        request = clipper.RenderRequest(job_id=job_id, video_path=str(source), selected_clips=[selected])
        with pytest.raises(HTTPException) as exc:
            clipper._validated_render(request, queue.get_job(job_id))
        assert exc.value.status_code in {400, 409, 422}


def test_clipper_render_submission_is_idempotent_and_conflicting_selection_rejected(monkeypatch, tmp_path):
    job_id, source = _selection_job(monkeypatch, tmp_path)
    monkeypatch.setattr(clipper, "_validated_render", lambda *_args: (
        source, [{"clip_id": "clip-0", "start": 6.0, "end": 30.0, "title": "edit"}], "fingerprint-a"
    ))
    monkeypatch.setattr(clipper, "effective_config", lambda *_args: {"PODCAST_LANGUAGE": "English"}, raising=False)
    submitted = []
    monkeypatch.setattr(clipper, "submit_awaiting_input_to_queue", lambda *args, **kwargs: submitted.append(args) or object())
    req = clipper.RenderRequest(job_id=job_id, video_path=str(source), selected_clips=[{"clip_id": "clip-0", "start": 6, "end": 30}])

    first = clipper.start_render(req)
    second = clipper.start_render(req)
    assert first["job_id"] == second["job_id"] == job_id
    assert len(submitted) == 1

    monkeypatch.setattr(clipper, "_validated_render", lambda *_args: (
        source, [{"clip_id": "clip-0", "start": 7.0, "end": 30.0}], "fingerprint-b"
    ))
    with pytest.raises(HTTPException) as exc:
        clipper.start_render(req)
    assert exc.value.status_code == 409


def test_clipper_provider_failure_becomes_failed_job(monkeypatch):
    job_id = queue.create_job("analysis failure", workflow="clipper.youtube")
    monkeypatch.setattr(clipper, "effective_config", lambda: {"TEXT_ENGINE": "Gemini API"})
    monkeypatch.setattr(clipper, "validate_provider_config", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(clipper, "analyze_video", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("provider unavailable")))

    clipper.run_analyze_task(job_id, "https://youtu.be/example", False, 2, {"TEXT_ENGINE": "Gemini API"})

    assert queue.get_job(job_id)["status"] == "failed"
    assert "provider unavailable" in queue.get_job(job_id)["error"]


@pytest.mark.parametrize("validator", [clipper._valid_youtube_url, director._validate_url])
def test_youtube_adapters_reject_host_suffix_and_query_hacks(validator):
    for url in (
        "https://youtube.com.evil.example/watch?v=1",
        "https://evil.youtube.com.example/watch?v=1",
        "https://example.test/?next=youtube.com/watch?v=1",
    ):
        with pytest.raises(ConfigValidationError):
            validator(url)


def test_director_uses_frozen_config_and_provider_failure_is_terminal(monkeypatch):
    monkeypatch.setattr(director, "effective_config", lambda: {"PODCAST_LANGUAGE": "German", "GEMINI_API_KEY": "test-key"})
    submitted = []
    monkeypatch.setattr(director, "submit_to_queue", lambda *args: submitted.append(args) or object())
    request = director.DirectorRequest(url="https://youtu.be/example", idempotency_key="director-1")
    first = director.start_director(request)
    second = director.start_director(request)
    assert first["job_id"] == second["job_id"]
    assert len(submitted) == 2  # queue CAS is the single execution gate
    snapshot = submitted[0][3]
    assert snapshot["PODCAST_LANGUAGE"] == "German"

    job_id = queue.create_job("director failing", workflow="director")
    monkeypatch.setattr(director, "run_director_pipeline", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("download failed")))
    director.run_director_task(job_id, director.DirectorRequest(url="https://youtu.be/example"), {}, queue.get_job(job_id)["project_id"])
    assert queue.get_job(job_id)["status"] == "failed"


def test_explainer_applies_requested_language_voice_and_frozen_config(monkeypatch):
    config_snapshot = {"GEMINI_API_KEY": "test-key", "TEXT_ENGINE": "Gemini API", "AUDIO_ENGINE": "Gemini API", "PODCAST_LANGUAGE": "English"}
    monkeypatch.setattr(explainer, "effective_config", lambda: dict(config_snapshot))
    monkeypatch.setattr(explainer, "validate_provider_config", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(explainer, "submit_to_queue", lambda *_args, **_kwargs: object())
    captured = {}

    class FakeEngine:
        def __init__(self, **kwargs):
            captured.update(kwargs)
        def process(self):
            raise RuntimeError("provider unavailable")

    monkeypatch.setattr(explainer, "ExplainerEngine", FakeEngine)
    request = explainer.ExplainerRequest(
        url="https://youtu.be/movie", language="German", voice="Puck", text_engine="Gemini API",
        audio_engine="Gemini API", idempotency_key="explainer-1",
    )
    accepted = explainer.start_explainer(request)
    job = queue.get_job(accepted["job_id"])
    explainer.run_explainer_task(job["id"], request, config_snapshot, job["project_id"])

    assert captured["language"] == "German"
    assert captured["voice"] == "Puck"
    assert captured["config"]["TEXT_ENGINE"] == "Gemini API"
    assert captured["output_dir"].endswith(job["id"])
    assert queue.get_job(job["id"])["status"] == "failed"


def test_explainer_timestamps_are_parsed_as_finite_video_times():
    assert _timestamp_seconds("00:02:03") == 123
    assert _timestamp_seconds("02:03") == 123
    with pytest.raises(ValueError):
        _timestamp_seconds("00:01:02:03")


def test_videofx_registers_silent_video_result_and_uses_project_output(monkeypatch, tmp_path):
    job_id = queue.create_job("videofx", workflow="videofx")
    output_paths = []

    class FakeClient:
        def __init__(self, _profile):
            pass
        def generate_video(self, prompt, output, **kwargs):
            output_paths.append(Path(output))
            Path(output).write_bytes(b"video")

    monkeypatch.setattr(videofx, "VideoFXClient", FakeClient)
    monkeypatch.setattr(videofx, "probe_media", lambda *_args, **_kwargs: {
        "media_type": "video/h264", "metadata": {"streams": [{"type": "video"}], "duration_seconds": 1.0},
    })
    registered = []
    from server.core import media_store
    monkeypatch.setattr(media_store, "register_media", lambda project, path, **kwargs: {
        "id": "video-fx-media", "project_id": project, "path": "output/videofx.mp4",
        "media_type": "video/h264", "origin": "native",
    })
    monkeypatch.setattr(videofx, "complete_job", queue.complete_job)
    original_register = media_store.register_media
    def capture_register(project, path, **kwargs):
        registered.append(kwargs)
        return original_register(project, path, **kwargs)
    monkeypatch.setattr(media_store, "register_media", capture_register)

    videofx.run_videofx_task(job_id, videofx.VideoFXRequest(prompt="a quiet scene"))

    assert output_paths[0].parent.name == "output"
    assert queue.get_job(job_id)["status"] == "completed"
    assert registered[0]["require_audio"] is False


def test_videofx_login_reports_browser_open_without_claiming_authentication(monkeypatch):
    from server.routers import videofx

    class LoginClient:
        def __init__(self, _profile):
            pass
        def login_if_needed(self):
            return None

    monkeypatch.setattr(videofx, "VideoFXClient", LoginClient)
    result = videofx.start_login()
    assert result["status"] == "browser_opened"
    assert result["authenticated"] is False


def test_legacy_oauth_rows_do_not_report_connected_and_mock_callbacks_are_disabled():
    with SessionLocal.begin() as db:
        db.add(OAuthToken(platform="youtube", access_token="mock_access_code", refresh_token="mock_refresh_code"))
    assert social.get_social_status()["youtube"] is False
    assert social.get_social_status()["tiktok"] is False
    with pytest.raises(HTTPException) as exc:
        social.youtube_callback()
    assert exc.value.status_code == 501
