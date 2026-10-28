"""Game content: the TOML files in this package, checked into frozen dataclasses at startup. A bad file fails loudly,
naming the file and the table."""

import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from importlib import resources
from types import MappingProxyType
from typing import cast

from vat_born.world import PlaceKind


class ContentError(Exception):
    """A content file is malformed."""


@dataclass(frozen=True, slots=True)
class PlaceDef:
    kind: PlaceKind
    name: str  # as it reads mid-sentence: "the vat bay"


@dataclass(frozen=True, slots=True)
class Content:
    places: Mapping[PlaceKind, PlaceDef]

    def place(self, kind: PlaceKind) -> PlaceDef:
        if kind not in self.places:
            raise ContentError(f"places.toml has no [{kind}]")
        return self.places[kind]


def load_content() -> Content:
    return Content(places=_places(_read("places.toml")))


def _read(name: str) -> dict[str, object]:
    text = resources.files(__name__).joinpath(name).read_text(encoding="utf-8")
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise ContentError(f"{name}: {error}") from error
    return cast("dict[str, object]", data)


def _places(data: dict[str, object]) -> Mapping[PlaceKind, PlaceDef]:
    places: dict[PlaceKind, PlaceDef] = {}
    for key, value in data.items():
        where = f"places.toml [{key}]"
        table = _table(value, where)
        _only(table, {"name"}, where)
        places[PlaceKind(key)] = PlaceDef(PlaceKind(key), _string(table, "name", where))
    return MappingProxyType(places)


def _table(value: object, where: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ContentError(f"{where}: expected a table")
    return cast("dict[str, object]", value)


def _string(table: dict[str, object], key: str, where: str) -> str:
    value = table.get(key)
    if not isinstance(value, str) or not value:
        raise ContentError(f"{where}: {key} must be a non-empty string")
    return value


def _only(table: dict[str, object], keys: set[str], where: str) -> None:
    unknown = sorted(set(table) - keys)
    if unknown:
        raise ContentError(f"{where}: unknown keys {', '.join(unknown)}")
