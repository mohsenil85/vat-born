"""Typed input to a command: an intent for the engine, or one of the frontend's own (help, quit). Engine commands are
a small fixed vocabulary (design §10.3); other text is rejected until the intent parser exists (M9)."""

import re
from dataclasses import dataclass

from vat_born.clock import MINUTES_PER_TICK
from vat_born.intents import Intent, Look, Map, Move, Status, Wait, WaitUntil, Where
from vat_born.world import Direction


@dataclass(frozen=True, slots=True)
class Help:
    pass


@dataclass(frozen=True, slots=True)
class Quit:
    pass


@dataclass(frozen=True, slots=True)
class Rejected:
    message: str


type Command = Intent | Help | Quit | Rejected


@dataclass(frozen=True, slots=True)
class Usage:
    form: str
    summary: str


HELP = (
    Usage("status", "the day, the time of day, and how you are; takes no time"),
    Usage("where", "where you are and the way home; takes no time"),
    Usage("look", "describe where you are; takes no time"),
    Usage("map", "the places you know and the ways between them; takes no time"),
    Usage("go <way>", "walk to the next place: north, south, east, west, up, down (n, s, e, w, u, d)"),
    Usage("wait [time]", 'let time pass: "wait", "wait 30 minutes", "wait 2 hours", "wait until noon"'),
    Usage("help", "this list"),
    Usage("quit", "stop playing; the world keeps your place"),
)

_WAIT_HELP = 'Wait how long? Try "wait", "wait 30 minutes", or "wait 2 hours".'
_WAIT_UNTIL_HELP = 'Wait until when? Try "wait until noon", "wait until dusk", or "wait until dawn".'
_GO_HELP = 'Go where? Try "go north", or just "n".'
# A longer wait is almost surely a typo, and a big enough one would overflow SQLite's integers.
_MAX_WAIT_DAYS = 30

_UNIT_MINUTES = {
    **dict.fromkeys(("m", "min", "mins", "minute", "minutes"), 1),
    **dict.fromkeys(("h", "hr", "hrs", "hour", "hours"), 60),
    **dict.fromkeys(("d", "day", "days"), 24 * 60),
}

# Every direction word and its first letter: "north" and "n" both mean north.
_WAYS = {word: way for way in Direction for word in (way.value, way.value[:1])}

# Named times of day, as minutes after midnight. The player never sees clock numbers, so a wait names its time;
# most of these are where a phase begins.
_TIMES_OF_DAY = {
    **dict.fromkeys(("dawn", "morning", "tomorrow"), 6 * 60),
    **dict.fromkeys(("noon", "midday", "afternoon"), 12 * 60),
    **dict.fromkeys(("dusk", "evening"), 18 * 60),
    **dict.fromkeys(("night", "nightfall", "dark"), 22 * 60),
    "midnight": 0,
}


def parse(line: str) -> Command:
    words = line.lower().split()
    if not words:
        return Rejected('Type "help" for the commands.')
    verb, rest = words[0], words[1:]
    match verb:
        case "status":
            return Status()
        case "where":
            return Where()
        case "look" | "l":
            return Look()
        case "map" | "m":
            return Map()
        case "wait":
            return _wait(rest)
        case "go":
            return _go(rest)
        case "help" | "?":
            return Help()
        case "quit" | "exit":
            return Quit()
        case way if way in _WAYS:  # extra words are ignored, as for "where am I"
            return Move(_WAYS[way])
        case _:
            return Rejected(f'I don\'t know "{verb}". Type "help" for the commands.')


def _wait(words: list[str]) -> Command:
    match words:
        case []:
            return Wait(1)
        case [("until" | "till" | "til" | "'til"), *rest]:
            return _wait_until(rest)
        case ["for", *rest]:
            return _wait_for(rest)
        case _:
            return _wait_duration(words)


def _wait_duration(words: list[str]) -> Command:
    minutes = _minutes(words)
    if minutes is None or minutes <= 0:
        return Rejected(_WAIT_HELP)
    if minutes > _MAX_WAIT_DAYS * _UNIT_MINUTES["day"]:
        return Rejected(f"That's too long to wait in one go: {_MAX_WAIT_DAYS} days at most.")
    return Wait((minutes + MINUTES_PER_TICK - 1) // MINUTES_PER_TICK)  # round up to whole ticks


def _wait_until(words: list[str]) -> Command:
    minute = _time_of_day(words)
    if minute is None:
        return Rejected(_WAIT_UNTIL_HELP)
    return WaitUntil(minute)


def _wait_for(words: list[str]) -> Command:
    minute = _time_of_day(words)
    return WaitUntil(minute) if minute is not None else _wait_duration(words)


def _time_of_day(words: list[str]) -> int | None:
    """The minute of the day WORDS name ("evening", "the evening"), or None if they name no time."""
    match words:
        case ["the", word] | [word]:
            return _TIMES_OF_DAY.get(word)
        case _:
            return None


def _go(words: list[str]) -> Command:
    if words and words[0] in _WAYS:
        return Move(_WAYS[words[0]])
    return Rejected(_GO_HELP)


def _minutes(words: list[str]) -> int | None:
    """Minutes in "30 minutes", "30m", "2 hours", "an hour", or "a day"; None if it isn't a duration."""
    match words:
        case ["a" | "an", unit] if unit in _UNIT_MINUTES:
            return _UNIT_MINUTES[unit]
        case [count, unit] if count.isdecimal() and unit in _UNIT_MINUTES:
            return int(count) * _UNIT_MINUTES[unit]
        case [compact] if (found := re.fullmatch(r"(\d+)([a-z]+)", compact)) and found[2] in _UNIT_MINUTES:
            return int(found[1]) * _UNIT_MINUTES[found[2]]
        case _:
            return None
