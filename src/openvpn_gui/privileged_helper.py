from __future__ import annotations

import json
import os
import pwd
import re
import shlex
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

from . import paths


PROFILE_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")


class HelperError(RuntimeError):
    pass


def _caller_uid() -> int:
    for key in ("PKEXEC_UID", "SUDO_UID"):
        value = os.environ.get(key)
        if value:
            return int(value)

    uid = os.getuid()
    if uid == 0:
        raise HelperError("Run this helper through pkexec so the calling user can be verified.")
    return uid


def _caller_info() -> tuple[int, int, Path]:
    uid = _caller_uid()
    info = pwd.getpwuid(uid)
    return uid, info.pw_gid, Path(info.pw_dir)


def _validate_profile_id(profile_id: str) -> str:
    if not PROFILE_ID_RE.fullmatch(profile_id):
        raise HelperError("Invalid profile id.")
    return profile_id


def _validate_profile_path(home: Path, profile_id: str, config_path: str) -> tuple[Path, Path]:
    profile_id = _validate_profile_id(profile_id)
    base = (home / ".config" / paths.APP_ID / "profiles").resolve()
    profile_dir = (base / profile_id).resolve()
    config = Path(config_path).resolve()

    try:
        profile_dir.relative_to(base)
        config.relative_to(profile_dir)
    except ValueError as exc:
        raise HelperError("Refusing to use a profile outside the OpenVPN GUI profile directory.") from exc

    if not config.exists() or not config.is_file() or config.suffix.lower() != ".ovpn":
        raise HelperError("Profile config is missing or is not an .ovpn file.")

    return profile_dir, config


def _validate_profile_local_file(profile_dir: Path, file_path: str | None, label: str) -> Path | None:
    if not file_path:
        return None

    resolved = Path(file_path).resolve()
    try:
        resolved.relative_to(profile_dir)
    except ValueError as exc:
        raise HelperError(f"Refusing to use {label} outside the selected profile directory.") from exc

    if not resolved.exists() or not resolved.is_file():
        raise HelperError(f"{label.title()} file is missing.")

    return resolved


def _parse_start_options(argv: list[str]) -> tuple[str | None, str | None]:
    auth_path: str | None = None
    secret_path: str | None = None
    args = argv[3:]

    if len(args) == 1 and not args[0].startswith("--"):
        return args[0], None

    index = 0
    while index < len(args):
        option = args[index]
        if option not in ("--auth", "--askpass"):
            raise HelperError("Usage: start PROFILE_ID CONFIG_PATH [--auth AUTH_PATH] [--askpass SECRET_PATH]")
        if index + 1 >= len(args):
            raise HelperError(f"{option} requires a path.")
        value = args[index + 1]
        if option == "--auth":
            auth_path = value
        else:
            secret_path = value
        index += 2

    return auth_path, secret_path


def _openvpn_bin() -> str:
    for candidate in (shutil.which("openvpn"), "/usr/sbin/openvpn", "/usr/bin/openvpn"):
        if candidate and Path(candidate).exists():
            return candidate
    raise HelperError("openvpn is not installed.")


def _process_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


def _read_pid(pid_file: Path) -> int | None:
    try:
        return int(pid_file.read_text(encoding="utf-8").strip())
    except (FileNotFoundError, ValueError):
        return None


def _touch_user_file(path: Path, uid: int, gid: int, mode: int = 0o600) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.touch(mode=mode, exist_ok=True)
    os.chown(path, uid, gid)
    path.chmod(mode)


def _prepare_runtime(profile_id: str, uid: int, gid: int) -> tuple[Path, Path, Path]:
    runtime_dir = paths.profile_runtime_dir(profile_id, uid)
    runtime_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chown(runtime_dir, uid, gid)
    runtime_dir.chmod(0o700)

    pid_file = paths.profile_pid_file(profile_id, uid)
    log_file = paths.profile_log_file(profile_id, uid)
    status_file = paths.profile_status_file(profile_id, uid)
    _touch_user_file(pid_file, uid, gid)
    _touch_user_file(log_file, uid, gid)
    _touch_user_file(status_file, uid, gid)
    return pid_file, log_file, status_file


def _read_cmdline(pid: int) -> list[str]:
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
    except FileNotFoundError:
        return []
    return [part.decode("utf-8", errors="replace") for part in raw.split(b"\0") if part]


def _is_expected_openvpn(pid: int, profile_dir: Path | None = None) -> bool:
    cmdline = _read_cmdline(pid)
    if not cmdline:
        return False
    binary = Path(cmdline[0]).name
    if binary != "openvpn":
        return False
    if profile_dir is None:
        return True
    expected_config = str((profile_dir / "config.ovpn").resolve())
    return expected_config in [str(Path(item).resolve()) if item.startswith("/") else item for item in cmdline]


