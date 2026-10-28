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
    """Drink your fill, where there's water."""


@dataclass(frozen=True, slots=True)
class Search:
    """Search where you are for what the place hides."""


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


type FreeIntent = Status | Where | Look | Map
type TimedIntent = Wait | WaitUntil | Move | Drink | Search | Rest | RestUntil
type Intent = FreeIntent | TimedIntent
