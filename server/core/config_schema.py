"""Typed defaults and compatibility normalization for application settings."""

from __future__ import annotations

import copy
import logging
from typing import Any, Mapping

DEFAULT_CONFIG: dict[str, Any] = {
    "GEMINI_API_KEY": "",
    "WAVESPEED_API_KEY": "",
    "WAVESPEED_IMAGE_MODEL": "black-forest-labs/flux-1.1-pro-ultra",
    "WAVESPEED_VIDEO_MODEL": "wavespeed-ai/ltx-2.3-text-to-video",
    "WAVESPEED_AUDIO_MODEL": "elevenlabs/text-to-speech",
    "NEWS_API_KEY": "",
    "PIXABAY_API_KEY": "",
    "VIDEO_ENGINE": "WaveSpeed AI",
    "IMAGE_ENGINE": "Gemini API",
    "TEXT_ENGINE": "Gemini API",
    "AUDIO_ENGINE": "Gemini API",
    "OLLAMA_BASE_URL": "http://localhost:11434",
    "OLLAMA_MODEL": "llama3",
    "WAVESPEED_TEXT_MODEL": "meta-llama/llama-3.3-70b-instruct",
    "SPEAKER1": "Kore",
    "SPEAKER2": "Puck",
    "HOST_NAME": "Alex",
    "GUEST_NAME": "Maya",
    "HOST_PERSONA": "A friendly podcast host who loves technology.",
    "GUEST_PERSONA": "An expert on the topic with a calm and informative style.",
    "CHANNEL_NAME": "My AI Channel",
    "SUBSCRIBE_COUNT": 3,
    "SUBSCRIBE_MESSAGE": "Don’t forget to subscribe to {channel} for more awesome content!",
    "SUBSCRIBE_RANDOM": True,
    "PODCAST_STYLE": "Informative News",
    "VIDEO_PROMPT_BASE_STYLE": "An animated and cinematic video. High-quality, 24fps.",
    "IMAGE_PROMPT_STYLE": "A cinematic, photorealistic image representing the podcast topic: {topic}",
    "STORY_ARC": "None",
    "API_DELAY": 2,
    "FACT_CHECK_ENABLED": False,
    "CAPTION_ENABLED": False,
    "CAPTION_FONT": "Arial",
    "CAPTION_FONT_SIZE": 22,
    "CAPTION_THEME": "default",
    "GENERATE_METADATA": False,
    "GENERATE_THUMBNAIL": False,
    "GENERATE_TIMED_IMAGES": False,
    "GENERATE_TIMESTAMPS": True,
    "BG_MODE": "AI Video",
    "IMAGE_COUNT": 8,
    "VIDEO_CLIP_COUNT": 1,
    "YOUTUBE_CLIENT_ID": "",
    "YOUTUBE_CLIENT_SECRET": "",
    "FACEBOOK_ACCESS_TOKEN": "",
    "SERPER_API_KEY": "",
    "VIDEO_TITLE": "",
    "VIDEO_DESCRIPTION": "",
    "VIDEO_TAGS": "",
    "LANGUAGE_ENABLED": False,
    "PODCAST_LANGUAGE": "English",
    "VIDEO_ASPECT_RATIO": "16:9",
    "SCRIPT_LENGTH": "Medium (~5 minutes)",
    "ADD_MUSIC": False,
    "GENERATE_SNIPPETS": False,
    "IMAGE_GENERATION_INTERVAL": 10,
    "TIMED_IMAGES_AS_SLIDESHOW": False,
}

SECRET_KEYS = frozenset({
    "GEMINI_API_KEY", "WAVESPEED_API_KEY", "WAVESPEED_AI_KEY", "NEWS_API_KEY",
    "PIXABAY_API_KEY", "YOUTUBE_CLIENT_SECRET", "FACEBOOK_ACCESS_TOKEN", "SERPER_API_KEY",
})

KEY_ALIASES = {
    "WAVESPEED_AI_KEY": "WAVESPEED_API_KEY",
    "FACT_CHECK": "FACT_CHECK_ENABLED",
    "FACT_CHECKING_ENABLED": "FACT_CHECK_ENABLED",
}

ENGINE_OPTIONS = {
    "TEXT_ENGINE": {"Gemini API", "WaveSpeed AI", "Ollama"},
    "IMAGE_ENGINE": {"Gemini API", "WaveSpeed AI"},
    "VIDEO_ENGINE": {"WaveSpeed AI", "Vertex AI (Veo)"},
    "AUDIO_ENGINE": {"Gemini API", "WaveSpeed AI"},
}

