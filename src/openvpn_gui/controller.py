from __future__ import annotations

import errno
import os
import re
import shlex
import shutil
import signal
import subprocess
from dataclasses import dataclass
from pathlib import Path

from . import paths
from .profiles import Profile


@dataclass
class ConnectionStatus:
    running: bool
    pid: int | None = None
    state: str = "Disconnected"
    log_tail: str = ""


class ControllerError(RuntimeError):
    pass


SESSION_PATH_RE = re.compile(r"Session path:\s*(\S+)")


def openvpn3_available() -> bool:
    return shutil.which("openvpn3") is not None


def _read_pid(profile_id: str) -> int | None:
    pid_file = paths.profile_pid_file(profile_id)
    try:
        return int(pid_file.read_text(encoding="utf-8").strip())
    except (FileNotFoundError, ValueError):
        return None


def _process_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True
    except ProcessLookupError:
        return False


def _process_matches_profile(pid: int, profile: Profile) -> bool:
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
    except FileNotFoundError:
        return False
    except PermissionError:
        return _process_exists(pid)

    parts = [part.decode("utf-8", errors="replace") for part in raw.split(b"\0") if part]
    if not parts or Path(parts[0]).name != "openvpn":
        return False

    config = str(profile.path.resolve())
    return config in [str(Path(item).resolve()) if item.startswith("/") else item for item in parts]


def _read_tail(path: Path, limit: int = 12000) -> str:
    try:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(size - limit, 0))
            return handle.read().decode("utf-8", errors="replace")
    except FileNotFoundError:
        return ""


def _write_runtime_text(path: Path, text: str, mode: int = 0o600) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    path.chmod(mode)


def _format_command(command: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in command)


def _format_process_failure(
    title: str,
    command: list[str],
    result: subprocess.CompletedProcess[str],
    extra: str = "",
) -> str:
    parts = [
        title,
        f"Exit code: {result.returncode}",
        f"Command: {_format_command(command)}",
    ]
    if result.stdout.strip():
        parts.append(f"stdout:\n{result.stdout.strip()}")
    if result.stderr.strip():
        parts.append(f"stderr:\n{result.stderr.strip()}")
    if extra.strip():
        parts.append(f"details:\n{extra.strip()}")
    return "\n\n".join(parts)


def _read_openvpn3_session_path(profile: Profile) -> str | None:
    try:
        value = paths.profile_openvpn3_session_file(profile.id).read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None
    return value or None


def _write_openvpn3_session_path(profile: Profile, session_path: str) -> None:
    _write_runtime_text(paths.profile_openvpn3_session_file(profile.id), f"{session_path}\n")


def _clear_openvpn3_session_path(profile: Profile) -> None:
    try:
        paths.profile_openvpn3_session_file(profile.id).unlink()
    except FileNotFoundError:
        pass


def _extract_openvpn3_session_path(output: str) -> str | None:
    match = SESSION_PATH_RE.search(output)
    return match.group(1) if match else None


