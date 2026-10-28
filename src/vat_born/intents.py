"""What the engine can be asked to do. Typed commands parse into these, and so will the LLM's intent parser (M9).

Free intents only read the world and take no time; timed intents change it and take at least one tick."""

from dataclasses import dataclass

from vat_born.clock import MINUTES_PER_DAY
from vat_born.world import Direction


@dataclass(frozen=True, slots=True)
class Status:
    """The day, the phase, and how the PC is."""


@dataclass(frozen=True, slots=True)
class Where:
    """Where the PC is."""


@dataclass(frozen=True, slots=True)
class Look:
    """A description of the place the PC is in."""


@dataclass(frozen=True, slots=True)
class Map:
    """The places the PC knows and the paths between them."""


@dataclass(frozen=True, slots=True)
class Inventory:
    """What the PC carries."""


@dataclass(frozen=True, slots=True)
class Wait:
    """Let time pass."""

    ticks: int

    def __post_init__(self) -> None:
        assert self.ticks > 0, "a wait takes at least one tick"


@dataclass(frozen=True, slots=True)
class WaitUntil:
    """Wait until the clock next reads this minute of the day."""

    minute_of_day: int

    def __post_init__(self) -> None:
        assert 0 <= self.minute_of_day < MINUTES_PER_DAY, f"{self.minute_of_day} is not a minute of the day"


@dataclass(frozen=True, slots=True)
class Move:
    """Walk the path in that direction, if there is one."""

    direction: Direction


@dataclass(frozen=True, slots=True)
class Drink:
    """Drink your fill, where there's water or in something you carry."""


@dataclass(frozen=True, slots=True)
class Fill:
    """Fill what holds water, where there's water."""


@dataclass(frozen=True, slots=True)
class Search:
    """Search where you are for what the place hides."""


@dataclass(frozen=True, slots=True)
class Repair:
    """Work on the air recycler in the vat bay, when it falters. The work keeps between stints."""


@dataclass(frozen=True, slots=True)
class Take:
    """Pick up what the words mean, from the open where the PC stands."""

    words: tuple[str, ...]

    def __post_init__(self) -> None:
        assert self.words, "taking needs words"


@dataclass(frozen=True, slots=True)
class TakeAll:
    """Pick up everything lying in the open where the PC stands."""


@dataclass(frozen=True, slots=True)
class Drop:
    """Put down what the words mean, from what the PC carries."""

    words: tuple[str, ...]

    def __post_init__(self) -> None:
        assert self.words, "dropping needs words"


@dataclass(frozen=True, slots=True)
class DropAll:
    """Put down everything the PC carries."""


@dataclass(frozen=True, slots=True)
class Eat:
    """Eat what the words mean, from what the PC carries."""

    words: tuple[str, ...]

    def __post_init__(self) -> None:
        assert self.words, "eating needs words"


@dataclass(frozen=True, slots=True)
class Rest:
    """Rest or sleep. Ticks None means until rested."""

    ticks: int | None

    def __post_init__(self) -> None:
        assert self.ticks is None or self.ticks > 0, "a rest takes at least one tick"


@dataclass(frozen=True, slots=True)
class RestUntil:
    """Rest until the clock next reads this minute of the day."""

    minute_of_day: int

    def __post_init__(self) -> None:
        assert 0 <= self.minute_of_day < MINUTES_PER_DAY, f"{self.minute_of_day} is not a minute of the day"


@dataclass(frozen=True, slots=True)
class Fight:
    """Fight off what has the PC cornered."""


@dataclass(frozen=True, slots=True)
class Flee:
    """Run from what has the PC cornered, back the way the PC came."""


type FreeIntent = Status | Where | Look | Map | Inventory
type TimedIntent = (
    Wait
    | WaitUntil
    | Move
    | Drink
    | Fill
    | Search
    | Repair
    | Take
    | TakeAll
    | Drop
    | DropAll
    | Eat
    | Rest
    | RestUntil
    | Fight
    | Flee
)
type Intent = FreeIntent | TimedIntent
