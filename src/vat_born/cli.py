"""The terminal frontend: picks the world file, then reads commands one per line and prints what happened. The only
module that prints."""

import argparse
import contextlib
import importlib
import os
import secrets
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import cast

from vat_born.commands import HELP, Help, Quit, Rejected, parse
from vat_born.content import Content, load_content
from vat_born.engine import Game, Turn
from vat_born.render import render
from vat_born.store import WorldError

_NEW_SEEDS = 1_000_000  # random seeds for new worlds stay below this, so they're easy to read and type


def main(argv: Sequence[str] | None = None) -> int:
    args = _arguments().parse_args(argv)
    world = cast("Path | None", args.world)
    seed = cast("int | None", args.seed)
    show_log = cast("bool", args.show_log)
    try:
        game, turn = _open(world, seed, load_content())
    except WorldError as error:
        print(f"vat-born: {error}", file=sys.stderr)
        return 2
    try:
        _show(turn, show_log=show_log)
        print('Type "help" for the commands.')
        _play(game, show_log=show_log)
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
    parser.add_argument("--show-log", action="store_true", help="after each command, print what it added to the log")
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
        return Game.resume(path, seed)
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


def _play(game: Game, *, show_log: bool) -> None:
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
                _print_help()
            case Rejected(message=message):
                print(message)
            case intent:
                _show(game.act(intent), show_log=show_log)


def _read(*, interactive: bool) -> str | None:
    """The next line of input, or None at the end of it."""
    if not interactive:
        return sys.stdin.readline() or None
    try:
        return input("> ")
    except EOFError:
        print()
        return None


def _show(turn: Turn, *, show_log: bool) -> None:
    for event in turn.events:
        for text in render(event):
            print(text)
    if show_log:
        for entry in turn.logged:
            print(f"  | t{entry.tick} {entry.kind} {entry.payload}")


def _print_help() -> None:
    width = max(len(usage.form) for usage in HELP)
    print("Commands:")
    for usage in HELP:
        print(f"  {usage.form:<{width}}  {usage.summary}")
