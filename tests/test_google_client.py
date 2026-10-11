import base64
import wave
from types import SimpleNamespace

import pytest
from google.genai import types
from google.genai.errors import APIError

import api_clients


class FakeClient:
    def __init__(self, response, calls, options):
        self.response = response
        self.calls = calls
        self.options = options
        self.closed = False
        self.models = self

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.closed = True

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def fake_candidate(parts, finish_reason="STOP"):
    return SimpleNamespace(content=SimpleNamespace(parts=list(parts)), finish_reason=finish_reason)


def fake_response(*parts, finish_reason="STOP", other_candidates=()):
    return SimpleNamespace(candidates=[fake_candidate(parts, finish_reason), *other_candidates])


def fake_client_factory(monkeypatch, responses):
    calls = []
    clients = []
    options = []

    def factory(**kwargs):
        options.append(kwargs)
        response = responses[len(clients)]
        client = FakeClient(response, calls, kwargs)
        clients.append(client)
        return client

    monkeypatch.setattr(api_clients.genai, "Client", factory)
    return calls, clients, options


def inline_part(data, mime_type):
    return SimpleNamespace(inline_data=SimpleNamespace(data=data, mime_type=mime_type), text=None)


def text_part(text, thought=False):
    return SimpleNamespace(text=text, inline_data=None, thought=thought)


def test_text_json_uses_explicit_isolated_client_and_closes(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "ambient-gemini-key")
    calls, clients, options = fake_client_factory(
        monkeypatch,
        [fake_response(text_part('{"answer": 42}'))],
    )
    client = api_clients.GoogleClient({"GEMINI_API_KEY": "request-key"})

    result = client._generate_text("return json", as_json=True)

    assert result == '{"answer": 42}'
    assert calls[0]["model"] == api_clients.GEMINI_TEXT_MODEL
    assert calls[0]["contents"] == "return json"
    assert calls[0]["config"].response_mime_type == "application/json"
    assert options[0]["api_key"] == "request-key"
    assert options[0]["vertexai"] is False
    assert options[0]["http_options"].timeout == 120_000
    assert options[0]["http_options"].retry_options.attempts == 1
    assert clients[0].closed


def test_each_text_client_uses_its_own_key_without_global_configuration(monkeypatch):
    _, clients, options = fake_client_factory(
        monkeypatch,
        [fake_response(text_part("one")), fake_response(text_part("two"))],
    )
    first = api_clients.GoogleClient({"GEMINI_API_KEY": "key-one"})
    second = api_clients.GoogleClient({"GEMINI_API_KEY": "key-two"})

    assert first._generate_text("prompt") == "one"
    assert second._generate_text("prompt") == "two"
    assert [option["api_key"] for option in options] == ["key-one", "key-two"]
    assert all(client.closed for client in clients)


def test_missing_key_and_empty_response_fail_without_using_environment_key(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "ambient-key-must-not-be-used")
    calls, _clients, _options = fake_client_factory(monkeypatch, [fake_response()])
    client = api_clients.GoogleClient({})

    with pytest.raises(RuntimeError, match="API key not configured"):
        client._generate_text("prompt")
    assert calls == []

    keyed = api_clients.GoogleClient({"GEMINI_API_KEY": "explicit-key"})
    with pytest.raises(RuntimeError, match="no text content"):
        keyed._generate_text("prompt")


def test_text_uses_first_candidate_and_ignores_thought_parts(monkeypatch):
    fake_client_factory(monkeypatch, [fake_response(
        text_part("internal", thought=True),
        text_part("answer "),
        text_part("continued"),
        other_candidates=[fake_candidate([text_part("alternative")])],
    )])

    assert api_clients.GoogleClient({"GEMINI_API_KEY": "key"})._generate_text("prompt") == "answer continued"


def test_text_fails_when_first_candidate_has_only_thought_parts(monkeypatch):
    fake_client_factory(monkeypatch, [fake_response(text_part("internal", thought=True))])

    with pytest.raises(RuntimeError, match="no text content"):
        api_clients.GoogleClient({"GEMINI_API_KEY": "key"})._generate_text("prompt")


