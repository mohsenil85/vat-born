"""Runs the game the way a player does: a fresh process, commands on stdin, text on stdout."""

import os
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import pytest


@dataclass(frozen=True, slots=True)
class Result:
    code: int
    out: str
    err: str


def run(args: Sequence[str], commands: Sequence[str], *, data_home: Path, hash_seed: int = 0) -> Result:
    """Run `vat-born ARGS` with COMMANDS on stdin. XDG_DATA_HOME points at DATA_HOME, so a test never touches the
    player's worlds even when it leaves out --world."""
    done = subprocess.run(  # noqa: S603 - runs this repo's game with arguments the tests choose
        [sys.executable, "-m", "vat_born", *args],
        input="".join(f"{command}\n" for command in commands),
        capture_output=True,
        text=True,
        env=os.environ | {"PYTHONHASHSEED": str(hash_seed), "XDG_DATA_HOME": str(data_home)},
        check=False,
    )
    return Result(done.returncode, done.stdout, done.stderr)


def play(world: Path, seed: int, commands: Sequence[str], *, hash_seed: int = 0) -> str:
    """Play COMMANDS on the world file WORLD, with the log shown, and return the transcript. Fails the test if the
    game exits with an error or writes anything to stderr."""
    args = ["--world", str(world), "--seed", str(seed), "--show-log"]
    result = run(args, commands, data_home=world.parent / "data", hash_seed=hash_seed)
    if result.code != 0 or result.err:
        pytest.fail(f"vat-born exited with {result.code}:\n{result.err}", pytrace=False)
    return result.out
