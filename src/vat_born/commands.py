"""Typed input to a command: an intent for the engine, or one of the frontend's own (help, quit). Engine commands are
a small fixed vocabulary (design §10.3); other text is rejected until the intent parser exists (M9)."""

import re
from dataclasses import dataclass

from vat_born.clock import MINUTES_PER_TICK
from vat_born.intents import Intent, Look, Status, Wait, Where


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
    Usage("where", "where you are; takes no time"),
    Usage("look", "describe where you are; takes no time"),
    Usage("wait [time]", 'let time pass: "wait", "wait 30 minutes", "wait 2 hours", "wait a day"'),
    Usage("help", "this list"),
    Usage("quit", "stop playing; the world keeps your place"),
)

_WAIT_HELP = 'Wait how long? Try "wait", "wait 30 minutes", or "wait 2 hours".'
# A longer wait is almost surely a typo, and a big enough one would overflow SQLite's integers.
_MAX_WAIT_DAYS = 30

_UNIT_MINUTES = {
    **dict.fromkeys(("m", "min", "mins", "minute", "minutes"), 1),
    **dict.fromkeys(("h", "hr", "hrs", "hour", "hours"), 60),
    **dict.fromkeys(("d", "day", "days"), 24 * 60),
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
        case "wait":
            return _wait(rest)
        case "help" | "?":
            return Help()
        case "quit" | "exit":
            return Quit()
        case _:
            return Rejected(f'I don\'t know "{verb}". Type "help" for the commands.')


def _wait(words: list[str]) -> Command:
    if not words:
        return Wait(1)
    minutes = _minutes(words)
    if minutes is None or minutes <= 0:
        return Rejected(_WAIT_HELP)
    if minutes > _MAX_WAIT_DAYS * _UNIT_MINUTES["day"]:
        return Rejected(f"That's too long to wait in one go: {_MAX_WAIT_DAYS} days at most.")
    return Wait((minutes + MINUTES_PER_TICK - 1) // MINUTES_PER_TICK)  # round up to whole ticks


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