def test_gemini_search_research_uses_google_search_tool(monkeypatch):
    calls, clients, options = fake_client_factory(
        monkeypatch,
        [fake_response(text_part("researched summary"))],
    )

    class News:
        def get_news(self, _topic):
            return "local news context"

    client = api_clients.GoogleClient({"GEMINI_API_KEY": "research-key"})
    result = client.deep_research("topic", "English", News())

    assert result == "researched summary"
    config = calls[0]["config"]
    assert config.tools[0].google_search is not None
    assert options[0]["api_key"] == "research-key"
    assert options[0]["http_options"].timeout == 120_000
    assert clients[0].closed


def test_image_searches_mixed_parts_and_writes_sdk_bytes_without_base64_decode(monkeypatch, tmp_path):
    image_bytes = b"\x89PNG\r\nraw-image"
    calls, clients, options = fake_client_factory(
        monkeypatch,
        [fake_response(
            text_part("description"),
            inline_part(image_bytes, "image/png"),
        )],
    )
    output = tmp_path / "image.png"

    api_clients.GoogleClient({"GEMINI_API_KEY": "image-key"}).gemini_nanobanana_image("draw", str(output))

    assert output.read_bytes() == image_bytes
    assert calls[0]["model"] == api_clients.NANO_BANANA_IMAGE_MODEL
    assert api_clients.NANO_BANANA_IMAGE_MODEL == "gemini-2.5-flash-image"
    assert options[0]["http_options"].timeout == 120_000
    assert clients[0].closed


def test_image_accepts_base64_fixture_and_rejects_text_only_response(monkeypatch, tmp_path):
    image_bytes = b"image-bytes"
    fake_client_factory(monkeypatch, [fake_response(
        text_part("first"),
        inline_part(base64.b64encode(image_bytes).decode(), "image/jpeg"),
    )])
    output = tmp_path / "image.jpg"
    api_clients.GoogleClient({"GEMINI_API_KEY": "image-key"}).gemini_nanobanana_image("draw", str(output))
    assert output.read_bytes() == image_bytes

    fake_client_factory(monkeypatch, [fake_response(text_part("no image"))])
    with pytest.raises(RuntimeError, match="did not return an image"):
        api_clients.GoogleClient({"GEMINI_API_KEY": "image-key"}).gemini_nanobanana_image("draw", str(output))


@pytest.mark.parametrize(
    "script,tts_config,expected_speakers",
    [
        ("single voice", {"SPEAKER1": "Kore"}, [None]),
        (
            "Alex: hello\nMaya: hi",
            {"CONTENT_STYLE": "Podcast", "HOST_NAME": "Alex", "GUEST_NAME": "Maya", "SPEAKER1": "Kore", "SPEAKER2": "Puck"},
            ["Alex", "Maya"],
        ),
    ],
)
def test_tts_single_and_multi_speaker_config_and_wav_output(
    monkeypatch, tmp_path, script, tts_config, expected_speakers
):
    pcm = b"\x00\x00\x01\x00"
    calls, clients, options = fake_client_factory(
        monkeypatch,
        [fake_response(inline_part(pcm, "audio/L16;rate=24000"))],
    )
    output = tmp_path / "audio.wav"

    api_clients.GoogleClient({"GEMINI_API_KEY": "tts-key"}).generate_tts(script, str(output), tts_config)

    config = calls[0]["config"]
    if expected_speakers[0] is None:
        assert config.speech_config.voice_config.prebuilt_voice_config.voice_name == "Kore"
    else:
        speaker_configs = config.speech_config.multi_speaker_voice_config.speaker_voice_configs
        assert [voice.speaker for voice in speaker_configs] == expected_speakers
        assert calls[0]["contents"].endswith(script)
    assert config.response_modalities == ["AUDIO"]
    assert options[0]["http_options"].timeout == 300_000
    assert clients[0].closed
    with wave.open(str(output), "rb") as wav:
        assert (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) == (1, 2, 24_000)
        assert wav.readframes(wav.getnframes()) == pcm


