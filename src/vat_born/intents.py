"""What the engine can be asked to do. Typed commands parse into these, and so will the LLM's intent parser (M9).

Free intents only read the world and take no time; timed intents change it and take at least one tick."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Status:
    """The day, the phase, and how the PC is."""


@dataclass(frozen=True, slots=True)
class Where:
    """Where the PC is."""


@dataclass(frozen=True, slots=True)
class Wait:
    """Let time pass."""

    ticks: int

    def __post_init__(self) -> None:
        assert self.ticks > 0, "a wait takes at least one tick"


type FreeIntent = Status | Where
type TimedIntent = Wait
type Intent = FreeIntent | TimedIntent
