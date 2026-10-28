"""Game content: the TOML files in this package, checked into frozen dataclasses at startup. A bad file fails loudly,
naming the file and the table."""

import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from importlib import resources
from types import MappingProxyType
from typing import cast

from vat_born.clock import MINUTES_PER_TICK
from vat_born.world import Direction, ItemKind, PlaceKind


class ContentError(Exception):
    """A content file is malformed."""


@dataclass(frozen=True, slots=True)
class PlaceDef:
    kind: PlaceKind
    name: str  # as it reads mid-sentence: "the vat bay"
    description: str
    water: bool


@dataclass(frozen=True, slots=True)
class ItemDef:
    kind: ItemKind
    name: str  # as it reads after "a" or a number: "a ration bar"
    plural: str
    meal: int  # the hunger eating it answers, in ticks; 0 when it isn't food
    drinks: int  # how many drinks it holds when full; 0 when it holds no water
    search: int  # the points it adds to a search's odds while carried; 0 when it doesn't help


@dataclass(frozen=True, slots=True)
class Finds:
    """What a place kind hides: how many things, drawn per place from COUNT, each drawn from ITEMS."""

    count: Span
    items: tuple[ItemKind, ...]


@dataclass(frozen=True, slots=True)
class PathDef:
    """A path in the home section: one line of home.toml's `paths`, running both ways."""

    origin: PlaceKind
    to: PlaceKind
    direction: Direction
    ticks: int


@dataclass(frozen=True, slots=True)
class Gate:
    """Where worldgen joins a section to what lies beyond it: the corridor runs from PLACE, going DIRECTION."""

    place: PlaceKind
    direction: Direction


@dataclass(frozen=True, slots=True)
class Section:
    """A laid-out section of the map: the places in it and the paths joining them."""

    start: PlaceKind
    places: tuple[PlaceKind, ...]
    paths: tuple[PathDef, ...]
    gate: Gate


@dataclass(frozen=True, slots=True)
class Span:
    """A range of whole numbers, least first, as written in a content pair like [5, 7]."""

    least: int
    most: int


@dataclass(frozen=True, slots=True)
class Corridor:
    """The corridor beyond the gate: one segment per frame of the hull, each walk lasting TICKS."""

    kind: PlaceKind
    segments: Span
    first_frame: int
    frame_step: Span
    ticks: Span


@dataclass(frozen=True, slots=True)
class SideRooms:
    """The rooms off the corridor: up to COUNT of them, each a walk of TICKS from its segment."""

    count: Span
    ticks: int
    kinds: tuple[PlaceKind, ...]


@dataclass(frozen=True, slots=True)
class LowerDeck:
    """The rooms under the ladder: a walk of TICKS between neighbours, running east from the foot of it."""

    ticks: int
    kinds: tuple[PlaceKind, ...]


@dataclass(frozen=True, slots=True)
class Decks:
    """Worldgen's tables for the decks beyond a section's gate."""

    corridor: Corridor
    side_rooms: SideRooms
    lower_deck: LowerDeck


@dataclass(frozen=True, slots=True)
class Content:
    places: Mapping[PlaceKind, PlaceDef]
    home: Section
    decks: Decks
    items: Mapping[ItemKind, ItemDef]
    finds: Mapping[PlaceKind, Finds]

    def place(self, kind: PlaceKind) -> PlaceDef:
        if kind not in self.places:
            raise ContentError(f"places.toml has no [{kind}]")
        return self.places[kind]

    def item(self, kind: ItemKind) -> ItemDef:
        if kind not in self.items:
            raise ContentError(f"items.toml has no [{kind}]")
        return self.items[kind]


def load_content() -> Content:
    places = _places(_read("places.toml"))
    home = _home(_read("home.toml"), places)
    items = _items(_read("items.toml"))
    return Content(
        places=places,
        home=home,
        decks=_decks(_read("decks.toml"), places, home),
        items=items,
        finds=_finds(_read("finds.toml"), places, items),
    )


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
        _only(table, {"name", "description", "water"}, where)
        places[PlaceKind(key)] = PlaceDef(
            PlaceKind(key), _string(table, "name", where), _string(table, "description", where), _water(table, where)
        )
    return MappingProxyType(places)


def _items(data: dict[str, object]) -> Mapping[ItemKind, ItemDef]:
    items: dict[ItemKind, ItemDef] = {}
    for key, value in data.items():
        where = f"items.toml [{key}]"
        table = _table(value, where)
        _only(table, {"name", "plural", "meal", "drinks", "search"}, where)
        items[ItemKind(key)] = ItemDef(
            ItemKind(key),
            _string(table, "name", where),
            _string(table, "plural", where),
            _meal(table, where),
            _optional_whole(table, "drinks", where),
            _optional_whole(table, "search", where),
        )
    return MappingProxyType(items)