def test_tts_chunks_long_script_and_concatenates_pcm(monkeypatch, tmp_path):
    script = "word " * 1900
    responses = [
        fake_response(inline_part(bytes([index, 0]), "audio/L16;rate=22050"))
        for index in range(3)
    ]
    calls, clients, _options = fake_client_factory(monkeypatch, responses)
    output = tmp_path / "long.wav"

    api_clients.GoogleClient({"GEMINI_API_KEY": "tts-key"}).generate_tts(
        script, str(output), {"SPEAKER1": "Aoede"}
    )

    assert len(calls) == 3
    prompt_instruction = (
        "You are a highly realistic human voice actor. Deliver the following script with "
        "natural emotion, dynamic pacing, breathing, and conversational tone to completely "
        "eliminate any robotic feel. Do not read this instruction, ONLY read the script:\\n\\n"
    )
    assert all(len(call["contents"]) <= 4_500 + len(prompt_instruction) for call in calls)
    assert [client.closed for client in clients] == [True, True, True]
    with wave.open(str(output), "rb") as wav:
        assert wav.getframerate() == 22_050
        assert wav.readframes(wav.getnframes()) == b"\x00\x00\x01\x00\x02\x00"


def test_tts_rejects_response_without_audio(monkeypatch, tmp_path):
    calls, clients, _options = fake_client_factory(
        monkeypatch,
        [fake_response(text_part("not audio"))],
    )

    with pytest.raises(RuntimeError, match="no audio data"):
        api_clients.GoogleClient({"GEMINI_API_KEY": "tts-key"}).generate_tts(
            "hello", str(tmp_path / "audio.wav"), {"SPEAKER1": "Kore"}
        )

    assert len(calls) == 1
    assert clients[0].closed


@pytest.mark.parametrize(
    "data,mime_type,error",
    [
        (b"\x00", "audio/L16;rate=24000", "incomplete 16-bit sample"),
        (b"\x00\x00", "audio/L16;rate=0", "non-positive sample rate"),
        (b"\x00\x00", "audio/wav", "unsupported audio format"),
    ],
)
def test_tts_rejects_invalid_pcm_before_creating_output(monkeypatch, tmp_path, data, mime_type, error):
    calls, _clients, _options = fake_client_factory(
        monkeypatch,
        [fake_response(inline_part(data, mime_type))],
    )
    output = tmp_path / "invalid.wav"

    with pytest.raises(RuntimeError, match=error):
        api_clients.GoogleClient({"GEMINI_API_KEY": "tts-key"}).generate_tts(
            "hello", str(output), {"SPEAKER1": "Kore"}
        )

    assert len(calls) == 1
    assert not output.exists()


def test_tts_rejects_mismatched_sample_rates_before_creating_output(monkeypatch, tmp_path):
    calls, _clients, _options = fake_client_factory(
        monkeypatch,
        [
            fake_response(inline_part(b"\x00\x00", "audio/L16;rate=24000")),
            fake_response(inline_part(b"\x01\x00", "audio/L16;rate=22050")),
        ],
    )
    output = tmp_path / "mismatched.wav"

    with pytest.raises(RuntimeError, match="different sample rates"):
        api_clients.GoogleClient({"GEMINI_API_KEY": "tts-key"}).generate_tts(
            "word " * 1000, str(output), {"SPEAKER1": "Kore"}
        )

    assert len(calls) == 2
    assert not output.exists()


def test_quota_api_error_is_not_retried(monkeypatch):
    calls, clients, _options = fake_client_factory(
        monkeypatch,
        [APIError(429, {"error": {"message": "quota exceeded"}})],
    )

    with pytest.raises(RuntimeError, match="quota exceeded"):
        api_clients.GoogleClient({"GEMINI_API_KEY": "key"})._generate_text("prompt")

    assert len(calls) == 1
    assert clients[0].closed
