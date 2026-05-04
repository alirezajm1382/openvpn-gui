from __future__ import annotations

import os
from pathlib import Path


APP_ID = "openvpn-gui"


def config_home() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME")
    if base:
        return Path(base)
    return Path.home() / ".config"


def runtime_home(uid: int | None = None) -> Path:
    if uid is not None:
        return Path("/run/user") / str(uid) / APP_ID

    base = os.environ.get("XDG_RUNTIME_DIR")
    if base:
        return Path(base) / APP_ID
    return Path("/run/user") / str(os.getuid()) / APP_ID


def profile_runtime_dir(profile_id: str, uid: int | None = None) -> Path:
    return runtime_home(uid) / profile_id


def profile_pid_file(profile_id: str, uid: int | None = None) -> Path:
    return profile_runtime_dir(profile_id, uid) / "openvpn.pid"


def profile_log_file(profile_id: str, uid: int | None = None) -> Path:
    return profile_runtime_dir(profile_id, uid) / "openvpn.log"


def profile_status_file(profile_id: str, uid: int | None = None) -> Path:
    return profile_runtime_dir(profile_id, uid) / "status.log"


def profile_openvpn3_session_file(profile_id: str, uid: int | None = None) -> Path:
    return profile_runtime_dir(profile_id, uid) / "openvpn3-session.txt"


def app_config_dir() -> Path:
    return config_home() / APP_ID


def profiles_dir() -> Path:
    return app_config_dir() / "profiles"


def metadata_file() -> Path:
    return app_config_dir() / "profiles.json"


def ensure_user_dirs() -> None:
    app_config_dir().mkdir(mode=0o700, parents=True, exist_ok=True)
    profiles_dir().mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        runtime_home().mkdir(mode=0o700, parents=True, exist_ok=True)
    except OSError:
        # The privileged helper recreates runtime paths when a desktop session
        # exists. Avoid failing startup in terminals without XDG_RUNTIME_DIR.
        pass


def installed_helper_path() -> Path:
    return Path("/usr/lib/openvpn-gui/openvpn-gui-helper")


def source_helper_path() -> Path:
    return Path(__file__).resolve().parents[2] / "scripts" / "openvpn-gui-helper"


def helper_path() -> Path:
    explicit = os.environ.get("OPENVPN_GUI_HELPER")
    if explicit:
        return Path(explicit)

    source = source_helper_path()
    if source.exists():
        return source

    return installed_helper_path()
