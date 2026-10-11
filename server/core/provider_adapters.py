"""Small adapters for the provider methods implemented by the existing clients."""

from __future__ import annotations

from typing import Any, Mapping
from threading import Event

from config import validate_provider_config
from server.core.config_schema import normalize_config


def generate_text(config: Mapping[str, Any], prompt: str, *, as_json: bool = False) -> str:
    validate_provider_config(config, "text")
    from api_clients import GoogleClient

    effective = normalize_config(config, fill_defaults=True)
    return GoogleClient(effective)._generate_text(prompt, as_json=as_json)


def synthesize_speech(
    config: Mapping[str, Any],
    text: str,
    output_path: str,
    *,
    voice: str | None = None,
    stop_event: Event | None = None,
) -> str:
    """Use the selected TTS client and its actual method signature."""
    validate_provider_config(config, "tts")
    effective = normalize_config(config, fill_defaults=True)
    engine = effective.get("AUDIO_ENGINE", "Gemini API")
    voice_name = voice or effective.get("VOICE_NAME") or effective.get("SPEAKER1", "Kore")
    if engine == "WaveSpeed AI":
        from api_clients import WaveSpeedClient

        client = WaveSpeedClient(effective.get("WAVESPEED_API_KEY", ""), stop_event=stop_event)
        client.text_to_speech(
            effective.get("WAVESPEED_AUDIO_MODEL", "elevenlabs/text-to-speech"),
            text,
            output_path,
            voice=voice_name,
        )
    elif engine == "Gemini API":
        from api_clients import GoogleClient

        tts_config = dict(effective)
        tts_config["SPEAKER1"] = voice_name
        tts_config.setdefault("CONTENT_STYLE", "Single Speaker")
        GoogleClient(effective).generate_tts(text, output_path, tts_config)
    else:
        raise ValueError("Selected audio engine does not provide text-to-speech")
    return output_path