def _run_openvpn3(
    args: list[str],
    input_text: str | None = None,
    timeout: int = 60,
) -> subprocess.CompletedProcess[str]:
    command = ["openvpn3", *args]
    return subprocess.run(
        command,
        input=input_text,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _auth_input(auth_path: Path | None, secret_path: Path | None) -> str | None:
    lines: list[str] = []
    if auth_path:
        try:
            auth_lines = auth_path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            raise ControllerError(f"Could not read credential file: {exc}") from exc
        lines.extend(auth_lines[:2])
    if secret_path:
        try:
            secret = secret_path.read_text(encoding="utf-8").splitlines()[0]
        except IndexError as exc:
            raise ControllerError("Secret key file is empty.") from exc
        except OSError as exc:
            raise ControllerError(f"Could not read secret key file: {exc}") from exc
        lines.append(secret)
    return "\n".join(lines) + "\n" if lines else None


def _openvpn3_status(profile: Profile, session_path: str) -> ConnectionStatus:
    command = ["sessions-list"]
    try:
        result = _run_openvpn3(command, timeout=15)
    except subprocess.TimeoutExpired:
        log_tail = _read_tail(paths.profile_log_file(profile.id))
        return ConnectionStatus(False, state="OpenVPN 3 status timed out", log_tail=log_tail)

    output = f"{result.stdout}\n{result.stderr}".strip()
    if result.returncode != 0:
        if output:
            _write_runtime_text(paths.profile_log_file(profile.id), output + "\n")
        return ConnectionStatus(False, state="OpenVPN 3 unavailable", log_tail=output)

    log_tail = _read_tail(paths.profile_log_file(profile.id))
    if session_path in result.stdout:
        return ConnectionStatus(True, state="Connected", log_tail=log_tail or result.stdout)

    _clear_openvpn3_session_path(profile)
    return ConnectionStatus(False, state="Disconnected", log_tail=log_tail or result.stdout)


def _derive_state(profile_id: str, running: bool, log_tail: str) -> str:
    status_text = _read_tail(paths.profile_status_file(profile_id), limit=8000)
    combined = f"{status_text}\n{log_tail}".lower()

    if "initialization sequence completed" in combined:
        return "Connected"
    if "auth_failed" in combined or "authentication failed" in combined:
        return "Authentication failed"
    if "exiting due to fatal error" in combined:
        return "Failed"
    if "tls error" in combined:
        return "TLS error"
    if running:
        return "Connecting"
    return "Disconnected"


def profile_status(profile: Profile) -> ConnectionStatus:
    openvpn3_session = _read_openvpn3_session_path(profile)
    if openvpn3_session and openvpn3_available():
        return _openvpn3_status(profile, openvpn3_session)

    pid = _read_pid(profile.id)
    running = bool(pid and _process_matches_profile(pid, profile))
    log_tail = _read_tail(paths.profile_log_file(profile.id))
    return ConnectionStatus(
        running=running,
        pid=pid if running else None,
        state=_derive_state(profile.id, running, log_tail),
        log_tail=log_tail,
    )


def write_auth_file(profile: Profile, username: str, password: str, save: bool) -> Path:
    target = profile.auth_file if save else profile.runtime_auth_file
    target.write_text(f"{username}\n{password}\n", encoding="utf-8")
    target.chmod(0o600)
    return target


def write_secret_file(profile: Profile, secret: str, save: bool) -> Path:
    target = profile.secret_file if save else profile.runtime_secret_file
    target.write_text(f"{secret}\n", encoding="utf-8")
    target.chmod(0o600)
    return target


def clear_runtime_auth(profile: Profile) -> None:
    try:
        profile.runtime_auth_file.unlink()
    except FileNotFoundError:
        pass


def clear_runtime_secret(profile: Profile) -> None:
    try:
        profile.runtime_secret_file.unlink()
    except FileNotFoundError:
        pass


def existing_saved_auth(profile: Profile) -> Path | None:
    if profile.auth_file.exists():
        return profile.auth_file
    return None


def existing_saved_secret(profile: Profile) -> Path | None:
    if profile.secret_file.exists():
        return profile.secret_file
    return None


def _run_helper(args: list[str]) -> str:
    pkexec = shutil.which("pkexec")
    if not pkexec:
        raise ControllerError("pkexec is not installed. Install pkexec and polkitd, then try again.")

    command = [pkexec, str(paths.helper_path()), *args]
    try:
        result = subprocess.run(command, check=False, capture_output=True, text=True, timeout=45)
    except subprocess.TimeoutExpired as exc:
        raise ControllerError(
            "The privileged OpenVPN 2 helper did not respond in time.\n\n"
            f"Command: {_format_command(command)}"
        ) from exc

    if result.returncode != 0:
        raise ControllerError(
            _format_process_failure(
                "The privileged OpenVPN 2 helper failed.",
                command,
                result,
            )
        )

    return result.stdout.strip()


def _start_openvpn2_profile(
    profile: Profile,
    auth_path: Path | None = None,
    secret_path: Path | None = None,
) -> str:
    args = ["start", profile.id, str(profile.path)]
    if auth_path:
        args.extend(["--auth", str(auth_path)])
    if secret_path:
        args.extend(["--askpass", str(secret_path)])
    return _run_helper(args)


def _start_openvpn3_profile(
    profile: Profile,
    auth_path: Path | None = None,
    secret_path: Path | None = None,
) -> str:
    command = [
        "session-start",
        "--config",
        str(profile.path),
        "--background",
        "--timeout",
        "45",
    ]
    input_text = _auth_input(auth_path, secret_path)

    try:
        result = _run_openvpn3(command, input_text=input_text, timeout=70)
    except subprocess.TimeoutExpired as exc:
        log_text = _read_tail(paths.profile_log_file(profile.id))
        raise ControllerError(
            "OpenVPN 3 did not finish starting within 70 seconds.\n\n"
            f"Command: openvpn3 {_format_command(command)}\n\n"
            f"Last log output:\n{log_text or 'No log output was captured.'}"
        ) from exc

    output = f"{result.stdout}\n{result.stderr}".strip()
    if output:
        _write_runtime_text(paths.profile_log_file(profile.id), output + "\n")

    if result.returncode != 0:
        raise ControllerError(
            _format_process_failure(
                "OpenVPN 3 exited before the connection could start.",
                ["openvpn3", *command],
                result,
            )
        )

    session_path = _extract_openvpn3_session_path(output)
    if session_path:
        _write_openvpn3_session_path(profile, session_path)
    else:
        sessions = _run_openvpn3(["sessions-list"], timeout=15)
        session_output = f"{sessions.stdout}\n{sessions.stderr}".strip()
        _write_runtime_text(paths.profile_log_file(profile.id), f"{output}\n\n{session_output}\n")
        raise ControllerError(
            _format_process_failure(
                "OpenVPN 3 started but did not report a session path.",
                ["openvpn3", *command],
                result,
                extra=session_output or "No session list output was returned.",
            )
        )

    return output or "started"


def start_profile(
    profile: Profile,
    auth_path: Path | None = None,
    secret_path: Path | None = None,
) -> str:
    if openvpn3_available():
        return _start_openvpn3_profile(profile, auth_path, secret_path)
    return _start_openvpn2_profile(profile, auth_path, secret_path)


def _stop_openvpn2_profile(profile: Profile) -> str:
    try:
        return _run_helper(["stop", profile.id])
    finally:
        clear_runtime_auth(profile)
        clear_runtime_secret(profile)


def _stop_openvpn3_profile(profile: Profile, session_path: str) -> str:
    command = ["session-manage", "--session-path", session_path, "--disconnect"]
    try:
        result = _run_openvpn3(command, timeout=45)
    except subprocess.TimeoutExpired as exc:
        raise ControllerError(
            "OpenVPN 3 did not respond to the disconnect request within 45 seconds.\n\n"
            f"Command: openvpn3 {_format_command(command)}"
        ) from exc

    output = f"{result.stdout}\n{result.stderr}".strip()
    if output:
        _write_runtime_text(paths.profile_log_file(profile.id), output + "\n")
    if result.returncode != 0:
        raise ControllerError(
            _format_process_failure(
                "OpenVPN 3 could not disconnect this session.",
                ["openvpn3", *command],
                result,
            )
        )

    _clear_openvpn3_session_path(profile)
    clear_runtime_auth(profile)
    clear_runtime_secret(profile)
    return output or "stopped"


def stop_profile(profile: Profile) -> str:
    session_path = _read_openvpn3_session_path(profile)
    if session_path and openvpn3_available():
        return _stop_openvpn3_profile(profile, session_path)
    return _stop_openvpn2_profile(profile)


def delete_profile_files(profile: Profile) -> None:
    target = profile.directory
    base = paths.profiles_dir().resolve()
    resolved = target.resolve()
    try:
        resolved.relative_to(base)
    except ValueError as exc:
        raise ControllerError("Refusing to delete a profile outside the app directory.") from exc

    for root, dirs, files in os.walk(resolved, topdown=False):
        for filename in files:
            Path(root, filename).unlink()
        for dirname in dirs:
            Path(root, dirname).rmdir()
    resolved.rmdir()


def terminate_local_pid(pid: int) -> bool:
    try:
        os.kill(pid, signal.SIGTERM)
        return True
    except OSError as exc:
        return exc.errno == errno.ESRCH
