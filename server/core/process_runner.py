"""Cancellation-aware subprocess helpers for job-owned child processes."""

from __future__ import annotations

import subprocess
import time
from threading import Event
from typing import Any, Sequence


class ProcessCancelledError(subprocess.SubprocessError):
    """Raised after the child process owned by a cancelled job has stopped."""

    def __init__(self, cmd, output=None, stderr=None):
        super().__init__(f"Process cancelled: {cmd!r}")
        self.cmd = cmd
        self.output = output
        self.stderr = stderr


def _stop_process(
    process: subprocess.Popen,
    *,
    cmd: Any,
    output: Any,
    stderr: Any,
    grace_period: float,
) -> None:
    """Stop only this Popen child, escalating to kill after a short grace."""
    if process.poll() is not None:
        return
    try:
        process.terminate()
    except ProcessLookupError:
        pass
    try:
        process.communicate(timeout=max(0.0, grace_period))
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate()


def run_process(
    args: str | Sequence[str],
    *,
    stop_event: Event | None = None,
    timeout: float | None = None,
    poll_interval: float = 0.1,
    terminate_grace_period: float = 2.0,
    check: bool = True,
    capture_output: bool = True,
    text: bool = False,
    encoding: str | None = None,
    errors: str | None = None,
    input: str | bytes | None = None,
    cwd: str | None = None,
    env: dict[str, str] | None = None,
    **popen_kwargs,
) -> subprocess.CompletedProcess:
    """Run one child, honoring cancellation and timeout without global process kills.

    This returns ``CompletedProcess`` and raises the same ``CalledProcessError``
    and ``TimeoutExpired`` exceptions as :func:`subprocess.run`. A cancelled
    child raises :class:`ProcessCancelledError` after it has exited.
    """
    if capture_output:
        if "stdout" in popen_kwargs or "stderr" in popen_kwargs:
            raise ValueError("stdout and stderr arguments may not be used with capture_output")
        stdout = subprocess.PIPE
        stderr = subprocess.PIPE
    else:
        stdout = popen_kwargs.pop("stdout", None)
        stderr = popen_kwargs.pop("stderr", None)
    stdin = popen_kwargs.pop("stdin", None)
    if input is not None:
        if stdin is not None:
            raise ValueError("stdin and input arguments may not both be used")
        stdin = subprocess.PIPE

    process = subprocess.Popen(
        args,
        stdin=stdin,
        stdout=stdout,
        stderr=stderr,
        cwd=cwd,
        env=env,
        text=text,
        encoding=encoding,
        errors=errors,
        **popen_kwargs,
    )
    started = time.monotonic()
    output = None
    stderr_output = None
    while True:
        if stop_event is not None and stop_event.is_set():
            _stop_process(
                process,
                cmd=args,
                output=output,
                stderr=stderr_output,
                grace_period=terminate_grace_period,
            )
            output, stderr_output = process.communicate()
            raise ProcessCancelledError(args, output=output, stderr=stderr_output)

        remaining = None if timeout is None else timeout - (time.monotonic() - started)
        if remaining is not None and remaining <= 0:
            try:
                process.terminate()
            except ProcessLookupError:
                pass
            try:
                process.communicate(timeout=terminate_grace_period)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate()
            raise subprocess.TimeoutExpired(args, timeout, output=output, stderr=stderr_output)

        wait = poll_interval if remaining is None else min(poll_interval, remaining)
        try:
            output, stderr_output = process.communicate(input=input, timeout=max(0.001, wait))
            break
        except subprocess.TimeoutExpired as exc:
            output, stderr_output = exc.output, exc.stderr
            # communicate can be called repeatedly with the same input only if
            # the child has not received it. Popen remembers communication state.
            input = None

    completed = subprocess.CompletedProcess(args, process.returncode, output, stderr_output)
    if check and completed.returncode:
        raise subprocess.CalledProcessError(
            completed.returncode,
            args,
            output=completed.stdout,
            stderr=completed.stderr,
        )
    return completed

