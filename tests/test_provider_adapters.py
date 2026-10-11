import pytest

from config import ConfigValidationError, validate_provider_config
from server.core import provider_adapters


def test_wave_speed_text_to_speech_adapter_uses_existing_method(monkeypatch):
    import api_clients

    called = {}

    def text_to_speech(self, model_id, text, output_path, voice="Brian"):
        called.update(model_id=model_id, text=text, output_path=output_path, voice=voice)

    monkeypatch.setattr(api_clients.WaveSpeedClient, "text_to_speech", text_to_speech)
    result = provider_adapters.synthesize_speech({
        "AUDIO_ENGINE": "WaveSpeed AI",
        "WAVESPEED_API_KEY": "local-test-key",
        "WAVESPEED_AUDIO_MODEL": "example/model",
    }, "hello", "/tmp/voice.mp3", voice="Kore")

    assert result == "/tmp/voice.mp3"
    assert called == {
        "model_id": "example/model",
        "text": "hello",
        "output_path": "/tmp/voice.mp3",
        "voice": "Kore",
    }


def test_gemini_tts_adapter_uses_existing_method_and_voice(monkeypatch):
    import api_clients

    called = {}

    class StubGoogleClient:
        def __init__(self, config):
            called["client_config"] = config

        def generate_tts(self, text, output_path, tts_config):
            called.update(text=text, output_path=output_path, tts_config=tts_config)

    monkeypatch.setattr(api_clients, "GoogleClient", StubGoogleClient)
    result = provider_adapters.synthesize_speech({
        "AUDIO_ENGINE": "Gemini API",
        "GEMINI_API_KEY": "local-test-key",
    }, "hello", "/tmp/voice.wav", voice="Aoede")

    assert result == "/tmp/voice.wav"
    assert called["text"] == "hello"
    assert called["output_path"] == "/tmp/voice.wav"
    assert called["tts_config"]["SPEAKER1"] == "Aoede"


@pytest.mark.parametrize("engine, key", [
    ("Gemini API", "GEMINI_API_KEY"),
    ("WaveSpeed AI", "WAVESPEED_API_KEY"),
])
def test_tts_preflight_requires_selected_provider_key(engine, key):
    config = {"AUDIO_ENGINE": engine, key: ""}
    with pytest.raises(ConfigValidationError, match="Missing provider configuration"):
        validate_provider_config(config, kind="tts")


def test_ollama_text_preflight_does_not_require_cloud_key():
    validate_provider_config({"TEXT_ENGINE": "Ollama"}, kind="text")


def test_wavespeed_cancellation_is_checked_before_submission_and_poll(monkeypatch):
    from threading import Event
    import api_clients

    cancelled = Event()
    cancelled.set()
    client = api_clients.WaveSpeedClient("fixture-key", stop_event=cancelled)

    def unexpected_request(*_args, **_kwargs):
        raise AssertionError("Cancelled jobs must not contact WaveSpeed")

    monkeypatch.setattr(api_clients.requests, "post", unexpected_request)
    monkeypatch.setattr(api_clients.requests, "get", unexpected_request)
    with pytest.raises(InterruptedError, match="cancelled locally"):
        client.text_to_video("example/model", "fixture", "/tmp/no-video.mp4", "16:9")
    with pytest.raises(InterruptedError, match="cancelled locally"):
        client._poll_and_download("fixture-request", "/tmp/no-video.mp4")


def test_wave_speed_text_adapter_uses_client_text_method(monkeypatch):
    import api_clients

    called = {}

    class StubGoogleClient:
        def __init__(self, config):
            called["config"] = config

        def _generate_text(self, prompt, as_json=False):
            called.update(prompt=prompt, as_json=as_json)
            return "generated"

    monkeypatch.setattr(api_clients, "GoogleClient", StubGoogleClient)
    result = provider_adapters.generate_text({
        "TEXT_ENGINE": "Gemini API",
        "GEMINI_API_KEY": "local-test-key",
    }, "prompt", as_json=True)

    assert result == "generated"
    assert called["prompt"] == "prompt"
    assert called["as_json"] is True
