"""Names for things in the world. IDs are distinct types, so a node can't be passed where a character is expected."""

from dataclasses import dataclass
from enum import StrEnum
from typing import NewType

NodeId = NewType("NodeId", int)
CharacterId = NewType("CharacterId", int)
ItemId = NewType("ItemId", int)
PlaceKind = NewType("PlaceKind", str)  # a table in content/places.toml
ItemKind = NewType("ItemKind", str)  # a table in content/items.toml


class Layer(StrEnum):
    """The map's zoom layers (design §11). The first build has only the decks."""

    DECKS = "decks"


class Direction(StrEnum):
    """The ways a path can run. Definition order is the order paths are listed in."""

    NORTH = "north"
    SOUTH = "south"
    EAST = "east"
    WEST = "west"
    UP = "up"
    DOWN = "down"

    @property
    def opposite(self) -> Direction:
        return _OPPOSITE[self]


_OPPOSITE = {
    Direction.NORTH: Direction.SOUTH,
    Direction.SOUTH: Direction.NORTH,
    Direction.EAST: Direction.WEST,
    Direction.WEST: Direction.EAST,
    Direction.UP: Direction.DOWN,
    Direction.DOWN: Direction.UP,
}


@dataclass(frozen=True, slots=True)
class Place:
    id: NodeId
    name: str
    description: str
    water: bool


@dataclass(frozen=True, slots=True)
class Item:
    """A thing in the world. It starts hidden in a place's search pool, comes into the open when a search turns it
    up, and can then be carried by a character. DRINKS is the water in it now, for the things that hold any."""

    id: ItemId
    kind: ItemKind
    drinks: int


@dataclass(frozen=True, slots=True)
class Exit:
    """A path out of a place: where it leads, how long the walk is, and whether the far end is known ground."""

    direction: Direction
    to: NodeId
    place_name: str
    ticks: int
    explored: bool
