"""What the engine tells frontends.

Facts are changes to the world. `Txn.record` applies a fact and appends it to the event log, and nothing else changes
state, so the log holds every change. Reports answer free actions and point out what a change means; they describe
the world without changing it, so they are never logged."""

from dataclasses import dataclass
from enum import StrEnum

from vat_born.clock import GameTime, Tick
from vat_born.dice import Key, Odds
from vat_born.world import CharacterId, Layer, NodeId, PlaceKind


class Activity(StrEnum):
    """What the PC was doing while time passed."""

    WAITING = "waiting"


# Facts


@dataclass(frozen=True, slots=True)
class WorldCreated:
    seed: int


@dataclass(frozen=True, slots=True)
class PlaceAdded:
    place: NodeId
    layer: Layer
    kind: PlaceKind
    name: str
    description: str


@dataclass(frozen=True, slots=True)
class CloneWoke:
    run: int
    pc: CharacterId
    place: NodeId
    place_name: str


@dataclass(frozen=True, slots=True)
class TimePassed:
    start: Tick
    end: Tick
    activity: Activity


@dataclass(frozen=True, slots=True)
class Rolled:
    purpose: str
    key: tuple[Key, ...]
    odds: Odds
    chance: float
    value: float
    success: bool


type Fact = WorldCreated | PlaceAdded | CloneWoke | TimePassed | Rolled


# Reports


@dataclass(frozen=True, slots=True)
class Resumed:
    seed: int
    run: int
    time: GameTime
    place_name: str


@dataclass(frozen=True, slots=True)
class StatusReport:
    time: GameTime
    run: int


@dataclass(frozen=True, slots=True)
class PlaceReport:
    place_name: str


@dataclass(frozen=True, slots=True)
class LookReport:
    place_name: str
    description: str


@dataclass(frozen=True, slots=True)
class PhaseChanged:
    before: GameTime
    after: GameTime


type Report = Resumed | StatusReport | PlaceReport | LookReport | PhaseChanged

type Event = Fact | Report
