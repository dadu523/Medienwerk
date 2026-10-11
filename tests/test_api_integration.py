"""Root review checks of the integrated HTTP contracts, with isolated data."""
import io
import wave

from fastapi.testclient import TestClient

from server.main import app
from server.core.media_store import register_media
from server.core.project_store import project_directory


def audio_bytes():
    output = io.BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16000)
        audio.writeframes(b"\0\0" * 16000)
    return output.getvalue()


def test_public_configuration_preserves_and_explicitly_deletes_saved_keys():
    with TestClient(app) as client:
        response = client.post("/api/config", json={"GEMINI_API_KEY": "root-local-test-secret"})
        assert response.status_code == 200
        assert "root-local-test-secret" not in response.text
        response = client.get("/api/config")
        assert response.json()["GEMINI_API_KEY_CONFIGURED"] is True
        assert response.json()["GEMINI_API_KEY"] == ""
        client.post("/api/config", json={"GEMINI_API_KEY": "", "CHANNEL_NAME": "Review"})
        assert client.get("/api/config").json()["GEMINI_API_KEY_CONFIGURED"] is True
        response = client.post("/api/config", json={"delete_secrets": ["GEMINI_API_KEY"]})
        assert response.status_code == 200
        assert client.get("/api/config").json()["GEMINI_API_KEY_CONFIGURED"] is False
        assert client.post("/api/config", json={"VIDEO_ASPECT_RATIO": "bad"}).status_code == 400


def test_catalog_upload_download_history_and_safe_deletion():
    with TestClient(app) as client:
        assert client.get("/api/health").json()["status"] == "ok"
        project = client.post("/api/projects", json={"title": "Root review", "kind": "tools"}).json()
        response = client.post(
            f"/api/projects/{project['id']}/media",
            files={"file": ("../../voice.wav", audio_bytes(), "audio/wav")},
        )
        assert response.status_code == 201
        media = response.json()
        assert ".." not in media["path"]
        url = f"/api/projects/media/{media['id']}/download"
        assert client.get(url).content == audio_bytes()
        source = project_directory(project["id"]) / media["path"]
        register_media(project["id"], source, role="final", kind="audio", origin_key="root-final-audio")
        history = client.get("/api/projects/history").json()
        row = next(item for item in history if item["id"] == project["id"])
        assert len(row["audios"]) == 1
        assert client.get("/api/generate/media", params={"path": "config.json"}).status_code == 404
        assert client.delete(f"/api/projects/{project['id']}").status_code == 200
        assert client.get(url).status_code == 404


def test_mock_social_connections_and_uploads_cannot_report_success():
    with TestClient(app) as client:
        status = client.get("/api/social/status").json()
        assert status["tiktok"] is False and status["instagram"] is False
        assert client.post("/api/social/tiktok/auth").status_code == 501
        assert client.post("/api/social/youtube/callback", json={"code": "fake"}).status_code == 501
        assert client.post("/api/social/publish/youtube", json={"video_path": "fake"}).status_code == 501
