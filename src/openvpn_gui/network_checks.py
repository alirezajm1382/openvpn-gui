from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime


DEFAULT_TARGETS = (
    "vercel.com",
    "google.com",
    "github.com",
    "api.github.com",
    "registry.npmjs.org",
)

PING_TIME_RE = re.compile(r"time[=<]([0-9.]+)\s*ms")


@dataclass
class PingResult:
    target: str
    ok: bool
    latency_ms: float | None
    checked_at: datetime
    message: str


def _last_output_line(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return lines[-1] if lines else ""


def ping_target(target: str, timeout_seconds: int = 2) -> PingResult:
    checked_at = datetime.now()
    ping = shutil.which("ping")
    if not ping:
        return PingResult(target, False, None, checked_at, "ping not installed")

    command = [
        ping,
        "-n",
        "-c",
        "1",
        "-W",
        str(timeout_seconds),
        target,
    ]
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds + 2,
        )
    except subprocess.TimeoutExpired:
        return PingResult(target, False, None, checked_at, "timeout")
    except OSError as exc:
        return PingResult(target, False, None, checked_at, str(exc))

    output = f"{result.stdout}\n{result.stderr}"
    latency = None
    match = PING_TIME_RE.search(output)
    if match:
        latency = float(match.group(1))

    if result.returncode == 0:
        message = f"{latency:.1f} ms" if latency is not None else "ok"
        return PingResult(target, True, latency, checked_at, message)

    message = _last_output_line(result.stderr) or _last_output_line(result.stdout) or "failed"
    return PingResult(target, False, latency, checked_at, message)


def ping_targets(targets: tuple[str, ...] = DEFAULT_TARGETS) -> list[PingResult]:
    return [ping_target(target) for target in targets]
