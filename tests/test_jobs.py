"""Isolated contract tests for the persistent queue and owned child processes."""

from __future__ import annotations

import subprocess
import sys
import threading
import time
import asyncio
import json
import logging

import pytest
from starlette.websockets import WebSocket

from server.core import queue
from server.core.database import init_database
from server.core.process_runner import ProcessCancelledError, run_process


@pytest.fixture(autouse=True)
def initialize_isolated_database():
    init_database()


def test_create_job_persists_safe_snapshot_and_deduplicates():
    from config import save_config

    save_config({"GEMINI_API_KEY": "test-secret-value"})
    job_id = queue.create_job(
        "topic test-secret-value",
        workflow="quick",
        settings={"GEMINI_API_KEY": "test-secret-value", "language": "en"},
        idempotency_key="request-1",
    )
    duplicate = queue.create_job(
        "duplicate topic",
        workflow="quick",
        settings={"language": "de"},
        idempotency_key="request-1",
    )

    assert duplicate == job_id
    snapshot = queue.get_job(job_id)
    assert snapshot["status"] == "queued"
    assert snapshot["topic"] == "topic [redacted]"
    assert snapshot["settings"]["language"] == "en"
    assert "GEMINI_API_KEY" not in snapshot["settings"]
    assert snapshot["latest_seq"] == 1
    assert "test-secret-value" not in repr(snapshot)


