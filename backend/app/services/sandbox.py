"""Sandboxed code execution.

Runs model-written Python inside a locked-down Docker container. The container
is the security boundary: the code being run was written by a language model
from a user's prompt, so it is treated as hostile input throughout.

What the container is denied, and why each matters:

    --network=none          No sockets at all. Doubly important here: the
                            workbench is air-gapped, and executed code must
                            not become the hole in that.
    --cap-drop ALL          No Linux capabilities. Nothing to escalate with.
    --security-opt          setuid binaries cannot raise privileges, so a
      no-new-privileges     root-owned binary in the image is not a ladder.
    --read-only             Root filesystem is immutable; the image cannot be
                            modified for a later run.
    tmpfs /tmp              A small writable scratch area, mounted noexec so
                            code cannot write a payload and execute it.
    --memory 256m           A fork bomb or runaway allocation hits a wall.
    --pids-limit 50         Caps process creation.
    user 65534 (nobody)     Unprivileged even inside the container.

Executions are logged as metadata only — a hash of the code, never the code
or its output. The log would otherwise become a transcript of arbitrary
model-written content and arbitrary program output on disk, which is a liability
rather than an audit trail.
"""

from __future__ import annotations

import hashlib
import time
from typing import Any, Final

import docker
from docker.errors import DockerException, ImageNotFound, NotFound
from docker.types import LogConfig
from requests.exceptions import ConnectionError as RequestsConnectionError
from requests.exceptions import ReadTimeout

from app.core.logs import get_file_logger

log = get_file_logger("drishti.sandbox", "sandbox.log")

IMAGE: Final = "drishti-sandbox:latest"
BUILD_HINT: Final = (
    f"Build it with: docker build -f Dockerfile.sandbox -t {IMAGE} ."
)

# Output beyond this is truncated. The container's log driver is capped too,
# so a runaway print loop cannot fill the host disk before the timeout fires.
MAX_OUTPUT_CHARS: Final = 10_000

_client: docker.DockerClient | None = None


class SandboxError(RuntimeError):
    """The sandbox could not run — a problem with the sandbox, not the code."""


def _docker() -> docker.DockerClient:
    """The Docker client, connected on first use.

    Connection is lazy so that importing this module — which happens at
    application start-up — does not require a running Docker daemon. Only
    actually executing code does.
    """
    global _client
    if _client is None:
        try:
            _client = docker.from_env()
            _client.ping()
        except DockerException as exc:
            _client = None
            raise SandboxError(
                f"Cannot reach the Docker daemon: {exc}. Is Docker running?"
            ) from exc
    return _client


def _truncate(raw: bytes) -> str:
    text = raw.decode("utf-8", errors="replace")
    if len(text) <= MAX_OUTPUT_CHARS:
        return text
    return text[:MAX_OUTPUT_CHARS] + f"\n… truncated at {MAX_OUTPUT_CHARS} characters"


def execute_code(
    code: str,
    timeout_seconds: int = 10,
    *,
    user_id: str | None = None,
    thread_id: str | None = None,
) -> dict[str, Any]:
    """Run `code` in the sandbox and return what it produced.

    Returns {"stdout", "stderr", "exit_code", "timed_out"}. A crash in the
    executed code is a normal result reported through exit_code, not an
    exception — the caller wants to see the traceback. SandboxError is raised
    only when the sandbox itself is unavailable.

    `user_id`/`thread_id` are optional and only used to attribute the audit
    trail entry below; every direct call in tests and scripts (which have
    neither) keeps working exactly as before.
    """
    client = _docker()
    digest = hashlib.sha256(code.encode("utf-8")).hexdigest()[:16]
    started = time.monotonic()

    container = None
    timed_out = False
    try:
        try:
            container = client.containers.create(
                IMAGE,
                command=["python3", "-c", code],
                network_mode="none",
                cap_drop=["ALL"],
                security_opt=["no-new-privileges"],
                read_only=True,
                # noexec stops code writing a binary here and running it;
                # nosuid and nodev remove the other two classic tmpfs tricks.
                tmpfs={"/tmp": "rw,size=64m,mode=1777,noexec,nosuid,nodev"},
                mem_limit="256m",
                pids_limit=50,
                user="65534:65534",
                working_dir="/tmp",
                environment={
                    "HOME": "/tmp",
                    "PYTHONDONTWRITEBYTECODE": "1",
                    "PYTHONUNBUFFERED": "1",
                },
                network_disabled=True,
                stdin_open=False,
                # Bounds what the log driver will hold, independently of the
                # truncation applied when reading it back.
                log_config=LogConfig(
                    type="json-file", config={"max-size": "1m", "max-file": "1"}
                ),
                detach=True,
            )
        except ImageNotFound as exc:
            raise SandboxError(f"Sandbox image '{IMAGE}' is missing. {BUILD_HINT}") from exc

        container.start()

        try:
            status = container.wait(timeout=timeout_seconds)
            exit_code = int(status.get("StatusCode", -1))
        except (ReadTimeout, RequestsConnectionError):
            # wait() timed out. Kill the container; whatever it printed before
            # being stopped is still readable from the log driver.
            timed_out = True
            exit_code = -1
            try:
                container.kill()
            except (DockerException, NotFound):
                pass

        stdout = _truncate(container.logs(stdout=True, stderr=False))
        stderr = _truncate(container.logs(stdout=False, stderr=True))

    except SandboxError:
        raise
    except DockerException as exc:
        raise SandboxError(f"Sandbox execution failed: {exc}") from exc
    finally:
        if container is not None:
            try:
                container.remove(force=True)
            except (DockerException, NotFound):
                # A container that cannot be removed is a housekeeping problem,
                # not a reason to lose the result the caller is waiting for.
                pass

    duration = time.monotonic() - started

    # Metadata only. Never the code, never the output.
    log.info(
        "sha256=%s | exit_code=%s | timed_out=%s | duration=%.3fs "
        "| stdout_bytes=%d | stderr_bytes=%d",
        digest, exit_code, timed_out, duration, len(stdout), len(stderr),
    )

    try:
        from app.services.audit_service import record_event

        record_event(
            "sandbox_execution",
            user_id or "demo_user",
            f"code {digest} -> exit={exit_code} timed_out={timed_out} "
            f"({duration:.2f}s)",
            thread_id=thread_id,
            source_component="sandbox.py",
        )
    except Exception as exc:
        log.warning("audit recording failed: %s", exc)

    return {
        "stdout": stdout,
        "stderr": stderr,
        "exit_code": exit_code,
        "timed_out": timed_out,
    }
