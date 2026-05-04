from __future__ import annotations

import os
import re
import secrets
import shlex
import shutil
from pathlib import Path

from . import paths
from .profiles import Profile


PATH_DIRECTIVES = {
    "askpass",
    "auth-user-pass",
    "ca",
    "cert",
    "crl-verify",
    "dh",
    "extra-certs",
    "http-proxy-user-pass",
    "key",
    "pkcs12",
    "secret",
    "tls-auth",
    "tls-crypt",
    "tls-crypt-v2",
    "tls-verify",
}


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", value.strip()).strip("-._")
    return slug[:48] or "profile"


def _quote(value: str) -> str:
    return shlex.quote(value)


def _looks_like_inline_path(value: str) -> bool:
    return value.startswith("[") or value.startswith("<")


def _parse_line(line: str) -> list[str] | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#") or stripped.startswith(";") or stripped.startswith("<"):
        return None
    try:
        return shlex.split(stripped, comments=False, posix=True)
    except ValueError:
        return None


def _resolve_reference(source_config: Path, reference: str) -> Path:
    candidate = Path(os.path.expanduser(reference))
    if not candidate.is_absolute():
        candidate = source_config.parent / candidate
    return candidate.resolve()


def _copy_reference(source: Path, target_dir: Path, used_names: set[str]) -> str:
    name = source.name
    if name in used_names:
        stem = source.stem or "file"
        suffix = source.suffix
        index = 2
        while f"{stem}-{index}{suffix}" in used_names:
            index += 1
        name = f"{stem}-{index}{suffix}"

    target = target_dir / name
    shutil.copy2(source, target)
    target.chmod(0o600)
    used_names.add(name)
    return name


def _rewrite_config(source_config: Path, target_dir: Path) -> tuple[list[str], bool, bool]:
    used_names: set[str] = {"config.ovpn"}
    rewritten: list[str] = []
    needs_credentials = False
    needs_secret = True

    for line in source_config.read_text(encoding="utf-8", errors="replace").splitlines():
        parts = _parse_line(line)
        if not parts:
            rewritten.append(line)
            continue

        directive = parts[0].lower()
        if directive not in PATH_DIRECTIVES or len(parts) < 2:
            if directive == "auth-user-pass":
                needs_credentials = True
            elif directive == "askpass":
                needs_secret = True
            rewritten.append(line)
            continue

        if directive == "askpass":
            needs_secret = True
            rewritten.append("askpass")
            continue

        reference = parts[1]
        if _looks_like_inline_path(reference):
            rewritten.append(line)
            continue

        source_reference = _resolve_reference(source_config, reference)
        if not source_reference.exists() or not source_reference.is_file():
            if directive == "auth-user-pass":
                needs_credentials = True
            rewritten.append(line)
            continue

        copied_name = _copy_reference(source_reference, target_dir, used_names)
        parts[1] = copied_name
        rewritten.append(" ".join(_quote(part) for part in parts))

    return rewritten, needs_credentials, needs_secret


def import_profile(config_path: Path, display_name: str | None = None) -> Profile:
    source = config_path.expanduser().resolve()
    if not source.exists() or not source.is_file():
        raise FileNotFoundError(f"{source} is not a file")
    if source.suffix.lower() != ".ovpn":
        raise ValueError("OpenVPN profiles must use the .ovpn extension")

    profile_name = display_name or source.stem
    profile_id = f"{_slugify(profile_name)}-{secrets.token_hex(4)}"
    target_dir = paths.profiles_dir() / profile_id
    target_dir.mkdir(mode=0o700, parents=True, exist_ok=False)

    rewritten, needs_credentials, needs_secret = _rewrite_config(source, target_dir)
    target_config = target_dir / "config.ovpn"
    target_config.write_text("\n".join(rewritten) + "\n", encoding="utf-8")
    target_config.chmod(0o600)

    return Profile(
        id=profile_id,
        name=profile_name,
        config_path=str(target_config),
        source_path=str(source),
        needs_credentials=needs_credentials,
        needs_secret=needs_secret,
    )
