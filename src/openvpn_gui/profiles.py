from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import paths


@dataclass
class Profile:
    id: str
    name: str
    config_path: str
    source_path: str | None = None
    imported_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    needs_credentials: bool = False
    needs_secret: bool = True

    @property
    def path(self) -> Path:
        return Path(self.config_path)

    @property
    def directory(self) -> Path:
        return self.path.parent

    @property
    def auth_file(self) -> Path:
        return self.directory / "auth.txt"

    @property
    def runtime_auth_file(self) -> Path:
        return self.directory / "runtime-auth.txt"

    @property
    def secret_file(self) -> Path:
        return self.directory / "secret.txt"

    @property
    def runtime_secret_file(self) -> Path:
        return self.directory / "runtime-secret.txt"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "config_path": self.config_path,
            "source_path": self.source_path,
            "imported_at": self.imported_at,
            "needs_credentials": self.needs_credentials,
            "needs_secret": self.needs_secret,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Profile":
        return cls(
            id=str(data["id"]),
            name=str(data["name"]),
            config_path=str(data["config_path"]),
            source_path=data.get("source_path"),
            imported_at=str(data.get("imported_at") or datetime.now(timezone.utc).isoformat()),
            needs_credentials=bool(data.get("needs_credentials", False)),
            needs_secret=bool(data.get("needs_secret", True)),
        )


class ProfileStore:
    def __init__(self) -> None:
        paths.ensure_user_dirs()
        self._profiles: list[Profile] = []
        self.load()

    @property
    def profiles(self) -> list[Profile]:
        return list(self._profiles)

    def load(self) -> None:
        path = paths.metadata_file()
        if not path.exists():
            self._profiles = []
            return

        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)

        self._profiles = [Profile.from_dict(item) for item in data.get("profiles", [])]
        self._profiles.sort(key=lambda profile: profile.name.casefold())

    def save(self) -> None:
        paths.ensure_user_dirs()
        payload = {"profiles": [profile.to_dict() for profile in self._profiles]}
        tmp = paths.metadata_file().with_suffix(".json.tmp")
        with tmp.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
            handle.write("\n")
        tmp.chmod(0o600)
        tmp.replace(paths.metadata_file())

    def add(self, profile: Profile) -> None:
        self._profiles = [item for item in self._profiles if item.id != profile.id]
        self._profiles.append(profile)
        self._profiles.sort(key=lambda item: item.name.casefold())
        self.save()

    def remove(self, profile_id: str) -> None:
        self._profiles = [profile for profile in self._profiles if profile.id != profile_id]
        self.save()

    def get(self, profile_id: str) -> Profile | None:
        return next((profile for profile in self._profiles if profile.id == profile_id), None)