def test_claim_is_atomic_and_terminal_status_is_immutable():
    job_id = queue.create_job("claim race")
    results = []
    threads = [threading.Thread(target=lambda: results.append(queue.claim_job(job_id))) for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert results.count(True) == 1
    assert queue.get_job(job_id)["status"] == "running"
    assert queue.update_job(job_id, status="completed", result={"clips": [{"id": "clip-1"}]}) is True
    assert queue.get_job(job_id)["status"] == "completed"
    assert queue.get_job(job_id)["progress"] == 1.0
    assert queue.update_job(job_id, status="failed", error="late failure") is False
    assert queue.get_job(job_id)["status"] == "completed"
    assert queue.get_job(job_id)["result"] == {"clips": [{"id": "clip-1"}]}


def test_legacy_processing_status_maps_to_running_and_caps_progress():
    job_id = queue.create_job("legacy status")
    assert queue.update_job(job_id, status="processing", progress=1.0, step="Rendering") is True
    snapshot = queue.get_job(job_id)
    assert snapshot["status"] == "running"
    assert snapshot["progress"] == 0.99
    assert snapshot["step"] == "Rendering"


def test_steps_persist_and_aggregate_skipped_steps():
    job_id = queue.create_job("steps")
    queue.claim_job(job_id)
    assert queue.update_step(job_id, "research", title="Research", progress=0.5)
    assert queue.update_step(job_id, "captions", title="Captions", status="skipped", progress=0)

    snapshot = queue.get_job(job_id)
    steps = queue.get_steps(job_id)
    assert snapshot["progress"] == 0.75
    assert [step["status"] for step in steps] == ["running", "skipped"]


def test_declared_step_count_keeps_quick_progress_monotonic():
    job_id = queue.create_job("fixed pipeline progress")
    queue.claim_job(job_id)

    assert queue.update_step(job_id, "pipeline.01", status="completed", progress=1.0, total_steps=10)
    first = queue.get_job(job_id)["progress"]
    assert first == pytest.approx(0.1)

    assert queue.update_step(job_id, "pipeline.02", status="completed", progress=1.0, total_steps=10)
    second = queue.get_job(job_id)["progress"]
    assert second == pytest.approx(0.2)

    # A repeated callback with lower step progress cannot move the durable
    # workflow progress backwards when the caller supplied its fixed total.
    assert queue.update_step(job_id, "pipeline.02", status="running", progress=0.0, total_steps=10)
    assert queue.get_job(job_id)["progress"] == second


def test_undeclared_step_count_keeps_observed_step_aggregation():
    job_id = queue.create_job("dynamic steps")
    queue.claim_job(job_id)
    assert queue.update_step(job_id, "first", status="completed", progress=1.0)
    assert queue.get_job(job_id)["progress"] == pytest.approx(0.99)
    assert queue.update_step(job_id, "second", status="running", progress=0.0)
    assert queue.get_job(job_id)["progress"] == pytest.approx(0.5)


def test_cancel_request_waits_for_worker_confirmation():
    job_id = queue.create_job("cancel")
    queue.claim_job(job_id)
    assert queue.request_cancel(job_id)
    assert queue.get_job(job_id)["status"] == "cancel_requested"
    assert queue.get_stop_event(job_id).is_set()

    # A late success callback cannot falsely turn the requested stop into success.
    assert queue.update_job(job_id, status="completed", result="late.mp4") is False
    assert queue.get_job(job_id)["status"] == "cancel_requested"
    assert queue.update_job(job_id, status="cancelled") is True
    assert queue.get_job(job_id)["status"] == "cancelled"


def test_restart_marks_queued_and_running_interrupted_but_preserves_input():
    for existing in queue.list_jobs():
        if existing["status"] not in queue.TERMINAL_STATES:
            queue.update_job(existing["id"], status="completed")
    queued = queue.create_job("queued")
    running = queue.create_job("running")
    awaiting = queue.create_job("awaiting input")
    assert queue.claim_job(running)
    queue.update_job(awaiting, status="awaiting_input")

    assert queue.recover_interrupted_jobs() == 2
    assert queue.get_job(queued)["status"] == "interrupted"
    assert queue.get_job(running)["status"] == "interrupted"
    assert queue.get_job(awaiting)["status"] == "awaiting_input"


def test_awaiting_input_resumes_only_through_claim_and_stop_confirms_without_worker():
    job_id = queue.create_job("selection")
    queue.update_job(job_id, status="awaiting_input")

    assert queue.update_job(job_id, status="running") is False
    assert queue.claim_job(job_id, expected=("awaiting_input",)) is True

    second = queue.create_job("selection waiting")
    queue.update_job(second, status="awaiting_input")
    assert queue.stop_job(second) is True
    assert queue.get_job(second)["status"] == "cancelled"


def test_websocket_connection_receives_persisted_full_state_snapshot():
    job_id = queue.create_job("websocket snapshot")
    queue.add_log(job_id, "first durable line")
    queue.update_job(job_id, status="running", progress=0.25, step="Working")
    sent = []
    messages = [{"type": "websocket.connect"}]

    async def receive():
        return messages.pop(0)

    async def send(message):
        sent.append(message)

    websocket = WebSocket({
        "type": "websocket",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "scheme": "ws",
        "server": ("testserver", 80),
        "client": ("testclient", 123),
        "path": f"/ws/{job_id}",
        "raw_path": f"/ws/{job_id}".encode(),
        "query_string": b"",
        "headers": [],
        "subprotocols": [],
        "path_params": {"job_id": job_id},
        "route": None,
        "app": None,
        "root_path": "",
    }, receive, send)

    async def connect_and_disconnect():
        await queue.manager.connect(websocket, job_id)
        queue.manager.disconnect(websocket, job_id)

    asyncio.run(connect_and_disconnect())
    assert sent[0]["type"] == "websocket.accept"
    snapshot = json.loads(sent[1]["text"])
    assert snapshot["type"] == "full_state"
    assert snapshot["job_id"] == job_id
    assert snapshot["seq"] == snapshot["data"]["latest_seq"]
    assert snapshot["data"]["status"] == "running"
    assert snapshot["data"]["logs"] == ["first durable line"]
    entry = snapshot["data"]["log_entries"][0]
    assert entry["seq"] == 2
    assert entry["message"] == "first durable line"
    assert entry["timestamp"].endswith("Z")


def test_ephemeral_browser_frames_do_not_reuse_persisted_event_sequence():
    job_id = queue.create_job("frame stream")
    manager = queue.ConnectionManager()
    received = []

    class FakeConnection:
        async def send_text(self, message):
            received.append(json.loads(message))

    async def broadcast_frame():
        manager.active_connections[job_id] = [FakeConnection()]
        manager.loop = asyncio.get_running_loop()
        manager.broadcast(job_id, {"type": "browser_frame", "data": "frame-data"})
        await asyncio.sleep(0)

    asyncio.run(broadcast_frame())
    assert received[0]["type"] == "browser_frame"
    assert "seq" not in received[0]


def test_complete_job_rolls_back_media_and_job_when_registration_fails(monkeypatch):
    from server.core import media_store
    from server.core.database import Media, SessionLocal, utcnow

    job_id = queue.create_job("atomic final output")
    project_id = queue.get_job(job_id)["project_id"]

    def insert_then_fail(project, path, **kwargs):
        session = kwargs["session"]
        session.add(Media(
            id="test-media-id", project_id=project, role="final",
            relative_path="output/final.mp4", storage_root="/tmp",
            media_type="video/h264", metadata_json="{}", origin="native",
            origin_key="atomic-test", created_at=utcnow(),
        ))
        session.flush()
        raise ValueError("probe rejected output")

    monkeypatch.setattr(media_store, "register_media", insert_then_fail)
    with pytest.raises(ValueError, match="probe rejected"):
        queue.complete_job(job_id, "final.mp4", media_records=[{"path": "final.mp4", "kind": "video"}])

    assert queue.get_job(job_id)["status"] == "queued"
    with SessionLocal() as db:
        assert db.get(Media, "test-media-id") is None


def test_complete_job_exposes_registered_media_ids_and_download_url(monkeypatch):
    from server.core import media_store

    job_id = queue.create_job("media result")
    monkeypatch.setattr(media_store, "register_media", lambda project, path, **kwargs: {
        "id": "media-123", "project_id": project, "path": "output/final.mp4",
        "media_type": "video/h264", "origin": "native",
    })

    assert queue.complete_job(job_id, "output/final.mp4", media_records=[{"path": "output/final.mp4", "kind": "video"}])
    snapshot = queue.get_job(job_id)
    assert snapshot["status"] == "completed"
    assert snapshot["result"] == "output/final.mp4"
    assert snapshot["result_ids"] == ["media-123"]
    assert snapshot["result_media"][0]["url"] == "/api/projects/media/media-123/download"


def test_event_retention_keeps_monotonic_sequence(monkeypatch):
    monkeypatch.setattr(queue, "MAX_EVENTS_PER_JOB", 3)
    job_id = queue.create_job("event retention")
    for index in range(6):
        queue.add_log(job_id, f"log-{index}")

    events = queue.get_job_events(job_id)
    assert [event["seq"] for event in events] == [5, 6, 7]
    assert queue.get_latest_seq(job_id) == 7
    snapshot = queue.get_job(job_id)
    assert snapshot["latest_seq"] == 7
    assert snapshot["logs"] == ["log-3", "log-4", "log-5"]


def test_worker_dispatch_claims_once_and_persists_result():
    job_id = queue.create_job("dispatch")
    future = queue.submit_to_queue(lambda current: queue.update_job(current, status="completed", result="done"), job_id)
    assert future is not None
    future.result(timeout=3)
    assert queue.get_job(job_id)["status"] == "completed"
    assert queue.get_job(job_id)["result"] == "done"


def test_generic_dispatch_does_not_reclaim_awaiting_input_or_run_duplicate_analysis():
    job_id = queue.create_job("analysis should run once", idempotency_key="analysis-key")
    entered = threading.Event()
    release = threading.Event()
    calls = []

    def analyze(current):
        calls.append(current)
        entered.set()
        assert release.wait(timeout=3)
        queue.update_job(current, status="awaiting_input", step="Choose a clip")

    first = queue.submit_to_queue(analyze, job_id)
    assert first is not None
    assert entered.wait(timeout=3)
    duplicate = queue.create_job("duplicate analysis", idempotency_key="analysis-key")
    assert duplicate == job_id
    second = queue.submit_to_queue(analyze, duplicate)
    assert second is not None
    release.set()
    first.result(timeout=3)
    second.result(timeout=3)

    assert calls == [job_id]
    assert queue.get_job(job_id)["status"] == "awaiting_input"

    # Reusing the generic entry point cannot trigger another provider call.
    generic_retry = queue.submit_to_queue(analyze, job_id)
    assert generic_retry is not None
    generic_retry.result(timeout=3)
    assert calls == [job_id]
    assert queue.get_job(job_id)["status"] == "awaiting_input"


def test_explicit_followup_dispatch_claims_awaiting_input_once():
    job_id = queue.create_job("selected render")
    queue.update_job(job_id, status="awaiting_input")
    entered = threading.Event()
    release = threading.Event()
    calls = []

    def render(current):
        calls.append(current)
        entered.set()
        assert release.wait(timeout=3)
        queue.update_job(current, status="completed", result="rendered")

    first = queue.submit_awaiting_input_to_queue(render, job_id)
    assert first is not None
    assert entered.wait(timeout=3)
    duplicate = queue.submit_awaiting_input_to_queue(render, job_id)
    assert duplicate is not None
    release.set()
    first.result(timeout=3)
    duplicate.result(timeout=3)

    assert calls == [job_id]
    assert queue.get_job(job_id)["status"] == "completed"
    assert queue.get_job(job_id)["result"] == "rendered"


def test_worker_dispatch_propagates_job_log_context():
    job_id = queue.create_job("context propagation")

    def worker(current_job_id):
        logging.getLogger("test-job-context").info("worker context log")
        queue.update_job(current_job_id, status="completed")

    queue.submit_to_queue(worker, job_id).result(timeout=3)
    assert queue.get_job(job_id)["logs"] == ["worker context log"]


def test_queue_rejects_work_when_inflight_limit_is_reached(monkeypatch):
    job_id = queue.create_job("full queue")
    monkeypatch.setattr(queue._inflight, "acquire", lambda blocking=False: False)

    with pytest.raises(RuntimeError, match="queue is full"):
        queue.submit_to_queue(lambda: None, job_id)
    assert queue.get_job(job_id)["status"] == "queued"


def test_run_process_returns_output_and_check_failure():
    result = run_process([sys.executable, "-c", "print('ready')"], text=True)
    assert result.stdout.strip() == "ready"

    with pytest.raises(subprocess.CalledProcessError):
        run_process([sys.executable, "-c", "raise SystemExit(4)"])

    with pytest.raises(FileNotFoundError):
        run_process(["/definitely/not/a/real/program"])


def test_run_process_cancellation_stops_only_its_child():
    stop_event = threading.Event()
    outcome = []

    def run():
        try:
            run_process([
                sys.executable,
                "-c",
                "import time; print('started', flush=True); time.sleep(30)",
            ], stop_event=stop_event, poll_interval=0.02, terminate_grace_period=0.5)
        except BaseException as exc:  # capture worker outcome for the test thread
            outcome.append(exc)

    thread = threading.Thread(target=run)
    thread.start()
    time.sleep(0.15)
    stop_event.set()
    thread.join(timeout=3)

    assert not thread.is_alive()
    assert len(outcome) == 1
    assert isinstance(outcome[0], ProcessCancelledError)
    captured = outcome[0].output or ""
    if isinstance(captured, bytes):
        captured = captured.decode(errors="replace")
    assert "started" in captured


def test_run_process_timeout_raises_timeout_expired():
    with pytest.raises(subprocess.TimeoutExpired):
        run_process([sys.executable, "-c", "import time; time.sleep(30)"], timeout=0.1)

