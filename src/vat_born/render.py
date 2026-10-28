"""Events into the words a player reads. This is template text until the narrator arrives (M9); the scenario
transcripts pin it down."""

from typing import assert_never

from vat_born.clock import TICKS_PER_DAY, TICKS_PER_HOUR, GameTime
from vat_born.dice import Odds
from vat_born.events import (
    Activity,
    CloneWoke,
    Event,
    LookReport,
    NoPath,
    PathAdded,
    PcMoved,
    PhaseChanged,
    PlaceAdded,
    PlaceReport,
    Resumed,
    Rolled,
    StatusReport,
    TimePassed,
    WorldCreated,
)
from vat_born.world import Exit

_NUMBERS = ("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine")
_MINUTES = ("ten minutes", "twenty minutes", "half an hour", "forty minutes", "fifty minutes")


def render(event: Event) -> list[str]:
    """The lines to show for EVENT: none for a fact the player doesn't notice."""
    match event:
        case WorldCreated(seed=seed):
            return [f"A new world, seed {seed}."]
        case PlaceAdded() | PathAdded():
            return []
        case CloneWoke(place_name=place):
            return [f"You wake in a clone vat in {place}."]
        case PcMoved(direction=direction, place_name=place):
            return [f"You head {direction} to {place}."]
        case TimePassed():
            return _time_passed(event)
        case Rolled(odds=odds, success=success):
            return [f"{describe_odds(odds)}: {'success' if success else 'failure'}."]
        case Resumed(seed=seed, run=run, time=time, place_name=place):
            return [f"Seed {seed}, clone {run}. {describe_time(time)}.", f"You are in {place}."]
        case StatusReport(time=time, run=run):
            return [f"{describe_time(time)}. You are clone {run}."]
        case PlaceReport(place_name=place):
            return [f"You are in {place}."]
        case NoPath(direction=direction):
            return [f"You can't go {direction} from here."]
        case LookReport(place_name=place, description=description, exits=exits):
            return [place[:1].upper() + place[1:], description, _paths(exits)]
        case PhaseChanged(before=before, after=after):
            if after.day == before.day:
                return [f"It is now {after.phase}."]
            return [f"It is now day {after.day}, {after.phase}."]
        case _:
            assert_never(event)


def describe_time(time: GameTime) -> str:
    return f"Day {time.day}, {time.phase}"


def describe_duration(ticks: int) -> str:
    """A duration as a person would say it: "half an hour", "two hours", "about a day"."""
    assert ticks > 0, "a duration is at least one tick"
    if ticks < TICKS_PER_HOUR:
        return _MINUTES[ticks - 1]
    if ticks < TICKS_PER_DAY:
        hours, rest = divmod(ticks, TICKS_PER_HOUR)
        if rest == 0:
            return _count(hours, "hour")
        if rest * 2 == TICKS_PER_HOUR:
            return "an hour and a half" if hours == 1 else f"{_number(hours)} and a half hours"
        rounded = round(ticks / TICKS_PER_HOUR)
        return "about a day" if rounded == 24 else f"about {_count(rounded, 'hour')}"
    days, rest = divmod(ticks, TICKS_PER_DAY)
    if rest == 0:
        return _count(days, "day")
    return f"about {_count(round(ticks / TICKS_PER_DAY), 'day')}"


def describe_odds(odds: Odds) -> str:
    """The chance and how it was reached: "55% (base 40%, lamp +15%)", or just "40%" when nothing modifies it."""
    if not odds.modifiers:
        return _percent(odds.chance)
    parts = [f"base {_percent(odds.base)}", *(f"{m.reason} {m.delta:+.0%}" for m in odds.modifiers)]
    return f"{_percent(odds.chance)} ({', '.join(parts)})"


def _time_passed(event: TimePassed) -> list[str]:
    match event.activity:
        case Activity.WALKING:
            return []  # the move itself says where the walk went
        case Activity.WAITING:
            return [f"You wait {describe_duration(event.end - event.start)}."]
        case _:
            assert_never(event.activity)


def _paths(exits: tuple[Exit, ...]) -> str:
    """The exits as one line, in `Direction` order; only a walk longer than ten minutes says how long it is."""
    if not exits:
        return "Paths: none."
    ways = ", ".join(
        f"{out.direction} to {out.place_name}" + (f" ({describe_duration(out.ticks)})" if out.ticks > 1 else "")
        for out in exits
    )
    return f"Paths: {ways}."


def _count(n: int, unit: str) -> str:
    """Like "an hour", "two hours", or "a day"."""
    if n == 1:
        return f"{'an' if unit == 'hour' else 'a'} {unit}"
    return f"{_number(n)} {unit}s"


def _number(n: int) -> str:
    return _NUMBERS[n] if n < len(_NUMBERS) else str(n)


def _percent(p: float) -> str:
    # Rounding would show a real chance as 0% or 100%.
    if 0 < p < 0.005:
        return "under 1%"
    if 0.995 < p < 1:
        return "over 99%"
    return f"{p:.0%}"
