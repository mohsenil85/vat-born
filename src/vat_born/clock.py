"""Game time. A tick is ten minutes. Tick 0 is 06:00 on day 1, and a game day runs from 06:00 to 06:00, so a night
belongs to the day it began in."""

from dataclasses import dataclass
from enum import StrEnum
from typing import NewType

Tick = NewType("Tick", int)

MINUTES_PER_TICK = 10
TICKS_PER_HOUR = 6
TICKS_PER_DAY = 144
MINUTES_PER_DAY = 24 * 60
_DAY_START = 6 * 60  # the minute of the day at which the game day begins (tick 0 is 06:00 on day 1)


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


def ticks_until(now: Tick, minute_of_day: int) -> int:
    """Ticks from NOW until the clock next reads MINUTE_OF_DAY, minutes after midnight (0 to 1439). The wait is
    strictly later, so a clock that reads that time now is a full day away."""
    assert 0 <= minute_of_day < MINUTES_PER_DAY, f"{minute_of_day} is not a minute of the day"
    into_day = now * MINUTES_PER_TICK % MINUTES_PER_DAY  # minutes since the day began at 06:00
    wait = (minute_of_day - _DAY_START - into_day) % MINUTES_PER_DAY
    assert wait % MINUTES_PER_TICK == 0, f"the clock never reads {minute_of_day} minutes into a tick"
    return wait // MINUTES_PER_TICK if wait else TICKS_PER_DAY
