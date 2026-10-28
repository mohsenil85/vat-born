"""Events into the words a player reads. This is template text until the narrator arrives (M9); the scenario
transcripts pin it down."""

from typing import assert_never

from vat_born.clock import TICKS_PER_DAY, TICKS_PER_HOUR, GameTime
from vat_born.dice import Odds
from vat_born.events import (
    Activity,
    CloneWoke,
    Event,
    Interrupted,
    LookReport,
    MapEntry,
    MapReport,
    NeedLevel,
    NeedsChanged,
    NeedWorsened,
    NoPath,
    PathAdded,
    PcMoved,
    PhaseChanged,
    PlaceAdded,
    PlaceReport,
    PlaceVisited,
    Resumed,
    Rolled,
    Route,
    StatusReport,
    TimePassed,
    WorldCreated,
)
from vat_born.needs import Need
from vat_born.world import Direction, Exit

_NUMBERS = ("zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine")
_MINUTES = ("ten minutes", "twenty minutes", "half an hour", "forty minutes", "fifty minutes")

# What each need says as it reaches each level (1 to 3), and how `status` names it there.
_WORSENING = {
    Need.THIRST: ("You're getting thirsty.", "You're very thirsty now.", "You're dying of thirst."),
    Need.HUNGER: ("You're getting hungry.", "You're very hungry now.", "You're starving."),
    Need.FATIGUE: ("You're getting tired.", "You're very tired now.", "You're exhausted."),
}
_NAMED = {
    Need.THIRST: ("thirsty", "very thirsty", "dying of thirst"),
    Need.HUNGER: ("hungry", "very hungry", "starving"),
    Need.FATIGUE: ("tired", "very tired", "exhausted"),
}


def render(event: Event) -> list[str]:
    """The lines to show for EVENT: none for a fact the player doesn't notice."""
    match event:
        case WorldCreated(seed=seed):
            return [f"A new world, seed {seed}."]
        case PlaceAdded() | PathAdded() | PlaceVisited() | NeedsChanged():
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
        case StatusReport(time=time, run=run, levels=levels):
            return [f"{describe_time(time)}. You are clone {run}.", _how_you_are(levels)]
        case PlaceReport(place_name=place, route=route):
            line = f"You are in {place}."
            match route:
                case None:
                    return [line, "You don't know the way home from here."]
                case Route(steps=steps, ticks=ticks):
                    if not steps:
                        return [line, "You are home."]
                    return [line, f"The way home: {_route(steps)} ({describe_duration(ticks)})."]
        case NoPath(direction=direction):
            return [f"You can't go {direction} from here."]
        case LookReport(place_name=place, description=description, exits=exits):
            return [place[:1].upper() + place[1:], description, _paths(exits)]
        case MapReport(places=places):
            return [_on_the_map(entry) for entry in places]
        case PhaseChanged(before=before, after=after):
            if after.day == before.day:
                return [f"It is now {after.phase}."]
            return [f"It is now day {after.day}, {after.phase}."]
        case NeedWorsened(need=need, level=level):
            return [_WORSENING[need][level - 1]]
        case Interrupted(activity=activity):
            return [_stopped(activity)]
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


def _stopped(activity: Activity) -> str:
    """What the PC does when an action stops early. A walk never stops, but the words stay exhaustive."""
    match activity:
        case Activity.WAITING:
            return "You stop waiting."
        case Activity.WALKING:
            return "You stop walking."
        case _:
            assert_never(activity)


def _how_you_are(levels: tuple[NeedLevel, ...]) -> str:
    """The second line of `status`: each need above level 0, named by its level, in `Need` order."""
    words = [_NAMED[entry.need][entry.level - 1] for entry in levels if entry.level > 0]
    if not words:
        return "You feel fine."
    if len(words) == 1:
        return f"You're {words[0]}."
    if len(words) == 2:
        return f"You're {words[0]} and {words[1]}."
    return f"You're {', '.join(words[:-1])}, and {words[-1]}."


def _paths(exits: tuple[Exit, ...]) -> str:
    """The exits as one line, in `Direction` order; only a walk longer than ten minutes says how long it is."""
    return f"Paths: {_exits(exits)}."


def _exits(exits: tuple[Exit, ...], *, unknown: bool = False) -> str:
    """The exits as a comma-separated list, in `Direction` order. With UNKNOWN, a way into unvisited ground says so,
    after any duration."""
    if not exits:
        return "none"
    return ", ".join(_exit(out, unknown=unknown) for out in exits)


def _exit(out: Exit, *, unknown: bool) -> str:
    inside = [describe_duration(out.ticks)] if out.ticks > 1 else []
    if unknown and not out.explored:
        inside.append("unexplored")
    way = f"{out.direction} to {out.place_name}"
    return f"{way} ({', '.join(inside)})" if inside else way


def _on_the_map(entry: MapEntry) -> str:
    place = entry.place_name[:1].upper() + entry.place_name[1:]
    here = " (you are here)" if entry.here else ""
    return f"{place}{here}: {_exits(entry.exits, unknown=True)}."


def _route(steps: tuple[Direction, ...]) -> str:
    """The steps as a person would give them: "west, then up, then south five times"."""
    runs: list[tuple[Direction, int]] = []
    for step in steps:
        if runs and runs[-1][0] == step:
            runs[-1] = (step, runs[-1][1] + 1)
        else:
            runs.append((step, 1))
    return ", then ".join(_steps_of_one_way(way, n) for way, n in runs)


def _steps_of_one_way(way: Direction, n: int) -> str:
    if n == 1:
        return str(way)
    if n == 2:
        return f"{way} twice"
    return f"{way} {_number(n)} times"


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