def _tail(path: Path, limit: int = 6000) -> str:
    try:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(size - limit, 0))
            return handle.read().decode("utf-8", errors="replace")
    except FileNotFoundError:
        return ""


def _command_text(command: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in command)


def start(argv: list[str]) -> int:
    if len(argv) < 3:
        raise HelperError("Usage: start PROFILE_ID CONFIG_PATH [--auth AUTH_PATH] [--askpass SECRET_PATH]")

    uid, gid, home = _caller_info()
    profile_id = _validate_profile_id(argv[1])
    profile_dir, config = _validate_profile_path(home, profile_id, argv[2])
    auth_path, secret_path = _parse_start_options(argv)
    auth_file = _validate_profile_local_file(profile_dir, auth_path, "credential")
    secret_file = _validate_profile_local_file(profile_dir, secret_path, "secret key")
    pid_file, log_file, status_file = _prepare_runtime(profile_id, uid, gid)

    existing_pid = _read_pid(pid_file)
    if existing_pid and _process_exists(existing_pid):
        raise HelperError("This profile is already running.")

    pid_file.write_text("", encoding="utf-8")
    log_file.write_text("", encoding="utf-8")
    status_file.write_text("", encoding="utf-8")
    for item in (pid_file, log_file, status_file):
        os.chown(item, uid, gid)
        item.chmod(0o600)

    command = [
        _openvpn_bin(),
        "--config",
        str(config),
        "--writepid",
        str(pid_file),
        "--log-append",
        str(log_file),
        "--status",
        str(status_file),
        "5",
    ]
    if auth_file:
        command.extend(["--auth-user-pass", str(auth_file)])
    if secret_file:
        command.extend(["--askpass", str(secret_file)])

    try:
        process = subprocess.Popen(
            command,
            cwd=str(profile_dir),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as exc:
        raise HelperError(
            "Could not launch OpenVPN 2.\n\n"
            f"Command: {_command_text(command)}\n"
            f"Working directory: {profile_dir}\n"
            f"Error: {exc}"
        ) from exc
    pid_file.write_text(f"{process.pid}\n", encoding="utf-8")
    os.chown(pid_file, uid, gid)
    pid_file.chmod(0o600)

    time.sleep(0.8)
    if process.poll() is not None:
        log_tail = _tail(log_file)
        status_tail = _tail(status_file)
        details = [
            "OpenVPN 2 exited before the connection could start.",
            f"Exit code: {process.returncode}",
            f"Command: {_command_text(command)}",
            f"Working directory: {profile_dir}",
        ]
        if log_tail:
            details.append(f"Log output:\n{log_tail}")
        if status_tail:
            details.append(f"Status output:\n{status_tail}")
        raise HelperError("\n\n".join(details))

    print("started")
    return 0


def stop(argv: list[str]) -> int:
    if len(argv) != 2:
        raise HelperError("Usage: stop PROFILE_ID")

    uid, _gid, home = _caller_info()
    profile_id = _validate_profile_id(argv[1])
    profile_dir = (home / ".config" / paths.APP_ID / "profiles" / profile_id).resolve()
    pid_file = paths.profile_pid_file(profile_id, uid)
    pid = _read_pid(pid_file)
    if not pid:
        print("not running")
        return 0

    if not _process_exists(pid):
        pid_file.unlink(missing_ok=True)
        print("not running")
        return 0

    if not _is_expected_openvpn(pid, profile_dir):
        raise HelperError("Refusing to stop a process that does not look like this OpenVPN profile.")

    os.kill(pid, signal.SIGTERM)
    deadline = time.time() + 12
    while time.time() < deadline:
        if not _process_exists(pid):
            break
        time.sleep(0.25)

    if _process_exists(pid):
        os.kill(pid, signal.SIGKILL)

    pid_file.unlink(missing_ok=True)
    print("stopped")
    return 0


def status(argv: list[str]) -> int:
    if len(argv) != 2:
        raise HelperError("Usage: status PROFILE_ID")

    uid, _gid, _home = _caller_info()
    profile_id = _validate_profile_id(argv[1])
    pid_file = paths.profile_pid_file(profile_id, uid)
    pid = _read_pid(pid_file)
    running = bool(pid and _process_exists(pid) and _is_expected_openvpn(pid))
    print(json.dumps({"running": running, "pid": pid if running else None}))
    return 0


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        if not args:
            raise HelperError("Usage: openvpn-gui-helper start|stop|status ...")
        command = args[0]
        if command == "start":
            return start(args)
        if command == "stop":
            return stop(args)
        if command == "status":
            return status(args)
        raise HelperError(f"Unknown command: {command}")
    except HelperError as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
