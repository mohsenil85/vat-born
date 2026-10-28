"""Game content: the TOML files in this package, checked into frozen dataclasses at startup. A bad file fails loudly,
naming the file and the table."""

import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from importlib import resources
from types import MappingProxyType
from typing import cast

from vat_born.clock import MINUTES_PER_TICK
from vat_born.world import Direction, PlaceKind


class ContentError(Exception):
    """A content file is malformed."""


@dataclass(frozen=True, slots=True)
class PlaceDef:
    kind: PlaceKind
    name: str  # as it reads mid-sentence: "the vat bay"
    description: str


@dataclass(frozen=True, slots=True)
class PathDef:
    """A path in the home section: one line of home.toml's `paths`, running both ways."""

    origin: PlaceKind
    to: PlaceKind
    direction: Direction
    ticks: int


@dataclass(frozen=True, slots=True)
class Section:
    """A laid-out section of the map: the places in it and the paths joining them."""

    start: PlaceKind
    places: tuple[PlaceKind, ...]
    paths: tuple[PathDef, ...]


@dataclass(frozen=True, slots=True)
class Content:
    places: Mapping[PlaceKind, PlaceDef]
    home: Section

    def place(self, kind: PlaceKind) -> PlaceDef:
        if kind not in self.places:
            raise ContentError(f"places.toml has no [{kind}]")
        return self.places[kind]


def load_content() -> Content:
    places = _places(_read("places.toml"))
    return Content(places=places, home=_home(_read("home.toml"), places))


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
        _only(table, {"name", "description"}, where)
        places[PlaceKind(key)] = PlaceDef(
            PlaceKind(key), _string(table, "name", where), _string(table, "description", where)
        )
    return MappingProxyType(places)


def _home(data: dict[str, object], places: Mapping[PlaceKind, PlaceDef]) -> Section:
    """home.toml into a `Section`, checked: the section it describes must be a walkable map."""
    _only(data, {"start", "places", "paths"}, "home.toml")
    start = _kind(_string(data, "start", "home.toml"), places, "home.toml start")
    listed = _listed(data.get("places"), places)
    if start not in listed:
        raise ContentError("home.toml start: must be one of the places in the section")
    ways = _paths(data.get("paths"), places, listed)
    _no_two_ways_one_direction(ways)
    _reachable(start, listed, ways)
    return Section(start, listed, ways)


def _listed(value: object, places: Mapping[PlaceKind, PlaceDef]) -> tuple[PlaceKind, ...]:
    if not isinstance(value, list):
        raise ContentError("home.toml places: must be a list of place kinds")
    listed = [_kind(item, places, "home.toml places") for item in cast("list[object]", value)]
    if len(set(listed)) != len(listed):
        raise ContentError("home.toml places: a place is listed twice")
    return tuple(listed)


def _paths(value: object, places: Mapping[PlaceKind, PlaceDef], listed: tuple[PlaceKind, ...]) -> tuple[PathDef, ...]:
    if not isinstance(value, list):
        raise ContentError("home.toml paths: must be a list of tables")
    ways: list[PathDef] = []
    for i, item in enumerate(cast("list[object]", value), start=1):
        where = f"home.toml [[paths]] {i}"
        table = _table(item, where)
        _only(table, {"from", "to", "direction", "minutes"}, where)
        origin = _kind(_required(table, "from", where), places, f"{where} from")
        to = _kind(_required(table, "to", where), places, f"{where} to")
        if origin == to:
            raise ContentError(f"{where}: joins {origin} to itself")
        if origin not in listed or to not in listed:
            raise ContentError(f"{where}: a path must join two places in the section")
        direction = _direction(_required(table, "direction", where), where)
        minutes = _minutes(_required(table, "minutes", where), where)
        ways.append(PathDef(origin, to, direction, minutes))
    return tuple(ways)


def _required(table: dict[str, object], key: str, where: str) -> object:
    if key not in table:
        raise ContentError(f"{where}: {key} is required")
    return table[key]


def _kind(value: object, places: Mapping[PlaceKind, PlaceDef], where: str) -> PlaceKind:
    if not isinstance(value, str) or not value:
        raise ContentError(f"{where}: must be a place kind")
    kind = PlaceKind(value)
    if kind not in places:
        raise ContentError(f"{where}: places.toml has no [{kind}]")
    return kind


def _direction(value: object, where: str) -> Direction:
    if not isinstance(value, str):
        raise ContentError(f"{where}: direction must be one of the six ways")
    try:
        return Direction(value)
    except ValueError as error:
        raise ContentError(f'{where}: "{value}" is not one of the six ways') from error


def _minutes(value: object, where: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0 or value % MINUTES_PER_TICK:
        raise ContentError(f"{where}: minutes must be a positive multiple of ten")
    return value // MINUTES_PER_TICK


def _no_two_ways_one_direction(ways: tuple[PathDef, ...]) -> None:
    taken: set[tuple[PlaceKind, Direction]] = set()
    for i, way in enumerate(ways, start=1):
        for place, direction in ((way.origin, way.direction), (way.to, way.direction.opposite)):
            if (place, direction) in taken:
                raise ContentError(f"home.toml [[paths]] {i}: {place} already has a path leading {direction}")
            taken.add((place, direction))


def _reachable(start: PlaceKind, listed: tuple[PlaceKind, ...], ways: tuple[PathDef, ...]) -> None:
    """Walk the section from start: a place nothing reaches would strand a clone in it."""
    joins: dict[PlaceKind, set[PlaceKind]] = {kind: set() for kind in listed}
    for way in ways:
        joins[way.origin].add(way.to)
        joins[way.to].add(way.origin)
    seen = {start}
    frontier = [start]
    while frontier:
        for place in joins[frontier.pop()]:
            if place not in seen:
                seen.add(place)
                frontier.append(place)
    unreachable = sorted(kind for kind in listed if kind not in seen)
    if unreachable:
        raise ContentError(f"home.toml: nothing reaches {', '.join(unreachable)} from {start}")


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
