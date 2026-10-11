"""Exercise real SDK serialization with a local HTTPX transport, never Google."""

import base64
import io
import json
import wave
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from PIL import Image

import api_clients


def install_transport(monkeypatch, handler):
    real_client = api_clients.genai.Client
    transports = []

    def factory(**kwargs):
        options = kwargs["http_options"].model_copy(update={
            "client_args": {"transport": httpx.MockTransport(handler)},
        })
        client = real_client(**{**kwargs, "http_options": options})
        transports.append(client._api_client._httpx_client)
        return client

    monkeypatch.setattr(api_clients.genai, "Client", factory)
    return transports


def sdk_response(parts):
    return httpx.Response(200, json={"candidates": [{
        "content": {"role": "model", "parts": parts}, "finishReason": "STOP",
    }]})


def test_parallel_clients_keep_credentials_out_of_urls_and_separate(monkeypatch):
    seen = []

    def handler(request):
        body = json.loads(request.content)
        prompt = body["contents"][0]["parts"][0]["text"]
        seen.append((prompt, request.headers["x-goog-api-key"], str(request.url)))
        return sdk_response([{"text": prompt}])

    transports = install_transport(monkeypatch, handler)
    clients = [api_clients.GoogleClient({"GEMINI_API_KEY": key}) for key in ("fixture-a", "fixture-b")]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda pair: pair[0]._generate_text(pair[1]), zip(clients, ("A", "B"))))
    assert results == ["A", "B"]
    assert {(prompt, key) for prompt, key, _ in seen} == {("A", "fixture-a"), ("B", "fixture-b")}
    assert all("key=" not in url and "fixture-" not in url for _, _, url in seen)
    assert all(client.is_closed for client in transports)


def test_real_sdk_quota_response_is_not_retried_and_transport_closes(monkeypatch):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(429, json={"error": {
            "code": 429, "status": "RESOURCE_EXHAUSTED", "message": "fixture quota exceeded",
        }})

    transports = install_transport(monkeypatch, handler)
    client = api_clients.GoogleClient({"GEMINI_API_KEY": "quota-fixture"})
    with pytest.raises(RuntimeError, match="quota exceeded"):
        client._generate_text("prompt")
    assert len(requests) == 1
    assert all(client.is_closed for client in transports)


def test_sdk_serializes_json_search_image_and_speech_and_decodes_media(monkeypatch, tmp_path):
    image_buffer = io.BytesIO()
    Image.new("RGB", (2, 2), "red").save(image_buffer, format="PNG")
    image_bytes = image_buffer.getvalue()
    pcm = b"\x01\x00\x02\x00\x03\x00\x04\x00"
    requests = []

    def handler(request):
        payload = json.loads(request.content)
        requests.append(payload)
        if api_clients.GEMINI_TTS_MODEL in request.url.path:
            return sdk_response([{"text": "audio follows"}, {"inlineData": {
                "mimeType": "audio/L16;codec=pcm;rate=24000",
                "data": base64.b64encode(pcm).decode(),
            }}])
        if api_clients.NANO_BANANA_IMAGE_MODEL in request.url.path:
            return sdk_response([{"text": "image follows"}, {"inlineData": {
                "mimeType": "image/png", "data": base64.b64encode(image_bytes).decode(),
            }}])
        return sdk_response([{"text": '{"ok":true}'}])

    transports = install_transport(monkeypatch, handler)
    client = api_clients.GoogleClient({"GEMINI_API_KEY": "transport-fixture"})
    assert json.loads(client._generate_text("json", as_json=True)) == {"ok": True}
    assert requests[-1]["generationConfig"]["responseMimeType"] == "application/json"
    client.deep_research("research", "English", api_clients.NewsApiClient(""))
    assert requests[-1]["tools"] == [{"googleSearch": {}}]
    image_path = tmp_path / "image.png"
    client.gemini_nanobanana_image("image", str(image_path))
    assert image_path.read_bytes() == image_bytes
    with Image.open(image_path) as generated:
        assert generated.size == (2, 2)
    single_path = tmp_path / "single.wav"
    client.generate_tts("Hello", str(single_path), {"SPEAKER1": "Kore"})
    assert requests[-1]["generationConfig"]["speechConfig"]["voice_config"]["prebuilt_voice_config"]["voice_name"] == "Kore"
    multi_path = tmp_path / "multi.wav"
    client.generate_tts("Alex: Hello\nMaya: Hi", str(multi_path), {
        "CONTENT_STYLE": "Podcast", "HOST_NAME": "Alex", "GUEST_NAME": "Maya",
        "SPEAKER1": "Kore", "SPEAKER2": "Aoede",
    })
    speakers = requests[-1]["generationConfig"]["speechConfig"]["multi_speaker_voice_config"]["speaker_voice_configs"]
    assert [speaker["speaker"] for speaker in speakers] == ["Alex", "Maya"]
    for path in (single_path, multi_path):
        with wave.open(str(path), "rb") as audio:
            assert (audio.getnchannels(), audio.getsampwidth(), audio.getframerate()) == (1, 2, 24000)
            assert audio.readframes(audio.getnframes()) == pcm
    assert all(client.is_closed for client in transports)
