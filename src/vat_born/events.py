"""What the engine tells frontends.

Facts are changes to the world. `Txn.record` applies a fact and appends it to the event log, and nothing else changes
state, so the log holds every change. Reports answer free actions and point out what a change means; they describe
the world without changing it, so they are never logged."""

from dataclasses import dataclass

from vat_born.clock import GameTime, Tick
from vat_born.dice import Key, Odds
from vat_born.needs import Activity, Need
from vat_born.world import CharacterId, Direction, Exit, ItemId, ItemKind, Layer, NodeId, PlaceKind

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
    water: bool


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


@dataclass(frozen=True, slots=True)
class ItemHidden:
    """A thing hidden in a place at worldgen, waiting for a search to turn it up."""

    item: ItemId
    kind: ItemKind
    place: NodeId


@dataclass(frozen=True, slots=True)
class ItemFound:
    """A search turned a hidden item up: it lies in the open where it was found. NAME is its singular name."""

    item: ItemId
    place: NodeId
    name: str


@dataclass(frozen=True, slots=True)
class ItemTaken:
    """The item went from the open at PLACE into the PC's hands. NAME is its singular name."""

    pc: CharacterId
    item: ItemId
    place: NodeId
    name: str


@dataclass(frozen=True, slots=True)
class ItemDropped:
    """The item went from the PC's hands into the open at PLACE. NAME is its singular name."""

    pc: CharacterId
    item: ItemId
    place: NodeId
    name: str


@dataclass(frozen=True, slots=True)
class Ate:
    """The PC ate the item, which is gone. HUNGER is the PC's hunger after the meal; NAME is the item's singular
    name."""

    pc: CharacterId
    item: ItemId
    name: str
    hunger: int


@dataclass(frozen=True, slots=True)
class ItemFilled:
    """An item the PC carries was filled with water to its capacity. NAME is its singular name."""

    item: ItemId
    name: str
    drinks: int


@dataclass(frozen=True, slots=True)
class DrankFrom:
    """The PC drank one drink from an item it carries; DRINKS is what's left in it. NAME is its singular name."""

    item: ItemId
    name: str
    drinks: int


@dataclass(frozen=True, slots=True)
class PlaceSearchedBare:
    """The current clone has searched PLACE until nothing was left. The knowledge is the clone's, not the world's
    (design §4)."""

    run: int
    place: NodeId


type Fact = (
    WorldCreated
    | PlaceAdded
    | CloneWoke
    | PathAdded
    | PcMoved
    | PlaceVisited
    | ItemHidden
    | ItemFound
    | ItemTaken
    | ItemDropped
    | Ate
    | ItemFilled
    | DrankFrom
    | PlaceSearchedBare
    | TimePassed
    | NeedsChanged
    | Rolled
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
class ItemStack:
    """COUNT items of one kind, as a look lists them. For the things that hold water (CAPACITY above 0), DRINKS is
    the drinks in each item of the stack and the stack holds only items equally full; None, with capacity 0, for
    everything else."""

    name: str
    plural: str
    count: int
    drinks: int | None
    capacity: int


@dataclass(frozen=True, slots=True)
class LookReport:
    place_name: str
    description: str
    items: tuple[ItemStack, ...]  # the items lying in the open, one stack per kind, in items.toml order
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
class NeedMet:
    """A need came back down to 0 as time passed, so it is answered for now."""

    need: Need


@dataclass(frozen=True, slots=True)
class Interrupted:
    """The action stopped early, so the player can react."""

    activity: Activity


@dataclass(frozen=True, slots=True)
class NoWater:
    """There is nothing to drink where the PC is."""


@dataclass(frozen=True, slots=True)
class NotTired:
    """The PC is already rested, so there is nothing to sleep off."""


@dataclass(frozen=True, slots=True)
class NowhereLeft:
    """This place has been searched bare already, and the clone knows it."""


@dataclass(frozen=True, slots=True)
class InventoryReport:
    """What the PC carries, one stack per kind, in items.toml order."""

    items: tuple[ItemStack, ...]


@dataclass(frozen=True, slots=True)
class WhichOne:
    """The words could mean more than one kind of thing, so the player must say which. NAMES holds each answering
    kind's singular name, in items.toml order."""

    names: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class NotHere:
    """Nothing the words mean lies in the open where the PC is."""

    words: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class NotCarried:
    """The PC carries nothing the words mean."""

    words: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class NothingHere:
    """Nothing lies in the open where the PC is, so there is nothing to take."""


@dataclass(frozen=True, slots=True)
class NothingCarried:
    """The PC carries nothing, so there is nothing to drop."""


@dataclass(frozen=True, slots=True)
class NotFood:
    """The thing named can't be eaten. NAME is its singular name."""

    name: str


@dataclass(frozen=True, slots=True)
class NothingToFill:
    """The PC carries nothing that holds water and isn't full."""


@dataclass(frozen=True, slots=True)
class NothingToDrink:
    """There is no water where the PC is, and the only thing it carries that holds water is empty. NAME is that
    thing's singular name."""

    name: str


@dataclass(frozen=True, slots=True)
class NeedEased:
    """An action answered a need: how hungry or tired the PC was before (BEFORE) and is after (AFTER), as levels."""

    need: Need
    before: int
    after: int


type Report = (
    Resumed
    | StatusReport
    | PlaceReport
    | LookReport
    | MapReport
    | NoPath
    | PhaseChanged
    | NeedWorsened
    | NeedMet
    | NeedEased
    | Interrupted
    | NoWater
    | NotTired
    | NowhereLeft
    | InventoryReport
    | WhichOne
    | NotHere
    | NotCarried
    | NothingHere
    | NothingCarried
    | NotFood
    | NothingToFill
    | NothingToDrink
)

type Event = Fact | Report
