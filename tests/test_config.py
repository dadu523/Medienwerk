import json
import logging

import pytest

import config as config_module
from server.core.config_schema import ConfigValidationError, normalize_config


def test_load_migrates_legacy_wave_speed_alias_without_losing_it(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"WAVESPEED_AI_KEY": "legacy-secret"}), encoding="utf-8")

    loaded = config_module.load_config(path)

    assert loaded["WAVESPEED_API_KEY"] == "legacy-secret"
    assert loaded["WAVESPEED_AI_KEY"] == "legacy-secret"


def test_conflicting_secret_aliases_are_preserved_and_warning_hides_values(tmp_path, caplog):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({
        "WAVESPEED_API_KEY": "canonical-secret",
        "WAVESPEED_AI_KEY": "legacy-secret",
    }), encoding="utf-8")

    with caplog.at_level(logging.WARNING):
        loaded = config_module.load_config(path)

    assert loaded["WAVESPEED_API_KEY"] == "canonical-secret"
    assert loaded["WAVESPEED_AI_KEY"] == "legacy-secret"
    assert "conflicting values" in caplog.text
    assert "canonical-secret" not in caplog.text
    assert "legacy-secret" not in caplog.text


@pytest.mark.parametrize("value, expected", [
    ("16:9 (Horizontal)", "16:9"),
    ("9:16 (Vertical)", "9:16"),
    ("1:1 (Square)", "1:1"),
])
def test_aspect_ratio_aliases_are_canonical(value, expected):
    assert normalize_config({"VIDEO_ASPECT_RATIO": value})["VIDEO_ASPECT_RATIO"] == expected


def test_unknown_aspect_ratio_is_rejected():
    with pytest.raises(ConfigValidationError, match="VIDEO_ASPECT_RATIO"):
        normalize_config({"VIDEO_ASPECT_RATIO": "4:3"})


def test_loading_preserves_old_enabled_options_and_reports_unsupported_ones():
    public = config_module.public_config({"OMNICHANNEL": True, "TIMED_IMAGES_AS_SLIDESHOW": True})
    assert public["OMNICHANNEL"] is True
    assert public["TIMED_IMAGES_AS_SLIDESHOW"] is True
    assert public["UNSUPPORTED_ENABLED_FLAGS"] == ["OMNICHANNEL"]


def test_corrupt_config_is_not_replaced_by_defaults(tmp_path):
    path = tmp_path / "config.json"
    original = "{ broken data"
    path.write_text(original, encoding="utf-8")

    with pytest.raises(config_module.ConfigFileError):
        config_module.load_config(path)

    assert path.read_text(encoding="utf-8") == original


def test_save_is_atomic_and_propagates_errors(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    config_module.save_config({"FACT_CHECK": True}, path)
    assert json.loads(path.read_text(encoding="utf-8"))["FACT_CHECK_ENABLED"] is True
    assert list(tmp_path.glob("*.tmp")) == []

    def fail_replace(*args):
        raise OSError("disk unavailable")

    monkeypatch.setattr(config_module.os, "replace", fail_replace)
    with pytest.raises(config_module.ConfigFileError):
        config_module.save_config({"FACT_CHECK_ENABLED": False}, path)
    assert json.loads(path.read_text(encoding="utf-8"))["FACT_CHECK_ENABLED"] is True


def test_public_config_masks_secrets_and_reports_configured_state():
    public = config_module.public_config({
        "GEMINI_API_KEY": "gemini-secret",
        "WAVESPEED_API_KEY": "wavespeed-secret",
    })

    assert public["GEMINI_API_KEY"] == ""
    assert public["GEMINI_API_KEY_CONFIGURED"] is True
    assert public["WAVESPEED_API_KEY"] == ""
    assert public["WAVESPEED_API_KEY_CONFIGURED"] is True
    assert "gemini-secret" not in repr(public)
    assert "wavespeed-secret" not in repr(public)


def test_effective_config_returns_isolated_validated_snapshot(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    config_module.save_config({"HOST_PERSONA": "saved"}, path)
    monkeypatch.setattr(config_module, "CONFIG_FILE", str(path))

    snapshot = config_module.effective_config({"FACT_CHECK": True})
    snapshot["HOST_PERSONA"] = "mutated"

    assert config_module.load_config(path)["HOST_PERSONA"] == "saved"
    assert snapshot["FACT_CHECK_ENABLED"] is True


def test_masked_secret_preserves_saved_value_and_explicit_delete_clears_it(tmp_path):
    path = tmp_path / "config.json"
    config_module.save_config({"WAVESPEED_API_KEY": "saved-secret"}, path)

    config_module.update_config({"WAVESPEED_API_KEY": ""}, config_path=path)
    assert config_module.load_config(path)["WAVESPEED_API_KEY"] == "saved-secret"

    public = config_module.update_config({}, delete_secrets=["WAVESPEED_API_KEY"], config_path=path)
    assert config_module.load_config(path)["WAVESPEED_API_KEY"] == ""
    assert public["WAVESPEED_API_KEY_CONFIGURED"] is False


def test_body_secret_delete_clears_canonical_and_legacy_alias(tmp_path):
    path = tmp_path / "config.json"
    config_module.save_config({
        "WAVESPEED_API_KEY": "canonical-secret",
        "WAVESPEED_AI_KEY": "legacy-secret",
    }, path)

    public = config_module.update_config({"delete_secrets": ["WAVESPEED_API_KEY"]}, config_path=path)
    loaded = config_module.load_config(path)
    assert loaded["WAVESPEED_API_KEY"] == ""
    assert "WAVESPEED_AI_KEY" not in loaded
    assert public["WAVESPEED_API_KEY_CONFIGURED"] is False


def test_arbitrary_secret_suffixes_are_removed_from_nested_snapshots():
    value = {
        "SERPER_API_KEY": "serper-secret",
        "job": {"CUSTOM_ACCESS_TOKEN": "token-secret", "status": "running"},
    }

    sanitized = config_module.sanitize_config(value)
    assert "SERPER_API_KEY" not in sanitized
    assert sanitized["SERPER_API_KEY_CONFIGURED"] is True
    assert sanitized["job"] == {"status": "running"}
    redacted = config_module.redact_secrets({"log": "token-secret serper-secret"}, value)
    assert redacted["log"] == "[REDACTED] [REDACTED]"
