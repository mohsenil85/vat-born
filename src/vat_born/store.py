"""The world file: its SQLite schema, the read-only `View` that free actions get, and the `Txn` that timed actions
change the world through. All SQL lives here, with `?` parameters."""

import dataclasses
import json
import re
import sqlite3
from collections import Counter
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Self, assert_never, cast, final

from vat_born.clock import Tick
from vat_born.dice import Dice, Key, Odds, Stream
from vat_born.events import CloneWoke, Fact, PlaceAdded, Rolled, TimePassed, WorldCreated
from vat_born.world import NodeId, Place

# Bump this with any change to the schema. A world made under another version refuses to open: while worlds are
# disposable there are no migrations.
SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE world (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    seed INTEGER NOT NULL,
    schema_version INTEGER NOT NULL,
    tick INTEGER NOT NULL
) STRICT;

CREATE TABLE nodes (
    id INTEGER PRIMARY KEY,
    layer TEXT NOT NULL,
    kind TEXT NOT NULL,
    name TEXT NOT NULL
) STRICT;

CREATE TABLE characters (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL,
    node INTEGER NOT NULL REFERENCES nodes (id)
) STRICT;

-- One row per clone: the run counter (design §4).
CREATE TABLE runs (
    n INTEGER PRIMARY KEY,
    pc INTEGER NOT NULL REFERENCES characters (id),
    started_tick INTEGER NOT NULL
) STRICT;

-- Every fact, in order.
CREATE TABLE log (
    seq INTEGER PRIMARY KEY,
    tick INTEGER NOT NULL,
    kind TEXT NOT NULL,
    payload TEXT NOT NULL
) STRICT;

CREATE TRIGGER log_no_update BEFORE UPDATE ON log
BEGIN SELECT RAISE(ABORT, 'the event log is append-only'); END;

CREATE TRIGGER log_no_delete BEFORE DELETE ON log
BEGIN SELECT RAISE(ABORT, 'the event log is append-only'); END;
"""


class WorldError(Exception):
    """A world file can't be created or opened. The message is meant for the player."""


@dataclass(frozen=True, slots=True)
class LogEntry:
    """One row of the event log, as stored."""

    tick: Tick
    kind: str
    payload: str


class View:
    """Read access to the world. Outside a transaction SQLite holds the connection read-only, so a free action that
    tries to write fails."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn: sqlite3.Connection = conn

    def seed(self) -> int:
        row = cast("tuple[int] | None", self._conn.execute("SELECT seed FROM world").fetchone())
        assert row is not None, "the world table is empty"
        return row[0]

    def tick(self) -> Tick:
        row = cast("tuple[int] | None", self._conn.execute("SELECT tick FROM world").fetchone())
        assert row is not None, "the world table is empty"
        return Tick(row[0])

    def run(self) -> int:
        """The current clone's number, counting from 1."""
        row = cast("tuple[int | None]", self._conn.execute("SELECT max(n) FROM runs").fetchone())
        assert row[0] is not None, "no clone has woken"
        return row[0]

    def pc_place(self) -> Place:
        row = cast(
            "tuple[int, str] | None",
            self._conn.execute(
                "SELECT nodes.id, nodes.name FROM runs"
                " JOIN characters ON characters.id = runs.pc"
                " JOIN nodes ON nodes.id = characters.node"
                " ORDER BY runs.n DESC LIMIT 1",
            ).fetchone(),
        )
        assert row is not None, "no clone has woken"
        return Place(NodeId(row[0]), row[1])


