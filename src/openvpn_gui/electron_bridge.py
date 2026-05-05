from __future__ import annotations

import argparse
import json
import sys
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any

from .controller import (
    ControllerError,
    delete_profile_files,
    existing_saved_auth,
    existing_saved_secret,
    profile_status,
    start_profile,
    stop_profile,
    write_auth_file,
    write_secret_file,
)
from .importer import import_profile
from .network_checks import PingResult, ping_targets
from .profiles import Profile, ProfileStore


class BridgeError(RuntimeError):
    pass


def _read_payload() -> dict[str, Any]:
    raw = sys.stdin.read().strip()
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise BridgeError(f"Invalid JSON payload: {exc}") from exc
    if not isinstance(payload, dict):
        raise BridgeError("JSON payload must be an object.")
    return payload


def _write_response(ok: bool, payload: dict[str, Any]) -> int:
    key = "data" if ok else "error"
    print(json.dumps({"ok": ok, key: payload}, ensure_ascii=False))
    return 0 if ok else 1


def _profile_to_dict(profile: Profile) -> dict[str, Any]:
    return {
        "id": profile.id,
        "name": profile.name,
        "configPath": profile.config_path,
        "sourcePath": profile.source_path,
        "importedAt": profile.imported_at,
        "needsCredentials": profile.needs_credentials,
        "needsSecret": profile.needs_secret,
        "hasSavedAuth": existing_saved_auth(profile) is not None,
        "hasSavedSecret": existing_saved_secret(profile) is not None,
    }


def _status_to_dict(profile: Profile) -> dict[str, Any]:
    status = profile_status(profile)
    return {
        "running": status.running,
        "pid": status.pid,
        "state": status.state,
        "logTail": status.log_tail,
    }


def _ping_to_dict(result: PingResult) -> dict[str, Any]:
    checked_at = result.checked_at
    if isinstance(checked_at, datetime):
        checked = checked_at.isoformat()
    else:
        checked = str(checked_at)
    return {
        "target": result.target,
        "ok": result.ok,
        "latencyMs": result.latency_ms,
        "checkedAt": checked,
        "message": result.message,
    }


def _selected_profile(payload: dict[str, Any], store: ProfileStore) -> Profile:
    profile_id = str(payload.get("profileId") or "")
    if not profile_id:
        raise BridgeError("profileId is required.")
    profile = store.get(profile_id)
    if profile is None:
        raise BridgeError("Profile was not found.")
    return profile


def list_profiles(_payload: dict[str, Any]) -> dict[str, Any]:
    store = ProfileStore()
    return {"profiles": [_profile_to_dict(profile) for profile in store.profiles]}


def import_selected_profile(payload: dict[str, Any]) -> dict[str, Any]:
    source_path = payload.get("path")
    if not isinstance(source_path, str) or not source_path:
        raise BridgeError("path is required.")

    display_name = payload.get("displayName")
    if display_name is not None and not isinstance(display_name, str):
        raise BridgeError("displayName must be a string.")

    profile = import_profile(Path(source_path), display_name=display_name)
    store = ProfileStore()
    store.add(profile)
    return {"profile": _profile_to_dict(profile), "profiles": [_profile_to_dict(item) for item in store.profiles]}


def get_profile_status(payload: dict[str, Any]) -> dict[str, Any]:
    store = ProfileStore()
    profile = _selected_profile(payload, store)
    return {"status": _status_to_dict(profile)}


def start_selected_profile(payload: dict[str, Any]) -> dict[str, Any]:
    store = ProfileStore()
    profile = _selected_profile(payload, store)
    credentials = payload.get("credentials") or {}
    if not isinstance(credentials, dict):
        raise BridgeError("credentials must be an object.")

    auth_path = existing_saved_auth(profile)
    secret_path = existing_saved_secret(profile)
    save = bool(credentials.get("save", False))

    username = str(credentials.get("username") or "")
    password = str(credentials.get("password") or "")
    secret = str(credentials.get("secret") or "")

    if username or password:
        if not username or not password:
            return {"needsCredentials": True, "missing": ["username", "password"]}
        auth_path = write_auth_file(profile, username, password, save)

    if secret:
        secret_path = write_secret_file(profile, secret, save)

    missing: list[str] = []
    if profile.needs_credentials and auth_path is None:
        missing.extend(["username", "password"])
    if profile.needs_secret and secret_path is None:
        missing.append("secret")
    if missing:
        return {"needsCredentials": True, "missing": missing}

    message = start_profile(profile, auth_path, secret_path)
    store.load()
    refreshed = store.get(profile.id) or profile
    return {
        "message": message,
        "profile": _profile_to_dict(refreshed),
        "status": _status_to_dict(refreshed),
    }


def stop_selected_profile(payload: dict[str, Any]) -> dict[str, Any]:
    store = ProfileStore()
    profile = _selected_profile(payload, store)
    message = stop_profile(profile)
    return {"message": message, "status": _status_to_dict(profile)}


def delete_selected_profile(payload: dict[str, Any]) -> dict[str, Any]:
    store = ProfileStore()
    profile = _selected_profile(payload, store)
    status = profile_status(profile)
    if status.running:
        raise BridgeError("Disconnect this profile before deleting it.")

    delete_profile_files(profile)
    store.remove(profile.id)
    return {"profiles": [_profile_to_dict(item) for item in store.profiles]}


def run_connectivity_checks(_payload: dict[str, Any]) -> dict[str, Any]:
    return {"checks": [_ping_to_dict(result) for result in ping_targets()]}


COMMANDS = {
    "list-profiles": list_profiles,
    "import-profile": import_selected_profile,
    "status": get_profile_status,
    "start": start_selected_profile,
    "stop": stop_selected_profile,
    "delete": delete_selected_profile,
    "checks": run_connectivity_checks,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="OpenVPN GUI Electron JSON bridge")
    parser.add_argument("command", choices=sorted(COMMANDS))
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args(argv)

    try:
        payload = _read_payload()
        result = COMMANDS[args.command](payload)
        return _write_response(True, result)
    except (BridgeError, ControllerError, OSError, ValueError) as exc:
        error: dict[str, Any] = {"message": str(exc)}
        if args.debug:
            error["traceback"] = traceback.format_exc()
        return _write_response(False, error)


if __name__ == "__main__":
    raise SystemExit(main())
