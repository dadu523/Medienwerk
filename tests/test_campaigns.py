import json

import pytest

import config
from server.core import scheduler


def test_load_pauses_previously_active_campaign_and_records_old_state(tmp_path):
    path = tmp_path / "campaigns.json"
    path.write_text(json.dumps([{
        "id": "old-campaign", "name": "daily", "niche": "tech",
        "preset": "Tech News Short", "frequency_hours": 24,
        "next_run": 0, "active": True,
    }]), encoding="utf-8")

    manager = scheduler.CampaignManager(path)
    campaign = manager.get_campaigns()[0]

    assert campaign["active"] is False
    assert campaign["active_before_stabilization"] is True
    persisted = json.loads(path.read_text(encoding="utf-8"))[0]
    assert persisted["schema_version"] == scheduler.SCHEDULER_VERSION


def test_new_campaign_starts_paused_and_validates_bounds(tmp_path):
    manager = scheduler.CampaignManager(tmp_path / "campaigns.json")

    campaign = manager.add_campaign("New campaign", "science", "Historical Deep Dive", 24)

    assert campaign["active"] is False
    assert campaign["next_run"] > campaign["last_run"] if campaign["last_run"] else campaign["next_run"] > 0
    with pytest.raises(ValueError, match="frequency"):
        manager.add_campaign("Bad", "topic", "Tech News Short", float("inf"))


def test_activation_requires_provider_preflight(tmp_path, monkeypatch):
    manager = scheduler.CampaignManager(tmp_path / "campaigns.json")
    campaign = manager.add_campaign("Need keys", "science", "Historical Deep Dive", 24)
    monkeypatch.setattr(scheduler, "effective_config", lambda: {})
    monkeypatch.setattr(scheduler, "validate_provider_config", lambda *_args, **_kwargs: (_ for _ in ()).throw(config.ConfigValidationError("Missing API key")))

    with pytest.raises(config.ConfigValidationError):
        manager.toggle(campaign["id"])
    assert manager.get_campaigns()[0]["active"] is False


def test_run_due_uses_stable_key_and_queues_only_one_job(tmp_path, monkeypatch):
    manager = scheduler.CampaignManager(tmp_path / "campaigns.json")
    campaign = manager.add_campaign("Due", "climate science", "Tech News Short", 1)
    stored_campaign = manager.campaigns[0]
    stored_campaign["active"] = True
    stored_campaign["next_run"] = 1000.0
    manager.save()
    calls = []

    from server.routers import generation
    monkeypatch.setattr(generation, "start_quick_generation", lambda req, idempotency_key=None: calls.append((req, idempotency_key)) or {"job_id": "job-1", "status": "queued"})

    first = manager.run_due(now=1200.0)
    second = manager.run_due(now=1200.0)

    assert len(first) == 1
    assert second == []
    assert calls[0][0].topic == "climate science"
    assert calls[0][0].omnichannel is False
    assert calls[0][1] == f"campaign:{campaign['id']}:1000000"
    updated = manager.get_campaigns()[0]
    assert updated["last_job_id"] == "job-1"
    assert updated["next_run"] > 1200
