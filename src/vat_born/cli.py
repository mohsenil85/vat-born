"""The terminal frontend: picks the world file, then reads commands one per line and prints what happened. The only
module that prints."""

import argparse
import contextlib
import importlib
import os
import secrets
import shutil
import sys
import textwrap
from collections.abc import Sequence
from enum import StrEnum
from pathlib import Path
from typing import cast

from vat_born.commands import HELP, Help, Quit, Rejected, parse
from vat_born.content import Content, load_content
from vat_born.engine import Game, Turn
from vat_born.render import render
from vat_born.store import WorldError

_NEW_SEEDS = 1_000_000  # random seeds for new worlds stay below this, so they're easy to read and type
_MAX_WIDTH = 100  # wrapped text never runs past this, however wide the terminal gets: longer lines are hard to read


class ShowLog(StrEnum):
    """How much of the event log to print. Making a world logs every place and path, so only `ALL` shows that."""

    TURNS = "turns"
    ALL = "all"


def main(argv: Sequence[str] | None = None) -> int:
    args = _arguments().parse_args(argv)
    world = cast("Path | None", args.world)
    seed = cast("int | None", args.seed)
    show_log = cast("ShowLog | None", args.show_log)
    # Wrapping follows where the text goes, unlike `interactive` (stdin), which is about prompts and echo.
    wrap = sys.stdout.isatty()
    try:
        game, turn = _open(world, seed, load_content())
    except WorldError as error:
        print(f"vat-born: {error}", file=sys.stderr)
        return 2
    try:
        _show(turn, log=show_log is ShowLog.ALL, wrap=wrap)
        _say('Type "help" for the commands.', wrap=wrap)
        _play(game, log=show_log is not None, wrap=wrap)
    except KeyboardInterrupt:
        print()
        return 130
    finally:
        game.close()
    return 0


def _arguments() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vat-born",
        description="A text-first survival roguelike aboard a colony ship. Commands are read one per line; the end "
        "of input quits.",
    )
    parser.add_argument("--seed", type=_seed, metavar="N", help="play world N, making it if it doesn't exist yet")
    parser.add_argument(
        "--world",
        type=Path,
        metavar="PATH",
        help="play the world in this file, making it if it doesn't exist yet (default: one file per seed in "
        "$XDG_DATA_HOME/vat-born, resuming the last world played)",
    )
    parser.add_argument(
        "--show-log",
        nargs="?",
        const=ShowLog.TURNS,
        type=ShowLog,
        choices=list(ShowLog),
        help="after each command, print what it added to the event log; with =all, the world's making too",
    )
    return parser


def _seed(text: str) -> int:
    if not text.isdecimal():
        msg = "a seed is a whole number, 0 or more"
        raise argparse.ArgumentTypeError(msg)
    return int(text)


def _open(world: Path | None, seed: int | None, content: Content) -> tuple[Game, Turn]:
    """Open or make the world to play. --world names the file. Otherwise worlds live in the data directory, one per
    seed, and with no --seed the last one played resumes."""
    if world is not None:
        return _open_or_create(world, seed, content)
    worlds = _data_dir()
    worlds.mkdir(parents=True, exist_ok=True)
    last = worlds / "last-world"
    if seed is not None:
        path = worlds / f"{seed}.db"
    elif (remembered := _remembered(last)) is not None:
        path = remembered
    else:
        seed = _unused_seed(worlds)
        path = worlds / f"{seed}.db"
    opened = _open_or_create(path, seed, content)
    last.write_text(f"{path.name}\n")
    return opened


def _open_or_create(path: Path, seed: int | None, content: Content) -> tuple[Game, Turn]:
    if path.exists():
        return Game.resume(path, seed, content)
    return Game.create(path, seed if seed is not None else secrets.randbelow(_NEW_SEEDS), content)


def _data_dir() -> Path:
    xdg = os.environ.get("XDG_DATA_HOME", "")
    base = Path(xdg) if xdg and Path(xdg).is_absolute() else Path.home() / ".local" / "share"
    return base / "vat-born"


def _remembered(last: Path) -> Path | None:
    """The last world played, if it's still there."""
    if not last.exists():
        return None
    path = last.parent / last.read_text().strip()
    return path if path.is_file() else None


def _unused_seed(worlds: Path) -> int:
    while True:
        seed = secrets.randbelow(_NEW_SEEDS)
        if not (worlds / f"{seed}.db").exists():
            return seed


def _play(game: Game, *, log: bool, wrap: bool) -> None:
    interactive = sys.stdin.isatty()
    if interactive:
        with contextlib.suppress(ImportError):  # line editing and history, where the platform has readline
            importlib.import_module("readline")
    while (line := _read(interactive=interactive)) is not None:
        command = line.strip()
        if not command:
            continue
        if not interactive:
            print(f"> {command}")  # no terminal echoes piped input, so show it as a player would have typed it
        match parse(command):
            case Quit():
                return
            case Help():
                _print_help(wrap=wrap)
            case Rejected(message=message):
                _say(message, wrap=wrap)
            case intent:
                _show(game.act(intent), log=log, wrap=wrap)


def _read(*, interactive: bool) -> str | None:
    """The next line of input, or None at the end of it."""
    if not interactive:
        return sys.stdin.readline() or None
    try:
        return input("> ")
    except EOFError:
        print()
        return None


def _show(turn: Turn, *, log: bool, wrap: bool) -> None:
    for event in turn.events:
        for text in render(event):
            _say(text, wrap=wrap)
    if log:
        for entry in turn.logged:
            print(f"  | t{entry.tick} {entry.kind} {entry.payload}")  # the log is machine-shaped; never wrapped


def _say(text: str, *, wrap: bool, hanging: str = "") -> None:
    """Print one line of game text, wrapped to the terminal when the output goes to one. A pipe or a file gets the
    line untouched, so transcripts are stable; the width is read per line, so a resize takes effect."""
    if not wrap:
        print(text)
        return
    width = min(shutil.get_terminal_size().columns, _MAX_WIDTH)
    print(textwrap.fill(text, width=width, subsequent_indent=hanging))


def _print_help(*, wrap: bool) -> None:
    column = max(len(usage.form) for usage in HELP)
    _say("Commands:", wrap=wrap)
    for usage in HELP:
        _say(f"  {usage.form:<{column}}  {usage.summary}", wrap=wrap, hanging=" " * (column + 4))
