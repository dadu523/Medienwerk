"""Paused-by-default local campaign scheduler with durable due-run idempotency."""

from __future__ import annotations

import copy
import json
import logging
import math
import os
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from config import ConfigValidationError, effective_config, validate_provider_config

CAMPAIGNS_FILE = os.environ.get("MEDIENWERK_CAMPAIGNS_FILE", "campaigns.json")
CAMPAIGN_PRESETS = {
    "Tech News Short", "Scary Story", "Motivation / Hustle", "Historical Deep Dive",
}
SCHEDULER_VERSION = 2


class CampaignManager:
    def __init__(self, campaigns_file: str | os.PathLike[str] | None = None):
        self.path = Path(campaigns_file or CAMPAIGNS_FILE)
        self.campaigns: list[dict[str, Any]] = []
        self._lock = threading.RLock()
        self._tick_lock = threading.Lock()
        self.load()

    def load(self) -> None:
        with self._lock:
            if not self.path.exists():
                self.campaigns = []
                return
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise RuntimeError(f"Could not read campaigns file '{self.path}'") from exc
            if not isinstance(data, list) or any(not isinstance(item, dict) for item in data):
                raise RuntimeError("Campaigns file must contain a JSON list of campaign objects")
            migrated = False
            for campaign in data:
                try:
                    campaign.setdefault("id", str(uuid.uuid4()))
                    campaign["frequency_hours"] = float(campaign.get("frequency_hours", 24))
                    campaign.setdefault("next_run", time.time() + campaign["frequency_hours"] * 3600)
                    campaign.setdefault("last_run", None)
                    campaign.setdefault("last_topic", None)
                    campaign.setdefault("preset", "Historical Deep Dive")
                    campaign.setdefault("active", False)
                except (TypeError, ValueError):
                    campaign["active"] = False
                    campaign["frequency_hours"] = 24.0
                    campaign["next_run"] = time.time() + 86400
                if int(campaign.get("schema_version", 0) or 0) < SCHEDULER_VERSION:
                    if campaign.get("active"):
                        campaign["active_before_stabilization"] = True
                        campaign["active"] = False
                    campaign["schema_version"] = SCHEDULER_VERSION
                    migrated = True
            self.campaigns = data
            if migrated:
                self._save_locked()

    def _save_locked(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=self.path.parent,
                prefix=f".{self.path.name}.", suffix=".tmp", delete=False,
            ) as stream:
                temporary_path = stream.name
                json.dump(self.campaigns, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_path, self.path)
            temporary_path = None
        except OSError as exc:
            raise RuntimeError(f"Could not save campaigns file '{self.path}'") from exc
        finally:
            if temporary_path is not None:
                try:
                    os.unlink(temporary_path)
                except OSError:
                    pass

    def save(self) -> None:
        with self._lock:
            self._save_locked()

    def add_campaign(self, name: str, niche: str, preset: str, frequency_hours: float) -> dict[str, Any]:
        name = str(name).strip()
        niche = str(niche).strip()
        try:
            frequency = float(frequency_hours)
        except (TypeError, ValueError) as exc:
            raise ValueError("Campaign frequency must be a positive number of hours") from exc
        if not name or len(name) > 120:
            raise ValueError("Campaign name must contain 1 to 120 characters")
        if not niche or len(niche) > 500:
            raise ValueError("Campaign niche must contain 1 to 500 characters")
        if preset not in CAMPAIGN_PRESETS:
            raise ValueError("Unsupported campaign preset")
        if not math.isfinite(frequency) or frequency <= 0 or frequency > 8760:
            raise ValueError("Campaign frequency must be greater than 0 and at most 8760 hours")
        now = time.time()
        campaign = {
            "id": str(uuid.uuid4()),
            "name": name,
            "niche": niche,
            "preset": preset,
            "frequency_hours": frequency,
            "next_run": now + frequency * 3600,
            "active": False,
            "last_run": None,
            "last_topic": None,
            "last_job_id": None,
            "schema_version": SCHEDULER_VERSION,
        }
        with self._lock:
            self.campaigns.append(campaign)
            self._save_locked()
        return copy.deepcopy(campaign)

    def get_campaigns(self) -> list[dict[str, Any]]:
        with self._lock:
            return copy.deepcopy(self.campaigns)

    def toggle(self, campaign_id: str) -> dict[str, Any] | None:
        with self._lock:
            campaign = next((item for item in self.campaigns if item["id"] == campaign_id), None)
            if campaign is None:
                return None
            if not campaign.get("active"):
                from server.routers.generation import _request_config
                request = _request_for_campaign(campaign)
                config = _request_config(request)
                validate_provider_config(config, kind="quick")
                campaign["active"] = True
                campaign["next_run"] = time.time() + float(campaign["frequency_hours"]) * 3600
                campaign.pop("last_error", None)
            else:
                campaign["active"] = False
            self._save_locked()
            return copy.deepcopy(campaign)

    def delete(self, campaign_id: str) -> bool:
        with self._lock:
            before = len(self.campaigns)
            self.campaigns = [item for item in self.campaigns if item["id"] != campaign_id]
            if len(self.campaigns) == before:
                return False
            self._save_locked()
            return True

    def run_due(self, now: float | None = None) -> list[dict[str, Any]]:
        """Queue at most one Quick Creator job for each persisted due timestamp."""
        from server.routers.generation import start_quick_generation

        current_time = time.time() if now is None else float(now)
        queued: list[dict[str, Any]] = []
        if not self._tick_lock.acquire(blocking=False):
            return queued
        try:
            with self._lock:
                due = [copy.deepcopy(item) for item in self.campaigns if item.get("active") and float(item.get("next_run", 0)) <= current_time]
            for campaign in due:
                due_at = float(campaign["next_run"])
                stable_key = f"campaign:{campaign['id']}:{int(due_at * 1000)}"
                try:
                    request = _request_for_campaign(campaign)
                    result = start_quick_generation(request, idempotency_key=stable_key)
                    with self._lock:
                        live = next((item for item in self.campaigns if item["id"] == campaign["id"]), None)
                        if live is None:
                            continue
                        live["last_run"] = current_time
                        live["last_topic"] = request.topic
                        live["last_job_id"] = result["job_id"]
                        live["next_run"] = current_time + float(live["frequency_hours"]) * 3600
                        live.pop("last_error", None)
                        self._save_locked()
                    queued.append(result)
                except Exception as exc:
                    logging.exception("Campaign %s could not schedule a job", campaign.get("id"))
                    with self._lock:
                        live = next((item for item in self.campaigns if item["id"] == campaign["id"]), None)
                        if live is not None:
                            live["active"] = False
                            live["last_error"] = str(exc)
                            self._save_locked()
            return queued
        finally:
            self._tick_lock.release()


