from pathlib import Path

import yaml

REQUIRED_FIELDS = ("name", "title")


class ProfileError(ValueError):
    pass


def load_profile(path: str | Path) -> dict:
    path = Path(path)
    if not path.exists():
        raise ProfileError(f"Profile not found: {path}")
    with path.open() as f:
        data = yaml.safe_load(f) or {}
    missing = [f for f in REQUIRED_FIELDS if f not in data]
    if missing:
        raise ProfileError(f"Profile {path} is missing required fields: {missing}")
    data.setdefault("watchlist", [])
    data.setdefault("skills", [])
    data.setdefault("target_titles", [])
    data.setdefault("locations", [])
    data.setdefault("industries", [])
    return data


def save_profile(path: str | Path, data: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)


def find_watchlist_entry(profile: dict, name: str) -> dict | None:
    for entry in profile.get("watchlist", []):
        if entry.get("name", "").lower() == name.lower():
            return entry
    return None
