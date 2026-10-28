"""Names for things in the world. IDs are distinct types, so a node can't be passed where a character is expected."""

from dataclasses import dataclass
from enum import StrEnum
from typing import NewType

NodeId = NewType("NodeId", int)
CharacterId = NewType("CharacterId", int)
PlaceKind = NewType("PlaceKind", str)  # a table in content/places.toml


class Layer(StrEnum):
    """The map's zoom layers (design §11). The first build has only the decks."""

    DECKS = "decks"


@dataclass(frozen=True, slots=True)
class Place:
    id: NodeId
    name: str
    description: str
