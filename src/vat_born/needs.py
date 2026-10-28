"""The PC's needs. Each counts the ticks since it was last answered, and the count reads as a level that says how
the clone is doing; past the last level, thirst and hunger kill at a count of their own (M5), while fatigue never
kills. Wounds count the other way: down, as they heal."""

from dataclasses import dataclass
from enum import StrEnum
from typing import assert_never

from vat_born.clock import TICKS_PER_DAY, TICKS_PER_HOUR


class Need(StrEnum):
    """The needs a clone carries, in the order they are reported in."""

    THIRST = "thirst"
    HUNGER = "hunger"
    FATIGUE = "fatigue"


class Activity(StrEnum):
    """What the PC was doing while time passed."""

    WAITING = "waiting"
    WALKING = "walking"
    RESTING = "resting"
    DRINKING = "drinking"
    SEARCHING = "searching"
    REPAIRING = "repairing"
    HANDLING = "handling"
    EATING = "eating"
    FIGHTING = "fighting"
    DEAD = "dead"  # the respawn gap: time passing with nobody aboard


@dataclass(frozen=True, slots=True)
class Needs:
    """Ticks since each need was last answered. A fresh clone has all three at 0."""

    thirst: int
    hunger: int
    fatigue: int

    def count(self, need: Need) -> int:
        match need:
            case Need.THIRST:
                return self.thirst
            case Need.HUNGER:
                return self.hunger
            case Need.FATIGUE:
                return self.fatigue
            case _:
                assert_never(need)


# The ticks at which each need reaches level 1, 2, and 3: thirst after 12 hours, a day, and two days; hunger after a
# day, three days, and a week; fatigue after 16 hours, a day, and a day and a half. Below the first count, level 0
# means fine.
_AT_LEVEL = {
    Need.THIRST: (72, 144, 288),
    Need.HUNGER: (144, 432, 1008),
    Need.FATIGUE: (96, 144, 216),
}


def level(need: Need, ticks: int) -> int:
    """How bad the need is after TICKS unanswered, from 0 (fine) to 3."""
    return sum(1 for at in _AT_LEVEL[need] if ticks >= at)


# The counts at which the needs kill: thirst after three days without a drink, hunger after two weeks without
# food. Fatigue never kills, so it has no count.
_DEADLY = {
    Need.THIRST: 3 * TICKS_PER_DAY,
    Need.HUNGER: 14 * TICKS_PER_DAY,
}


def deadly(need: Need, ticks: int) -> bool:
    """Whether TICKS unanswered of NEED has reached the count that kills."""
    return need in _DEADLY and ticks >= _DEADLY[need]


def tick(needs: Needs, activity: Activity) -> Needs:
    """One tick later, spent doing ACTIVITY. Thirst holds at 0 while drinking, and resting brings fatigue down
    twice as fast as being awake builds it; hunger only ever builds."""
    thirst = 0 if activity is Activity.DRINKING else needs.thirst + 1
    fatigue = max(needs.fatigue - 2, 0) if activity is Activity.RESTING else needs.fatigue + 1
    return Needs(thirst, needs.hunger + 1, fatigue)


# A wound is a day and a half of healing awake; a badly wounded clone carries two wounds' worth. A third wound
# kills instead of being counted, so the count never rises past two.
_WOUND_TICKS = TICKS_PER_DAY + TICKS_PER_HOUR * 12


def wound_level(wounds: int) -> int:
    """How badly wounded with WOUNDS ticks of healing left: 0 unhurt, 1 wounded, 2 badly wounded."""
    if wounds <= 0:
        return 0
    return 1 if wounds <= _WOUND_TICKS else 2


def take_wound(wounds: int) -> int:
    """The count after one wound more: a wound's worth of healing at a time, never past two of them."""
    return min(wounds + _WOUND_TICKS, 2 * _WOUND_TICKS)


def heal(wounds: int, activity: Activity) -> int:
    """The count after one tick spent doing ACTIVITY: wounds close three times as fast resting as awake."""
    rate = 3 if activity is Activity.RESTING else 1
    return max(wounds - rate, 0)