def _meal(table: dict[str, object], where: str) -> int:
    """An item's optional `meal`: minutes in, ticks out, 0 when the item isn't food."""
    if "meal" not in table:
        return 0
    minutes = table["meal"]
    if not isinstance(minutes, int) or isinstance(minutes, bool) or minutes <= 0 or minutes % MINUTES_PER_TICK:
        raise ContentError(f"{where}: meal must be a positive number of minutes, a multiple of ten")
    return minutes // MINUTES_PER_TICK


def _optional_whole(table: dict[str, object], key: str, where: str) -> int:
    """An item's optional positive whole number, 0 when the key is absent."""
    if key not in table:
        return 0
    value = table[key]
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ContentError(f"{where}: {key} must be a positive whole number")
    return value


def _finds(
    data: dict[str, object], places: Mapping[PlaceKind, PlaceDef], items: Mapping[ItemKind, ItemDef]
) -> Mapping[PlaceKind, Finds]:
    """finds.toml into `Finds`, keyed by place kind."""
    finds: dict[PlaceKind, Finds] = {}
    for key, value in data.items():
        if PlaceKind(key) not in places:
            raise ContentError(f"finds.toml [{key}]: places.toml has no [{key}]")
        where = f"finds.toml [{key}]"
        table = _table(value, where)
        _only(table, {"count", "items"}, where)
        count = _count_span(_required(table, "count", where), f"{where} count")
        listed = _required(table, "items", where)
        if not isinstance(listed, list) or not listed:
            raise ContentError(f"{where} items: must be a non-empty list of item kinds")
        kinds = tuple(_item_kind(item, items, f"{where} items") for item in cast("list[object]", listed))
        finds[PlaceKind(key)] = Finds(count, kinds)
    return MappingProxyType(finds)


def _item_kind(value: object, items: Mapping[ItemKind, ItemDef], where: str) -> ItemKind:
    if not isinstance(value, str) or not value:
        raise ContentError(f"{where}: must be an item kind")
    kind = ItemKind(value)
    if kind not in items:
        raise ContentError(f"{where}: items.toml has no [{kind}]")
    return kind


def _home(data: dict[str, object], places: Mapping[PlaceKind, PlaceDef]) -> Section:
    """home.toml into a `Section`, checked: the section it describes must be a walkable map."""
    _only(data, {"start", "places", "gate", "paths"}, "home.toml")
    start = _kind(_string(data, "start", "home.toml"), places, "home.toml start")
    listed = _listed(data.get("places"), places)
    if start not in listed:
        raise ContentError("home.toml start: must be one of the places in the section")
    ways = _paths(data.get("paths"), places, listed)
    _no_two_ways_one_direction(ways)
    _reachable(start, listed, ways)
    return Section(start=start, places=listed, paths=ways, gate=_gate(data.get("gate"), listed, ways))


def _gate(value: object, listed: tuple[PlaceKind, ...], ways: tuple[PathDef, ...]) -> Gate:
    """home.toml's `gate`, checked: worldgen hangs the decks off this place, in this direction."""
    where = "home.toml gate"
    table = _table(value, where)
    _only(table, {"place", "direction"}, where)
    place_value = _required(table, "place", where)
    if not isinstance(place_value, str) or place_value not in listed:
        raise ContentError(f"{where} place: must be one of the places in the section")
    place = PlaceKind(place_value)
    direction = _direction(_required(table, "direction", where), f"{where} direction")
    if direction in (Direction.UP, Direction.DOWN):
        raise ContentError(f"{where} direction: the decks don't join a section from above or below")
    leaving = {way.direction for way in ways if way.origin == place} | {
        way.direction.opposite for way in ways if way.to == place
    }
    if direction in leaving:
        raise ContentError(f"{where} direction: a path already leaves {place} {direction}")
    return Gate(place, direction)


def _decks(data: dict[str, object], places: Mapping[PlaceKind, PlaceDef], home: Section) -> Decks:
    """decks.toml into `Decks`, checked: the tables must describe a corridor worldgen can lay out."""
    _only(data, {"corridor", "side_rooms", "lower_deck"}, "decks.toml")
    seen: set[PlaceKind] = set()
    corridor = _corridor(data.get("corridor"), places, home, seen)
    side_rooms = _side_rooms(data.get("side_rooms"), places, home, seen, corridor)
    return Decks(corridor, side_rooms, _lower_deck(data.get("lower_deck"), places, home, seen))


