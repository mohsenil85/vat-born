"""What the engine tells frontends.

Facts are changes to the world. `Txn.record` applies a fact and appends it to the event log, and nothing else changes
state, so the log holds every change. Reports answer free actions and point out what a change means; they describe
the world without changing it, so they are never logged."""

from dataclasses import dataclass
from enum import StrEnum

from vat_born.clock import GameTime, Tick
from vat_born.dice import Key, Odds
from vat_born.needs import Need
from vat_born.world import CharacterId, Direction, Exit, Layer, NodeId, PlaceKind


class Activity(StrEnum):
    """What the PC was doing while time passed."""

    WAITING = "waiting"
    WALKING = "walking"


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
class PathAdded:
    """A path between two places. It runs both ways: applying it adds the way back as well."""

    place: NodeId
    to: NodeId
    direction: Direction
    ticks: int


@dataclass(frozen=True, slots=True)
class PcMoved:
    pc: CharacterId
    origin: NodeId
    destination: NodeId
    direction: Direction
    place_name: str


@dataclass(frozen=True, slots=True)
class PlaceVisited:
    """The PC has been to this place. The knowledge belongs to the world, so later clones share it."""

    place: NodeId


@dataclass(frozen=True, slots=True)
class TimePassed:
    start: Tick
    end: Tick
    activity: Activity


@dataclass(frozen=True, slots=True)
class NeedsChanged:
    """The PC's needs after time passed: ticks since each was last answered."""

    pc: CharacterId
    thirst: int
    hunger: int
    fatigue: int


@dataclass(frozen=True, slots=True)
class Rolled:
    purpose: str
    key: tuple[Key, ...]
    odds: Odds
    chance: float
    value: float
    success: bool


type Fact = (
    WorldCreated | PlaceAdded | CloneWoke | PathAdded | PcMoved | PlaceVisited | TimePassed | NeedsChanged | Rolled
)


# Reports


@dataclass(frozen=True, slots=True)
class Resumed:
    seed: int
    run: int
    time: GameTime
    place_name: str


@dataclass(frozen=True, slots=True)
class NeedLevel:
    """Where one need stands, for `status`."""

    need: Need
    level: int


@dataclass(frozen=True, slots=True)
class StatusReport:
    time: GameTime
    run: int
    levels: tuple[NeedLevel, ...]


@dataclass(frozen=True, slots=True)
class Route:
    """A way between two places: the directions to walk, in order, and how long the whole walk takes."""

    steps: tuple[Direction, ...]
    ticks: int


@dataclass(frozen=True, slots=True)
class PlaceReport:
    place_name: str
    route: Route | None


@dataclass(frozen=True, slots=True)
class LookReport:
    place_name: str
    description: str
    exits: tuple[Exit, ...]


@dataclass(frozen=True, slots=True)
class MapEntry:
    """One place on the map: its name, whether the PC is in it, and the paths out of it."""

    place_name: str
    here: bool
    exits: tuple[Exit, ...]


@dataclass(frozen=True, slots=True)
class MapReport:
    places: tuple[MapEntry, ...]


@dataclass(frozen=True, slots=True)
class NoPath:
    """There is no path out of here in that direction."""

    direction: Direction


@dataclass(frozen=True, slots=True)
class PhaseChanged:
    before: GameTime
    after: GameTime


@dataclass(frozen=True, slots=True)
class NeedWorsened:
    """A need crossed into a worse level as time passed."""

    need: Need
    level: int


@dataclass(frozen=True, slots=True)
class Interrupted:
    """The action stopped early, so the player can react."""

    activity: Activity


type Report = (
    Resumed | StatusReport | PlaceReport | LookReport | MapReport | NoPath | PhaseChanged | NeedWorsened | Interrupted
)

type Event = Fact | Report