def _request_for_campaign(campaign: dict[str, Any]):
    from server.routers.generation import GenerationRequest

    request = GenerationRequest(topic=campaign["niche"], content_style="Podcast", voice="Kore", aspect_ratio="16:9")
    preset = campaign.get("preset")
    if preset == "Tech News Short":
        request.content_style = "Viral Video"
        request.style = "TikTok Viral"
        request.aspect_ratio = "9:16"
    elif preset == "Scary Story":
        request.content_style = "Story"
        request.aspect_ratio = "9:16"
    elif preset == "Motivation / Hustle":
        request.content_style = "Viral Video"
        request.style = "Cyberpunk / Neon"
        request.aspect_ratio = "9:16"
    return request


campaign_mgr = CampaignManager()
_scheduler_thread: threading.Thread | None = None
_scheduler_start_lock = threading.Lock()


def scheduler_loop(stop_event: threading.Event | None = None, interval_seconds: float = 60) -> None:
    while stop_event is None or not stop_event.is_set():
        try:
            campaign_mgr.run_due()
        except Exception:
            logging.exception("Campaign scheduler tick failed")
        if stop_event is not None:
            stop_event.wait(interval_seconds)
        else:
            time.sleep(interval_seconds)


def start_scheduler() -> None:
    global _scheduler_thread
    with _scheduler_start_lock:
        if _scheduler_thread and _scheduler_thread.is_alive():
            return
        _scheduler_thread = threading.Thread(target=scheduler_loop, daemon=True, name="medienwerk-campaign-scheduler")
        _scheduler_thread.start()
    logging.info("Campaign scheduler started; campaigns require explicit activation")
