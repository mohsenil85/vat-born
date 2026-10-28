"""The hazard clocks (design §7.2): dangers that gather in the background as the days pass. Each clock climbs
through three signs a clone can come across — stage 0 is quiet, 1 to 3 are the signs, 4 is the threat — and each
stage comes by a set day at the latest, whatever the rolls.

A clock rolls every tick against the tick's share of a daily chance. A roll logged every tick would bury the log in
misses, so these draws don't go through `Txn.roll`: they come from a stream keyed by the clock and the tick, and
only a clock that moves records a fact, carrying the chance it moved at. This is the one exception to "every roll
is logged".

The threats the clocks climb toward — the hunt, the failing air — are later milestones. Here the clocks only run
and leave their signs.
"""

from dataclasses import dataclass
from enum import StrEnum
from math import pow as float_pow

from vat_born.clock import TICKS_PER_DAY, TICKS_PER_HOUR, Tick, game_time


class Clock(StrEnum):
    """The hazard clocks, in the order they take their turns each tick."""

    PREDATOR = "predator"
    AIR = "air"


@dataclass(frozen=True, slots=True)
class Pace:
    """How fast a clock climbs: the percent chance of reaching the next stage on day 1, the points that chance
    rises each day after, the most it rises to, and the day each stage (1 to 4) comes by at the latest."""

    daily: int
    rise: int
    most: int
    by: tuple[int, int, int, int]


_PACES = {
    Clock.PREDATOR: Pace(30, 10, 80, (3, 5, 7, 9)),
    Clock.AIR: Pace(10, 5, 50, (4, 6, 8, 10)),
}

# 00:00, where the cries are heard, is 18 hours into a game day that starts at 06:00 (tick 0).
_MIDNIGHT = TICKS_PER_HOUR * 18


def daily_chance(clock: Clock, day: int) -> float:
    """The chance of reaching a clock's next stage on DAY, as a share of 1: the daily rate rises each day to its
    ceiling (design §7.2)."""
    pace = _PACES[clock]
    return min(pace.daily + pace.rise * (day - 1), pace.most) / 100


def tick_chance(daily: float) -> float:
    """A daily chance spread over the ticks of a day, so one tick carries the same share of it as any other
    (design §7.2)."""
    return 1 - float_pow(1 - daily, 1 / TICKS_PER_DAY)


def may_move(stage: int, since: Tick, at: Tick) -> bool:
    """Whether a clock may move up a stage at AT: the threat (stage 4) is its last, and a clock never moves twice
    within a day of its last change — which, since the clocks start at tick 0, keeps day 1 quiet."""
    return stage < 4 and at - since >= TICKS_PER_DAY


def due(clock: Clock, stage: int, at: Tick) -> bool:
    """Whether STAGE's day has come by AT, so the clock reaches it for certain instead of rolling."""
    return game_time(at).day >= _PACES[clock].by[stage - 1]


def is_midnight(at: Tick) -> bool:
    """Whether AT is the tick at 00:00, the moment the night's cries carry, if there are any."""
    return at % TICKS_PER_DAY == _MIDNIGHT