_BOOL_FIELDS = {
    key for key, value in DEFAULT_CONFIG.items() if isinstance(value, bool)
} | {"FACT_CHECK", "FACT_CHECKING_ENABLED", "OMNICHANNEL", "GENERATE_SEO"}
_INT_FIELDS = {
    key for key, value in DEFAULT_CONFIG.items() if isinstance(value, int) and not isinstance(value, bool)
}
_STRING_FIELDS = {
    key for key, value in DEFAULT_CONFIG.items() if isinstance(value, str)
} | SECRET_KEYS
UNSUPPORTED_PROVIDER_FLAGS = frozenset({"OMNICHANNEL", "LANGUAGE_ENABLED"})

ASPECT_RATIOS = {"16:9", "9:16", "1:1"}
ASPECT_RATIO_ALIASES = {
    "16:9 (horizontal)": "16:9",
    "16:9 (youtube)": "16:9",
    "16:9 (landscape)": "16:9",
    "9:16 (vertical)": "9:16",
    "9:16 (portrait)": "9:16",
    "1:1 (square)": "1:1",
    "1:1 (instagram)": "1:1",
}


class ConfigValidationError(ValueError):
    """Raised when a known configuration field has an unsupported value."""


def _normalize_aspect_ratio(value: Any) -> str:
    if not isinstance(value, str):
        raise ConfigValidationError("VIDEO_ASPECT_RATIO must be a string")
    normalized = ASPECT_RATIO_ALIASES.get(value.strip().lower(), value.strip())
    if normalized not in ASPECT_RATIOS:
        raise ConfigValidationError("VIDEO_ASPECT_RATIO must be 16:9, 9:16, or 1:1")
    return normalized


def normalize_config(config: Mapping[str, Any], *, fill_defaults: bool = False) -> dict[str, Any]:
    """Copy, normalize aliases, and validate recognized fields without dropping extras."""
    if not isinstance(config, Mapping):
        raise ConfigValidationError("Configuration must be a JSON object")

    result = copy.deepcopy(dict(config))
    for alias, canonical in KEY_ALIASES.items():
        if alias not in result:
            continue
        alias_value = result[alias]
        canonical_value = result.get(canonical)
        populated_alias = alias_value not in (None, "")
        populated_canonical = canonical_value not in (None, "")
        if populated_alias and not populated_canonical:
            result[canonical] = alias_value
        elif populated_alias and populated_canonical and alias_value != canonical_value:
            logging.warning("Configuration contains conflicting values for %s and legacy alias %s; preserving both", canonical, alias)

    if fill_defaults:
        for key, value in DEFAULT_CONFIG.items():
            result.setdefault(key, copy.deepcopy(value))

    for key, options in ENGINE_OPTIONS.items():
        if key in result and result[key] not in options:
            raise ConfigValidationError(f"{key} has an unsupported value")

    if "VIDEO_ASPECT_RATIO" in result:
        result["VIDEO_ASPECT_RATIO"] = _normalize_aspect_ratio(result["VIDEO_ASPECT_RATIO"])

    for key in _BOOL_FIELDS:
        if key in result and not isinstance(result[key], bool):
            raise ConfigValidationError(f"{key} must be a boolean")
    for key in _INT_FIELDS:
        if key in result:
            if isinstance(result[key], bool) or not isinstance(result[key], int):
                raise ConfigValidationError(f"{key} must be an integer")
            if result[key] < 0:
                raise ConfigValidationError(f"{key} must not be negative")
    for key in _STRING_FIELDS:
        if key in result and result[key] is not None and not isinstance(result[key], str):
            raise ConfigValidationError(f"{key} must be a string")
    for key, value in result.items():
        if key.upper().endswith(("_API_KEY", "_KEY", "_TOKEN", "_SECRET", "_PASSWORD", "_CREDENTIAL", "_CREDENTIALS")) and not isinstance(value, str):
            raise ConfigValidationError(f"{key} must be a string")
    for key, value in result.items():
        if key.upper().endswith(("_API_KEY", "_KEY", "_TOKEN", "_SECRET", "_PASSWORD", "_CREDENTIAL", "_CREDENTIALS")) and not isinstance(value, str):
            raise ConfigValidationError(f"{key} must be a string")

    return result
