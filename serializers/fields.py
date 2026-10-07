from typing import Annotated
from urllib.parse import urlsplit

from pydantic import AfterValidator, Field


def _check_photo_url(value: str | None) -> str | None:
    # The frontend renders this as an <img src>, so only web URLs are allowed;
    # "" clears the photo like null does
    if value is None or not value.strip():
        return None
    value = value.strip()
    parts = urlsplit(value)
    if parts.scheme not in ("http", "https") or not parts.netloc or len(value) > 2048:
        raise ValueError("photo_url must be an http(s) URL")
    return value


PhotoUrl = Annotated[str | None, AfterValidator(_check_photo_url)]


# Ids in request bodies are PostgreSQL integers; larger values can never match a row
Id = Annotated[int, Field(le=2_147_483_647)]

MAX_SLOTS = 100
MAX_TEAMS = 4
MAX_SLOT_NAME = 50


def _slot_names(value, where: str) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"{where} must be a list of names")
    names = []
    for name in value:
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > MAX_SLOT_NAME:
            raise ValueError(f"each slot name must be 1-{MAX_SLOT_NAME} characters")
        names.append(name.strip())
    return names


def slot_names(layout: dict | None) -> list[str]:
    """Every slot name in a validated layout, in order."""
    layout = layout or {}
    names = list(layout.get("slots", []))
    for team in layout.get("teams", []):
        names += team.get("slots", [])
    return names


def _check_slot_layout(layout: dict | None) -> dict | None:
    # Only two small shapes are accepted, so the stored JSON stays bounded:
    # {"slots": ["GK", "D1"]} or {"teams": [{"name": "A", "slots": ["GK"]}]}
    if layout is None or layout == {}:
        return layout
    if set(layout) - {"slots", "teams"}:
        raise ValueError("slot_layout may only contain 'slots' or 'teams'")
    clean = {}
    if "slots" in layout:
        clean["slots"] = _slot_names(layout["slots"], "slots")
    if "teams" in layout:
        teams = layout["teams"]
        if not isinstance(teams, list) or len(teams) > MAX_TEAMS:
            raise ValueError(f"teams must be a list of at most {MAX_TEAMS} teams")
        clean["teams"] = []
        for team in teams:
            if not isinstance(team, dict) or set(team) - {"name", "slots"}:
                raise ValueError("a team may only contain 'name' and 'slots'")
            name = team.get("name")
            if name is not None and (not isinstance(name, str) or not name.strip() or len(name.strip()) > MAX_SLOT_NAME):
                raise ValueError(f"a team name must be 1-{MAX_SLOT_NAME} characters")
            clean["teams"].append({"name": name.strip() if name else None, "slots": _slot_names(team.get("slots", []), "slots")})
    names = slot_names(clean)
    if len(names) > MAX_SLOTS or len(set(names)) != len(names):
        raise ValueError(f"slot names must be unique, at most {MAX_SLOTS}")
    return clean


SlotLayout = Annotated[dict | None, AfterValidator(_check_slot_layout)]
