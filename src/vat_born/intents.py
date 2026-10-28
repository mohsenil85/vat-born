"""What the engine can be asked to do. Typed commands parse into these, and so will the LLM's intent parser (M9).

Free intents only read the world and take no time; timed intents change it and take at least one tick."""

from dataclasses import dataclass

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
class Wait:
    """Let time pass."""

    ticks: int

    def __post_init__(self) -> None:
        assert self.ticks > 0, "a wait takes at least one tick"


@dataclass(frozen=True, slots=True)
class Move:
    """Walk the path in that direction, if there is one."""

    direction: Direction


type FreeIntent = Status | Where | Look
type TimedIntent = Wait | Move
type Intent = FreeIntent | TimedIntent
