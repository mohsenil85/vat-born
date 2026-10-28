"""Typed input to a command: an intent for the engine, or one of the frontend's own (help, quit). Engine commands are
a small fixed vocabulary (design §10.3); other text is rejected until the intent parser exists (M9)."""

import re
from collections.abc import Callable
from dataclasses import dataclass

from vat_born.clock import MINUTES_PER_TICK
from vat_born.intents import (
    Drink,
    Drop,
    DropAll,
    Eat,
    Fight,
    Fill,
    Flee,
    Intent,
    Inventory,
    Look,
    Map,
    Move,
    Rest,
    RestUntil,
    Search,
    Status,
    Take,
    TakeAll,
    Wait,
    WaitUntil,
    Where,
)
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
    Usage("inventory", "what you're carrying; takes no time"),
    Usage("go <way>", "walk to the next place: north, south, east, west, up, down (n, s, e, w, u, d)"),
    Usage("wait [time]", 'let time pass: "wait", "wait 30 minutes", "wait 2 hours", "wait until noon"'),
    Usage("rest [time]", 'rest, or sleep, until rested or for a while: "rest", "rest 2 hours", "sleep until dawn"'),
    Usage("drink", "drink your fill where there's water, or from your canteen"),
    Usage("fill", "fill your canteen where there's water"),
    Usage("search", "spend an hour searching where you are; each place hides only so much"),
    Usage("take <thing>", 'pick up what you see: "take ration bar", "take bar", "take all"'),
    Usage("drop <thing>", 'put down what you carry: "drop canteen", "drop all"'),
    Usage("eat <food>", 'eat something you carry: "eat ration bar", "eat stew"'),
    Usage("fight", "fight off what's attacking you; it asks first, with the odds"),
    Usage("flee", "run back the way you came from what's attacking you; it asks first, with the odds"),
    Usage("help", "this list"),
    Usage("quit", "stop playing; the world keeps your place"),
)

_WAIT_HELP = 'Wait how long? Try "wait", "wait 30 minutes", or "wait 2 hours".'
_WAIT_UNTIL_HELP = 'Wait until when? Try "wait until noon", "wait until dusk", or "wait until dawn".'
_REST_HELP = 'Rest how long? Try "rest", "rest 2 hours", or "sleep until dawn".'
_REST_UNTIL_HELP = 'Rest until when? Try "sleep until dawn", "rest until noon", or "rest until dusk".'
_GO_HELP = 'Go where? Try "go north", or just "n".'
_TAKE_HELP = 'Take what? Try "take ration bar", or "take all".'
_DROP_HELP = 'Drop what? Try "drop ration bar", or "drop all".'
_EAT_HELP = 'Eat what? Try "eat ration bar".'
_PICK_UP_HELP = 'Pick up what? Try "pick up ration bar".'
_ARTICLES = frozenset(("the", "a", "an", "some"))
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
        case "inventory" | "inv" | "i":
            return Inventory()
        case "wait":
            return _wait(rest)
        case "rest" | "sleep":
            return _rest(rest)
        case "drink":  # extra words are ignored, as in "drink water"
            return Drink()
        case "fill":  # extra words are ignored, as in "fill canteen"
            return Fill()
        case "search":  # extra words are ignored, as in "search the room"
            return Search()
        case "take" | "get":
            return _taking(rest)
        case "pick":
            match rest:
                case ["up", *what]:
                    return _taking(what)
                case _:
                    return Rejected(_PICK_UP_HELP)
        case "drop":
            return _dropping(rest)
        case "eat":
            return _eating(rest)
        case "fight" | "attack":  # extra words are ignored, as in "fight it"
            return Fight()
        case "flee" | "run":  # extra words are ignored, as in "run for it"
            return Flee()
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
        case _:
            return _lasting(words, _WAIT_HELP, _WAIT_UNTIL_HELP, Wait, WaitUntil)


def _rest(words: list[str]) -> Command:
    match words:
        case []:
            return Rest(None)
        case _:
            return _lasting(words, _REST_HELP, _REST_UNTIL_HELP, Rest, RestUntil)


def _lasting(
    words: list[str],
    how_long: str,
    until_when: str,
    span: Callable[[int], Wait | Rest],
    until: Callable[[int], WaitUntil | RestUntil],
) -> Command:
    """The time words `wait` and `rest` share: a duration, or a time of day to last until."""
    match words:
        case [("until" | "till" | "til" | "'til"), *rest]:
            minute = _time_of_day(rest)
            return until(minute) if minute is not None else Rejected(until_when)
        case ["for", *rest]:
            minute = _time_of_day(rest)
            return until(minute) if minute is not None else _lasting_duration(rest, how_long, span)
        case _:
            return _lasting_duration(words, how_long, span)


def _lasting_duration(words: list[str], how_long: str, span: Callable[[int], Wait | Rest]) -> Command:
    minutes = _minutes(words)
    if minutes is None or minutes <= 0:
        return Rejected(how_long)
    if minutes > _MAX_WAIT_DAYS * _UNIT_MINUTES["day"]:
        return Rejected(f"That's too long for one go: {_MAX_WAIT_DAYS} days at most.")  # said of waits and rests alike
    return span((minutes + MINUTES_PER_TICK - 1) // MINUTES_PER_TICK)  # round up to whole ticks


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


def _taking(words: list[str]) -> Command:
    """The words after "take", "get", or "pick up": what to pick up."""
    match _thing(words):
        case []:
            return Rejected(_TAKE_HELP)
        case ["all" | "everything"]:
            return TakeAll()
        case what:
            return Take(tuple(what))


def _dropping(words: list[str]) -> Command:
    """The words after "drop": what to put down."""
    match _thing(words):
        case []:
            return Rejected(_DROP_HELP)
        case ["all" | "everything"]:
            return DropAll()
        case what:
            return Drop(tuple(what))


def _eating(words: list[str]) -> Command:
    """The words after "eat": what to eat."""
    match _thing(words):
        case []:
            return Rejected(_EAT_HELP)
        case what:
            return Eat(tuple(what))


def _thing(words: list[str]) -> list[str]:
    """The words that name a thing, with a leading article dropped: "the lamp" and "some bars" are "lamp" and
    "bars"."""
    return words[1:] if words and words[0] in _ARTICLES else words


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
