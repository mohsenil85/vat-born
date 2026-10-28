"""Game time. A tick is ten minutes. Tick 0 is 06:00 on day 1, and a game day runs from 06:00 to 06:00, so a night
belongs to the day it began in."""

from dataclasses import dataclass
from enum import StrEnum
from typing import NewType

Tick = NewType("Tick", int)

MINUTES_PER_TICK = 10
TICKS_PER_HOUR = 6
TICKS_PER_DAY = 144


class Phase(StrEnum):
    MORNING = "morning"  # 06:00 to 12:00
    AFTERNOON = "afternoon"  # 12:00 to 18:00
    EVENING = "evening"  # 18:00 to 22:00
    NIGHT = "night"  # 22:00 to 06:00


# Ticks into the game day at which each phase starts, latest first.
_PHASE_STARTS = ((96, Phase.NIGHT), (72, Phase.EVENING), (36, Phase.AFTERNOON), (0, Phase.MORNING))


@dataclass(frozen=True, slots=True)
class GameTime:
    """The time as the player sees it: never ticks, only the day and the phase."""

    day: int
    phase: Phase


def game_time(tick: Tick) -> GameTime:
    assert tick >= 0, f"tick {tick} is before the world began"
    day, into_day = divmod(tick, TICKS_PER_DAY)
    phase = next(phase for start, phase in _PHASE_STARTS if into_day >= start)
    return GameTime(day + 1, phase)