@final
class Txn(View):
    """Write access for one timed action, inside one SQLite transaction. Recording a fact is the only way to change
    the world: `record` applies the fact and appends it to the log."""

    def __init__(self, conn: sqlite3.Connection, dice: Dice) -> None:
        super().__init__(conn)
        self._dice = dice
        self._rolls: Counter[tuple[Key, ...]] = Counter()
        self._facts: list[Fact] = []
        self._logged: list[LogEntry] = []

    @property
    def facts(self) -> tuple[Fact, ...]:
        return tuple(self._facts)

    @property
    def logged(self) -> tuple[LogEntry, ...]:
        return tuple(self._logged)

    def record(self, fact: Fact) -> None:
        _apply(self._conn, fact)
        entry = LogEntry(self.tick(), _kind(fact), json.dumps(dataclasses.asdict(fact)))
        self._conn.execute(
            "INSERT INTO log (tick, kind, payload) VALUES (?, ?, ?)", (entry.tick, entry.kind, entry.payload)
        )
        self._facts.append(fact)
        self._logged.append(entry)

    def roll(self, odds: Odds, purpose: str, *key: Key) -> bool:
        """Roll against ODDS, as in `txn.roll(odds, "search", place)`, and log it. The draw is keyed by PURPOSE, KEY,
        and the current tick, so no other roll can shift it."""
        keyed = (purpose, self.tick(), *key)
        repeat = self._rolls[keyed]  # the same key rolled twice in one action gets a fresh draw
        self._rolls[keyed] += 1
        value = self._dice.stream("roll", *keyed, repeat).random()
        success = value < odds.chance
        self.record(Rolled(purpose, key, odds, odds.chance, value, success))
        return success

    def stream(self, purpose: str, *key: Key) -> Stream:
        """A generator for draws that aren't chances, such as worldgen's choices. Unlike `roll`, the key doesn't
        include the tick: add it to KEY for a draw made during play."""
        return self._dice.stream(purpose, *key)


@final
class Store:
    """An open world file, read-only except inside `transaction`."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._conn.execute("PRAGMA query_only = ON")

    @classmethod
    def create(cls, path: Path) -> Self:
        """Make an empty world file at PATH, which must not exist yet."""
        assert not path.exists(), f"{path} already exists"
        try:
            conn = _connect(path)
            conn.executescript(_SCHEMA)
        except sqlite3.Error as error:
            raise WorldError(f"can't create a world at {path}: {error}") from error
        return cls(conn)

    @classmethod
    def open(cls, path: Path) -> Self:
        """Open the world file at PATH, refusing anything this version of the game can't play."""
        try:
            conn = _connect(path)
        except sqlite3.Error as error:
            raise WorldError(f"can't open {path}: {error}") from error
        try:
            row = cast("tuple[int] | None", conn.execute("SELECT schema_version FROM world").fetchone())
        except sqlite3.DatabaseError as error:  # not SQLite at all, or SQLite without our tables
            conn.close()
            raise WorldError(f"{path} is not a Vat-Born world") from error
        if row is None:
            conn.close()
            raise WorldError(f"{path} is not a Vat-Born world")
        if row[0] != SCHEMA_VERSION:
            conn.close()
            raise WorldError(
                f"{path} was made by another version of the game (schema {row[0]}, not {SCHEMA_VERSION}); "
                "start a new world"
            )
        return cls(conn)

    def view(self) -> View:
        return View(self._conn)

    @contextmanager
    def transaction(self, dice: Dice) -> Generator[Txn]:
        """One timed action: everything it records commits together, or not at all."""
        self._conn.execute("PRAGMA query_only = OFF")
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            yield Txn(self._conn, dice)
        except BaseException:
            self._conn.execute("ROLLBACK")
            raise
        else:
            self._conn.execute("COMMIT")
        finally:
            self._conn.execute("PRAGMA query_only = ON")

    def close(self) -> None:
        self._conn.close()


def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path, autocommit=True)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _apply(conn: sqlite3.Connection, fact: Fact) -> None:
    match fact:
        case WorldCreated(seed=seed):
            conn.execute(
                "INSERT INTO world (id, seed, schema_version, tick) VALUES (1, ?, ?, 0)", (seed, SCHEMA_VERSION)
            )
        case PlaceAdded(place=place, layer=layer, kind=kind, name=name):
            conn.execute("INSERT INTO nodes (id, layer, kind, name) VALUES (?, ?, ?, ?)", (place, layer, kind, name))
        case CloneWoke(run=run, pc=pc, place=place):
            conn.execute("INSERT INTO characters (id, kind, node) VALUES (?, 'pc', ?)", (pc, place))
            conn.execute("INSERT INTO runs (n, pc, started_tick) SELECT ?, ?, tick FROM world", (run, pc))
        case TimePassed(start=start, end=end):
            assert end > start, "time only moves forward"
            moved = conn.execute("UPDATE world SET tick = ? WHERE tick = ?", (end, start))
            assert moved.rowcount == 1, f"time passed from tick {start}, which isn't now"
        case Rolled():
            pass  # a roll changes nothing by itself; what follows from it is a fact of its own
        case _:
            assert_never(fact)


def _kind(fact: Fact) -> str:
    """The log's name for a fact: `TimePassed` is `time_passed`."""
    return re.sub(r"(?<=[a-z])(?=[A-Z])", "_", type(fact).__name__).lower()