def _corridor(value: object, places: Mapping[PlaceKind, PlaceDef], home: Section, seen: set[PlaceKind]) -> Corridor:
    where = "decks.toml [corridor]"
    table = _table(value, where)
    _only(table, {"kind", "segments", "first_frame", "frame_step", "minutes"}, where)
    kind = _deck_kind(_required(table, "kind", where), places, home, f"{where} kind", seen)
    segments = _span(_required(table, "segments", where), f"{where} segments")
    if segments.least < 2:
        raise ContentError(f"{where} segments: at least 2, since the ladder never goes on the first")
    first_frame = _whole(_required(table, "first_frame", where), f"{where} first_frame")
    if first_frame < 1:
        raise ContentError(f"{where} first_frame: frames count from 1")
    frame_step = _span(_required(table, "frame_step", where), f"{where} frame_step")
    ticks = _minutes_span(_required(table, "minutes", where), f"{where} minutes")
    return Corridor(kind, segments, first_frame, frame_step, ticks)


def _side_rooms(
    value: object, places: Mapping[PlaceKind, PlaceDef], home: Section, seen: set[PlaceKind], corridor: Corridor
) -> SideRooms:
    where = "decks.toml [side_rooms]"
    table = _table(value, where)
    _only(table, {"count", "minutes", "kinds"}, where)
    count = _span(_required(table, "count", where), f"{where} count")
    ticks = _minutes(_required(table, "minutes", where), f"{where} minutes")
    kinds = _deck_kinds(_required(table, "kinds", where), places, home, f"{where} kinds", seen)
    if count.most > len(kinds):
        raise ContentError(f"{where} count: more side rooms at most than there are kinds ({len(kinds)})")
    if count.most > 2 * corridor.segments.least:
        raise ContentError(
            f"{where} count: more side rooms at most than the fewest segments have sides "
            f"({2 * corridor.segments.least})"
        )
    return SideRooms(count, ticks, kinds)


def _lower_deck(value: object, places: Mapping[PlaceKind, PlaceDef], home: Section, seen: set[PlaceKind]) -> LowerDeck:
    where = "decks.toml [lower_deck]"
    table = _table(value, where)
    _only(table, {"minutes", "kinds"}, where)
    ticks = _minutes(_required(table, "minutes", where), f"{where} minutes")
    kinds = _deck_kinds(_required(table, "kinds", where), places, home, f"{where} kinds", seen)
    if not kinds:
        raise ContentError(f"{where} kinds: the lower deck needs at least one room")
    return LowerDeck(ticks, kinds)


def _deck_kinds(
    value: object, places: Mapping[PlaceKind, PlaceDef], home: Section, where: str, seen: set[PlaceKind]
) -> tuple[PlaceKind, ...]:
    if not isinstance(value, list):
        raise ContentError(f"{where}: must be a list of place kinds")
    return tuple(_deck_kind(item, places, home, where, seen) for item in cast("list[object]", value))


def _deck_kind(
    value: object, places: Mapping[PlaceKind, PlaceDef], home: Section, where: str, seen: set[PlaceKind]
) -> PlaceKind:
    kind = _kind(value, places, where)
    if kind in home.places:
        raise ContentError(f"{where}: {kind} is one of the home section's places")
    if kind in seen:
        raise ContentError(f"{where}: {kind} appears twice in decks.toml")
    seen.add(kind)
    return kind


def _span(value: object, where: str) -> Span:
    pair = cast("list[object]", value) if isinstance(value, list) else None
    if pair is None or len(pair) != 2:
        raise ContentError(f"{where}: must be a pair like [5, 7]")
    least, most = (_whole(item, where) for item in pair)
    if least < 1 or least > most:
        raise ContentError(f"{where}: must be two whole numbers, least first, from 1 up")
    return Span(least, most)


def _count_span(value: object, where: str) -> Span:
    """A span of counts, which alone among the content ranges may start at 0: a place can hide nothing."""
    pair = cast("list[object]", value) if isinstance(value, list) else None
    if pair is None or len(pair) != 2:
        raise ContentError(f"{where}: must be a pair like [0, 2]")
    least, most = (_whole(item, where) for item in pair)
    if least < 0 or least > most:
        raise ContentError(f"{where}: must be two whole numbers, least first, from 0 up")
    return Span(least, most)


def _whole(value: object, where: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ContentError(f"{where}: must be a whole number")
    return value


def _minutes_span(value: object, where: str) -> Span:
    """A pair like [10, 30], as minutes in and a `Span` of ticks out."""
    pair = cast("list[object]", value) if isinstance(value, list) else None
    if pair is None or len(pair) != 2:
        raise ContentError(f"{where}: must be a pair like [10, 30]")
    span = Span(_minutes(pair[0], where), _minutes(pair[1], where))
    if span.least > span.most:
        raise ContentError(f"{where}: must be two minute counts, least first")
    return span


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


def _water(table: dict[str, object], where: str) -> bool:
    """A place's optional `water` flag: false when absent, so only places with something to drink say so."""
    value = table.get("water", False)
    if not isinstance(value, bool):
        raise ContentError(f"{where}: water must be true or false")
    return value


def _only(table: dict[str, object], keys: set[str], where: str) -> None:
    unknown = sorted(set(table) - keys)
    if unknown:
        raise ContentError(f"{where}: unknown keys {', '.join(unknown)}")
