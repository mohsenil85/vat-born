"""The PC's needs. Each counts the ticks since it was last answered, and the count reads as a level that says how
the clone is doing; what comes after the last level is death, which waits for M5."""

from dataclasses import dataclass
from enum import StrEnum
from typing import assert_never


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
    HANDLING = "handling"
    EATING = "eating"


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


def tick(needs: Needs, activity: Activity) -> Needs:
    """One tick later, spent doing ACTIVITY. Thirst holds at 0 while drinking, and resting brings fatigue down
    twice as fast as being awake builds it; hunger only ever builds."""
    thirst = 0 if activity is Activity.DRINKING else needs.thirst + 1
    fatigue = max(needs.fatigue - 2, 0) if activity is Activity.RESTING else needs.fatigue + 1
    return Needs(thirst, needs.hunger + 1, fatigue)
