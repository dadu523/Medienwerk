"""
config.py

Handles loading and saving of application configuration settings from a JSON file.
"""

import copy
import json
import logging
import os
import tempfile
import threading
from pathlib import Path
from typing import Any, Mapping

from server.core.config_schema import (
    DEFAULT_CONFIG,
    SECRET_KEYS,
    UNSUPPORTED_PROVIDER_FLAGS,
    ConfigValidationError,
    normalize_config,
)

CONFIG_FILE = os.environ.get("MEDIENWERK_CONFIG_FILE", "config.json")
_CONFIG_LOCK = threading.RLock()


class ConfigFileError(RuntimeError):
    """A configuration file could not safely be loaded or saved."""


def load_config(config_path: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    path = Path(config_path or CONFIG_FILE)
    if path.exists():
        try:
            with path.open("r", encoding="utf-8") as stream:
                config_data = json.load(stream)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            logging.error("Configuration file '%s' is corrupted; preserving it", path)
            raise ConfigFileError(f"Configuration file '{path}' is invalid JSON") from exc
        except OSError as exc:
            raise ConfigFileError(f"Could not read configuration file '{path}'") from exc
        config_data = normalize_config(config_data, fill_defaults=True)
        return config_data

    config_data = copy.deepcopy(DEFAULT_CONFIG)
    save_config(config_data, path)
    return config_data


def save_config(config: Mapping[str, Any], config_path: str | os.PathLike[str] | None = None) -> None:
    path = Path(config_path or CONFIG_FILE)
    normalized = normalize_config(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent,
            prefix=f".{path.name}.", suffix=".tmp", delete=False,
        ) as stream:
            temporary_path = stream.name
            json.dump(normalized, stream, indent=4, ensure_ascii=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
        temporary_path = None
        logging.info("Configuration saved to %s", path)
    except OSError as exc:
        raise ConfigFileError(f"Could not save configuration file '{path}'") from exc
    finally:
        if temporary_path is not None:
            try:
                os.unlink(temporary_path)
            except OSError:
                pass


def sanitize_config(config: Mapping[str, Any]) -> dict[str, Any]:
    """Remove secret material while preserving non-secret effective settings."""
    def clean(value: Any) -> Any:
        if isinstance(value, Mapping):
            return {key: clean(item) for key, item in value.items() if not _is_secret_key(str(key))}
        if isinstance(value, list):
            return [clean(item) for item in value]
        if isinstance(value, tuple):
            return tuple(clean(item) for item in value)
        return copy.deepcopy(value)

    sanitized = clean(config)
    for key, value in config.items():
        if _is_secret_key(str(key)):
            sanitized[f"{key}_CONFIGURED"] = bool(value)
    return sanitized


def public_config(config: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Return config fields safe for API responses, with blank secret inputs and flags."""
    effective = normalize_config(config if config is not None else load_config(), fill_defaults=True)
    result = sanitize_config(effective)
    for key in {key for key in effective if _is_secret_key(key)} | SECRET_KEYS:
        result[key] = ""
    result["UNSUPPORTED_ENABLED_FLAGS"] = sorted(
        key for key in UNSUPPORTED_PROVIDER_FLAGS if effective.get(key) is True
    )
    return result


def update_config(
    updates: Mapping[str, Any],
    *,
    replace_secrets: set[str] | list[str] | tuple[str, ...] = (),
    delete_secrets: set[str] | list[str] | tuple[str, ...] = (),
    config_path: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    """Merge validated settings and return the public representation.

    Empty secret fields are treated as masked form values and preserve the saved
    value. Secret deletion must be explicit through ``delete_secrets``.
    """
    if not isinstance(updates, Mapping):
        raise ConfigValidationError("Configuration updates must be a JSON object")
    incoming = dict(updates)
    body_replace = incoming.pop("replace_secrets", ())
    body_delete = incoming.pop("delete_secrets", ())
    replace_names = {_canonical_secret_name(name) for name in (*replace_secrets, *_secret_action_values(body_replace))}
    delete_names = {_canonical_secret_name(name) for name in (*delete_secrets, *_secret_action_values(body_delete))}
    unknown_secret_actions = {name for name in replace_names | delete_names if not _is_secret_key(name)}
    if unknown_secret_actions:
        raise ConfigValidationError("Secret action contains an unsupported key")

    if "WAVESPEED_AI_KEY" in incoming and "WAVESPEED_API_KEY" not in incoming:
        incoming["WAVESPEED_API_KEY"] = incoming["WAVESPEED_AI_KEY"]
    for alias, canonical in (("FACT_CHECK", "FACT_CHECK_ENABLED"), ("FACT_CHECKING_ENABLED", "FACT_CHECK_ENABLED")):
        if alias in incoming and canonical not in incoming:
            incoming[canonical] = incoming[alias]
    with _CONFIG_LOCK:
        current = normalize_config(load_config(config_path), fill_defaults=True)
        for key in delete_names:
            current[key] = ""
            incoming.pop(key, None)
            if key == "WAVESPEED_API_KEY":
                current.pop("WAVESPEED_AI_KEY", None)
                incoming.pop("WAVESPEED_AI_KEY", None)

        for key in list(incoming):
            if not _is_secret_key(key):
                continue
            value = incoming.pop(key)
            if key not in delete_names and value not in (None, ""):
                current[key] = value

        merged = dict(current)
        merged.update(incoming)
        normalized = normalize_config(merged, fill_defaults=True)
        save_config(normalized, config_path)
        return public_config(normalized)


def _canonical_secret_name(name: str) -> str:
    return "WAVESPEED_API_KEY" if name == "WAVESPEED_AI_KEY" else name


def _is_secret_key(name: str) -> bool:
    normalized = name.upper()
    return normalized in SECRET_KEYS or normalized.endswith((
        "_API_KEY", "_KEY", "_TOKEN", "_SECRET", "_PASSWORD", "_CREDENTIAL", "_CREDENTIALS",
    ))


def _secret_action_values(value: Any) -> tuple[str, ...]:
    if value in (None, ""):
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, (list, tuple, set)) and all(isinstance(item, str) for item in value):
        return tuple(value)
    raise ConfigValidationError("Secret actions must be a key name or a list of key names")


def redact_secrets(value: Any, config: Mapping[str, Any]) -> Any:
    """Recursively remove secret fields and redact known secret values in text."""
    safe = sanitize_config(value) if isinstance(value, Mapping) else copy.deepcopy(value)
    secrets: list[str] = []

    def collect(item: Any) -> None:
        if isinstance(item, Mapping):
            for key, nested in item.items():
                if _is_secret_key(str(key)) and nested not in (None, ""):
                    secrets.append(str(nested))
                else:
                    collect(nested)
        elif isinstance(item, (list, tuple)):
            for nested in item:
                collect(nested)

    collect(config)

    def redact(item: Any) -> Any:
        if isinstance(item, str):
            for secret in secrets:
                item = item.replace(secret, "[REDACTED]")
            return item
        if isinstance(item, Mapping):
            return {key: redact(nested) for key, nested in item.items() if not _is_secret_key(str(key))}
        if isinstance(item, list):
            return [redact(nested) for nested in item]
        if isinstance(item, tuple):
            return tuple(redact(nested) for nested in item)
        return item

    return redact(safe)


def effective_config(overrides: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Freeze a deep-copied config snapshot with per-job overrides applied."""
    base = normalize_config(load_config(), fill_defaults=True)
    if overrides:
        if not isinstance(overrides, Mapping):
            raise ConfigValidationError("Configuration overrides must be a JSON object")
        incoming = copy.deepcopy(dict(overrides))
        if "WAVESPEED_AI_KEY" in incoming and "WAVESPEED_API_KEY" not in incoming:
            incoming["WAVESPEED_API_KEY"] = incoming["WAVESPEED_AI_KEY"]
        for alias, canonical in (("FACT_CHECK", "FACT_CHECK_ENABLED"), ("FACT_CHECKING_ENABLED", "FACT_CHECK_ENABLED")):
            if alias in incoming and canonical not in incoming:
                incoming[canonical] = incoming[alias]
        base.update(incoming)
    return normalize_config(base, fill_defaults=True)


def validate_provider_config(config: Mapping[str, Any], kind: str = "quick") -> None:
    """Raise a safe, actionable error when selected provider credentials are missing."""
    effective = normalize_config(config, fill_defaults=True)
    required: set[str] = set()
    if kind == "quick":
        enabled_unsupported = sorted(key for key in UNSUPPORTED_PROVIDER_FLAGS if effective.get(key) is True)
        if enabled_unsupported:
            raise ConfigValidationError(f"Unsupported enabled options: {', '.join(enabled_unsupported)}")
        text_engine = effective.get("TEXT_ENGINE", "Gemini API")
        audio_engine = effective.get("AUDIO_ENGINE", "Gemini API")
        if text_engine == "Gemini API":
            required.add("GEMINI_API_KEY")
        elif text_engine == "WaveSpeed AI":
            required.add("WAVESPEED_API_KEY")
            _require_model(effective, "WAVESPEED_TEXT_MODEL", "WaveSpeed text")
        if audio_engine == "Gemini API":
            required.add("GEMINI_API_KEY")
            _validate_voice(effective, audio_engine)
        elif audio_engine == "WaveSpeed AI":
            required.add("WAVESPEED_API_KEY")
            _require_model(effective, "WAVESPEED_AUDIO_MODEL", "WaveSpeed audio")
            _validate_voice(effective, audio_engine)

        if effective.get("BG_MODE", "AI Video") == "AI Video":
            video_engine = effective.get("VIDEO_ENGINE", "WaveSpeed AI")
            if video_engine == "WaveSpeed AI":
                required.add("WAVESPEED_API_KEY")
                _require_model(effective, "WAVESPEED_VIDEO_MODEL", "WaveSpeed video")
        elif effective.get("BG_MODE") == "Stock Video (Pixabay)":
            required.add("PIXABAY_API_KEY")

        needs_images = effective.get("GENERATE_THUMBNAIL", False) or effective.get("GENERATE_TIMED_IMAGES", False)
        if needs_images:
            image_engine = effective.get("IMAGE_ENGINE", "Gemini API")
            if image_engine == "Gemini API":
                required.add("GEMINI_API_KEY")
            elif image_engine == "WaveSpeed AI":
                required.add("WAVESPEED_API_KEY")
                _require_model(effective, "WAVESPEED_IMAGE_MODEL", "WaveSpeed image")
    elif kind == "tts":
        engine = effective.get("AUDIO_ENGINE", "Gemini API")
        if engine == "Gemini API":
            required.add("GEMINI_API_KEY")
        else:
            required.add("WAVESPEED_API_KEY")
            _require_model(effective, "WAVESPEED_AUDIO_MODEL", "WaveSpeed audio")
        _validate_voice(effective, engine)
    elif kind == "text":
        engine = effective.get("TEXT_ENGINE", "Gemini API")
        if engine == "Gemini API":
            required.add("GEMINI_API_KEY")
        elif engine == "WaveSpeed AI":
            required.add("WAVESPEED_API_KEY")
            _require_model(effective, "WAVESPEED_TEXT_MODEL", "WaveSpeed text")
    elif kind == "image":
        if effective.get("IMAGE_ENGINE") == "Gemini API":
            required.add("GEMINI_API_KEY")
        elif effective.get("IMAGE_ENGINE") == "WaveSpeed AI":
            required.add("WAVESPEED_API_KEY")
            _require_model(effective, "WAVESPEED_IMAGE_MODEL", "WaveSpeed image")
    elif kind == "video":
        if effective.get("VIDEO_ENGINE") == "WaveSpeed AI":
            required.add("WAVESPEED_API_KEY")
            _require_model(effective, "WAVESPEED_VIDEO_MODEL", "WaveSpeed video")
    else:
        raise ConfigValidationError("Provider validation kind must be quick, tts, text, image, or video")

    if "PIXABAY_API_KEY" in required and not effective.get("PIXABAY_API_KEY"):
        raise ConfigValidationError("Missing provider configuration: PIXABAY API key")
    missing = sorted(key for key in required if not effective.get(key))
    if missing:
        labels = ", ".join(key.removesuffix("_API_KEY").replace("_", " ") for key in missing)
        raise ConfigValidationError(f"Missing provider configuration: {labels} API key")


def _require_model(config: Mapping[str, Any], key: str, provider: str) -> None:
    if not config.get(key):
        raise ConfigValidationError(f"{provider} model must be configured")


def _validate_voice(config: Mapping[str, Any], engine: str) -> None:
    voice = config.get("VOICE_NAME") or config.get("SPEAKER1", "Kore")
    if not isinstance(voice, str) or not voice.strip():
        raise ConfigValidationError("A non-empty voice must be selected")
    if engine == "Gemini API":
        if voice not in VOICE_OPTIONS:
            raise ConfigValidationError("Selected voice is not supported by Gemini TTS")

DEFAULT_PIPELINE_STEPS = [
    "Write Script", "Generate Voiceover", "Generate Images", "Video Generation",
    "Add Background Music", "Create Final Video", "Generate SEO Metadata", "Generate Timestamps", "Generate Snippets"
]

VOICE_OPTIONS = {
    "Achernar": "Clear, mid-range, enthusiastic & approachable", "Achird": "Youthful, breathy, inquisitive tone",
    "Algenib": "Warm, confident, friendly authority", "Alnilam": "Energetic, low pitch, promotional tone",
    "Aoede": "Clear, conversational, thoughtful", "Autonoe": "Mature, resonant, calm and wise",
    "Callirrhoe": "Confident, professional, energetic", "Despina": "Warm, inviting, trustworthy",
    "Erinome": "Professional, articulate, thoughtful", "Gacrux": "Authoritative yet approachable",
    "Iapetus": "Casual, relatable, ‘everyman’ tone", "Kore": "Energetic, youthful, clear & bright",
    "Laomedeia": "Inquisitive, intelligent & engaging", "Leda": "Composed, professional, calm",
    "Orus": "Resonant, authoritative, thoughtful", "Puck": "Confident, informal, trustworthy",
    "Pulcherrima": "Bright, enthusiastic, youthful", "Rasalgethi": "Conversational, thoughtful, quirky",
    "Sadachbia": "Deep, textured, confident, cool", "Sadaltager": "Friendly, enthusiastic, professional",
    "Schedar": "Down-to-earth, approachable", "Sulafat": "Warm, persuasive, articulate",
    "Umbriel": "Authoritative, clear, engaging", "Vindemiatrix": "Calm, mature, smooth, reassuring",
    "Zephyr": "Energetic, bright, perky & enthusiastic", "Zubenelgenubi": "Deep, resonant, powerful authority"
}

PODCAST_STYLES = ["Informative News", "Comedy / Entertaining", "Educational / Explainer", "Motivational / Inspiring", "Casual Conversational", "Serious Debate", "Story Mode", "Documentary", "ASMR"]
STORY_ARCS = ["None", "Hero's Journey", "Three-Act Structure", "Man vs. Nature", "Rags to Riches", "Voyage and Return"]
CONTENT_STYLES = ["Podcast", "ASMR Video", "Documentary", "Product Ad", "Story", "Kids Story", "Horror Story", "Viral Video"]
SCRIPT_LENGTHS = ["Micro (< 1 minute)", "Short (~2 minutes)", "Medium (~5 minutes)", "Long (~10 minutes)"]
