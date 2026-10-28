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
from vat_born.events import (
    AirRepaired,
    Ate,
    Body,
    BreathChanged,
    ClockAdvanced,
    ClockStarted,
    CloneWoke,
    DrankFrom,
    Fact,
    ItemDropped,
    ItemFilled,
    ItemFound,
    ItemHidden,
    ItemTaken,
    NeedsChanged,
    PathAdded,
    PcDied,
    PcEscaped,
    PcMoved,
    PcWounded,
    PlaceAdded,
    PlaceSearchedBare,
    PlaceVisited,
    PredatorAttacked,
    PredatorDrivenOff,
    PredatorRetreated,
    RepairWorked,
    Rolled,
    Sign,
    SignLeft,
    SignSeen,
    TimePassed,
    WorldCreated,
    WoundsChanged,
)
from vat_born.hazards import Clock
from vat_born.needs import Needs
from vat_born.world import CharacterId, Direction, Exit, Item, ItemId, ItemKind, NodeId, Place, PlaceKind

# SQL would sort the direction words alphabetically, so the order of a place's paths is set in Python instead.
_DIRECTION_ORDER = {way: n for n, way in enumerate(Direction)}

# The same goes for the clocks, whose names sort neither in `Clock` order nor usefully by stage.
_CLOCK_ORDER = {clock: n for n, clock in enumerate(Clock)}


def _signs(rows: list[tuple[str, int]]) -> tuple[Sign, ...]:
    """Sign rows (clock, stage), sorted into clock then stage order."""
    signs = (Sign(Clock(row[0]), row[1]) for row in rows)
    return tuple(sorted(signs, key=lambda sign: (_CLOCK_ORDER[sign.clock], sign.stage)))


# Bump this with any change to the schema. A world made under another version refuses to open: while worlds are
# disposable there are no migrations.
SCHEMA_VERSION = 12

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
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    water INTEGER NOT NULL CHECK (water IN (0, 1))
) STRICT;

CREATE TABLE characters (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL,
    node INTEGER NOT NULL REFERENCES nodes (id),
    thirst INTEGER NOT NULL,
    hunger INTEGER NOT NULL,
    fatigue INTEGER NOT NULL,
    wounds INTEGER NOT NULL CHECK (wounds >= 0),
    breath INTEGER NOT NULL CHECK (breath >= 0),
    came_from INTEGER REFERENCES nodes (id)
) STRICT;

CREATE TABLE edges (
    from_node INTEGER NOT NULL REFERENCES nodes (id),
    to_node INTEGER NOT NULL REFERENCES nodes (id),
    direction TEXT NOT NULL,
    ticks INTEGER NOT NULL CHECK (ticks > 0),
    PRIMARY KEY (from_node, direction)
) STRICT;

-- One row per clone: the run counter (design §4) and where this one woke, which is its way home. DIED, CAUSE,
-- and DEATH_NODE are set when the clone dies; they are NULL while it lives.
CREATE TABLE runs (
    n INTEGER PRIMARY KEY,
    pc INTEGER NOT NULL REFERENCES characters (id),
    home INTEGER NOT NULL REFERENCES nodes (id),
    started_tick INTEGER NOT NULL,
    died INTEGER,
    cause TEXT,
    death_node INTEGER REFERENCES nodes (id)
) STRICT;

-- The places a clone has been, kept for the next one (design §4: a new clone knows places, not details).
CREATE TABLE visited (
    node INTEGER PRIMARY KEY REFERENCES nodes (id),
    tick INTEGER NOT NULL
) STRICT;

-- Every item in the world. Each lies in a place, hidden in the place's search pool until a search turns it up and
-- then in the open, or is carried by a character. DRINKS is the water in it now, for the things that hold any.
CREATE TABLE items (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL,
    node INTEGER REFERENCES nodes (id),
    holder INTEGER REFERENCES characters (id),
    hidden INTEGER NOT NULL CHECK (hidden IN (0, 1)),
    drinks INTEGER NOT NULL CHECK (drinks >= 0),
    CHECK ((node IS NULL) <> (holder IS NULL)),
    CHECK (hidden = 0 OR node IS NOT NULL)
) STRICT;

-- The places each clone has searched until nothing was left. The knowledge is the clone's, not the world's: a new
-- clone has to search again (design §4: a new clone knows places, not details).
CREATE TABLE searched_bare (
    run INTEGER NOT NULL REFERENCES runs (n),
    node INTEGER NOT NULL REFERENCES nodes (id),
    tick INTEGER NOT NULL,
    PRIMARY KEY (run, node)
) STRICT;

-- Each hazard clock (design §7.2): its stage, the tick of its last change, and, for a clock being repaired, the
-- work done so far, in ticks.
CREATE TABLE clocks (
    clock TEXT PRIMARY KEY,
    stage INTEGER NOT NULL CHECK (stage BETWEEN 0 AND 4),
    since INTEGER NOT NULL,
    progress INTEGER NOT NULL CHECK (progress >= 0)
) STRICT;

-- The signs the clocks have left, one per clock and stage. A sign is in a place, or is heard (node NULL).
CREATE TABLE signs (
    clock TEXT NOT NULL REFERENCES clocks (clock),
    stage INTEGER NOT NULL,
    node INTEGER REFERENCES nodes (id),
    tick INTEGER NOT NULL,
    PRIMARY KEY (clock, stage)
) STRICT;

-- The signs each clone has come across. Like a place searched bare, the knowledge is the clone's.
CREATE TABLE signs_seen (
    run INTEGER NOT NULL REFERENCES runs (n),
    clock TEXT NOT NULL,
    stage INTEGER NOT NULL,
    tick INTEGER NOT NULL,
    PRIMARY KEY (run, clock, stage)
) STRICT;

-- The attack under way, if any: the predator has the PC cornered in this place until it fights or flees.
CREATE TABLE attack (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    node INTEGER NOT NULL REFERENCES nodes (id),
    tick INTEGER NOT NULL
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


@dataclass(frozen=True, slots=True)
class ClockState:
    """One hazard clock as it stands: its stage, the tick it last changed, and the repair work done on it."""

    clock: Clock
    stage: int
    since: Tick
    progress: int


@dataclass(frozen=True, slots=True)
class PlaceWithKind:
    """A place and its kind, as worldgen's tables and the clocks' signs pick places by."""

    place: NodeId
    kind: PlaceKind


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
            "tuple[int, str, str, int] | None",
            self._conn.execute(
                "SELECT nodes.id, nodes.name, nodes.description, nodes.water FROM runs"
                " JOIN characters ON characters.id = runs.pc"
                " JOIN nodes ON nodes.id = characters.node"
                " ORDER BY runs.n DESC LIMIT 1",
            ).fetchone(),
        )
        assert row is not None, "no clone has woken"
        return Place(NodeId(row[0]), row[1], row[2], bool(row[3]))

    def pc(self) -> CharacterId:
        """The current clone's character."""
        row = cast(
            "tuple[int] | None",
            self._conn.execute("SELECT runs.pc FROM runs ORDER BY runs.n DESC LIMIT 1").fetchone(),
        )
        assert row is not None, "no clone has woken"
        return CharacterId(row[0])

    def next_pc(self) -> CharacterId:
        """The character ID the next clone wakes as: one more than the highest so far."""
        row = cast("tuple[int | None]", self._conn.execute("SELECT max(id) FROM characters").fetchone())
        return CharacterId((row[0] or 0) + 1)

    def needs(self) -> Needs:
        """The current clone's needs: ticks since each was last answered."""
        row = cast(
            "tuple[int, int, int] | None",
            self._conn.execute(
                "SELECT characters.thirst, characters.hunger, characters.fatigue FROM runs"
                " JOIN characters ON characters.id = runs.pc"
                " ORDER BY runs.n DESC LIMIT 1",
            ).fetchone(),
        )
        assert row is not None, "no clone has woken"
        return Needs(*row)

    def wounds(self) -> int:
        """The current clone's wounds: the ticks of healing they have left."""
        row = cast(
            "tuple[int] | None",
            self._conn.execute(
                "SELECT characters.wounds FROM runs"
                " JOIN characters ON characters.id = runs.pc"
                " ORDER BY runs.n DESC LIMIT 1",
            ).fetchone(),
        )
        assert row is not None, "no clone has woken"
        return row[0]

    def breath(self) -> int:
        """The current clone's breath: ticks spent in bad air, eased by good air."""
        row = cast(
            "tuple[int] | None",
            self._conn.execute(
                "SELECT characters.breath FROM runs"
                " JOIN characters ON characters.id = runs.pc"
                " ORDER BY runs.n DESC LIMIT 1",
            ).fetchone(),
        )
        assert row is not None, "no clone has woken"
        return row[0]

    def came_from(self) -> NodeId | None:
        """Where the current clone last walked from, or None if it hasn't walked since it woke."""
        row = cast(
            "tuple[int | None] | None",
            self._conn.execute(
                "SELECT characters.came_from FROM runs"
                " JOIN characters ON characters.id = runs.pc"
                " ORDER BY runs.n DESC LIMIT 1",
            ).fetchone(),
        )
        assert row is not None, "no clone has woken"
        return None if row[0] is None else NodeId(row[0])

    def dead(self) -> bool:
        """Whether the current clone has died."""
        row = cast(
            "tuple[int | None] | None",
            self._conn.execute("SELECT died FROM runs ORDER BY n DESC LIMIT 1").fetchone(),
        )
        assert row is not None, "no clone has woken"
        return row[0] is not None

    def attack(self) -> NodeId | None:
        """Where the predator has the PC cornered, or None when no attack is under way."""
        row = cast("tuple[int] | None", self._conn.execute("SELECT node FROM attack WHERE id = 1").fetchone())
        return None if row is None else NodeId(row[0])

    def exits(self, place: NodeId) -> tuple[Exit, ...]:
        """The paths out of PLACE, in `Direction` order, each marked for whether its far end has been visited."""
        rows = cast(
            "list[tuple[str, int, int, str, int | None]]",
            self._conn.execute(
                "SELECT edges.direction, edges.to_node, edges.ticks, nodes.name, visited.node FROM edges"
                " JOIN nodes ON nodes.id = edges.to_node"
                " LEFT JOIN visited ON visited.node = edges.to_node"
                " WHERE edges.from_node = ?",
                (place,),
            ).fetchall(),
        )
        return tuple(
            sorted(
                (Exit(Direction(row[0]), NodeId(row[1]), row[3], row[2], row[4] is not None) for row in rows),
                key=lambda way: _DIRECTION_ORDER[way.direction],
            )
        )

    def visited(self) -> tuple[NodeId, ...]:
        """The places a clone has been, in ascending node ID order."""
        rows = cast("list[tuple[int]]", self._conn.execute("SELECT node FROM visited ORDER BY node").fetchall())
        return tuple(NodeId(row[0]) for row in rows)

    def is_visited(self, place: NodeId) -> bool:
        row = cast(
            "tuple[int] | None", self._conn.execute("SELECT node FROM visited WHERE node = ?", (place,)).fetchone()
        )
        return row is not None

    def place(self, node: NodeId) -> Place:
        row = cast(
            "tuple[int, str, str, int] | None",
            self._conn.execute("SELECT id, name, description, water FROM nodes WHERE id = ?", (node,)).fetchone(),
        )
        assert row is not None, f"no place {node}"
        return Place(NodeId(row[0]), row[1], row[2], bool(row[3]))

    def home(self) -> Place:
        """Where the current clone woke."""
        row = cast(
            "tuple[int, str, str, int] | None",
            self._conn.execute(
                "SELECT nodes.id, nodes.name, nodes.description, nodes.water FROM runs"
                " JOIN nodes ON nodes.id = runs.home"
                " ORDER BY runs.n DESC LIMIT 1",
            ).fetchone(),
        )
        assert row is not None, "no clone has woken"
        return Place(NodeId(row[0]), row[1], row[2], bool(row[3]))

    def items_at(self, place: NodeId) -> tuple[Item, ...]:
        """The items lying in the open at PLACE, in ID order."""
        rows = cast(
            "list[tuple[int, str, int]]",
            self._conn.execute(
                "SELECT id, kind, drinks FROM items WHERE node = ? AND hidden = 0 ORDER BY id", (place,)
            ).fetchall(),
        )
        return tuple(Item(ItemId(row[0]), ItemKind(row[1]), row[2]) for row in rows)

    def carried(self) -> tuple[Item, ...]:
        """What the current clone carries, in ID order."""
        rows = cast(
            "list[tuple[int, str, int]]",
            self._conn.execute(
                "SELECT id, kind, drinks FROM items WHERE holder ="
                " (SELECT pc FROM runs ORDER BY n DESC LIMIT 1) ORDER BY id"
            ).fetchall(),
        )
        return tuple(Item(ItemId(row[0]), ItemKind(row[1]), row[2]) for row in rows)

    def next_hidden(self, place: NodeId) -> Item | None:
        """The hidden item at PLACE with the lowest ID, or None when nothing is hidden there any more."""
        row = cast(
            "tuple[int, str, int] | None",
            self._conn.execute(
                "SELECT id, kind, drinks FROM items WHERE node = ? AND hidden = 1 ORDER BY id LIMIT 1", (place,)
            ).fetchone(),
        )
        return None if row is None else Item(ItemId(row[0]), ItemKind(row[1]), row[2])

    def searched_bare(self, place: NodeId) -> bool:
        """Whether the current clone has searched PLACE until nothing was left."""
        row = cast(
            "tuple[int] | None",
            self._conn.execute(
                "SELECT node FROM searched_bare WHERE run = (SELECT max(n) FROM runs) AND node = ?", (place,)
            ).fetchone(),
        )
        return row is not None

    def places(self) -> tuple[PlaceWithKind, ...]:
        """Every place with its kind, in node ID order."""
        rows = cast("list[tuple[int, str]]", self._conn.execute("SELECT id, kind FROM nodes ORDER BY id").fetchall())
        return tuple(PlaceWithKind(NodeId(row[0]), PlaceKind(row[1])) for row in rows)

    def clocks(self) -> tuple[ClockState, ...]:
        """The hazard clocks as they stand, in `Clock` order."""
        rows = cast(
            "list[tuple[str, int, int, int]]",
            self._conn.execute("SELECT clock, stage, since, progress FROM clocks").fetchall(),
        )
        standing = {Clock(row[0]): ClockState(Clock(row[0]), row[1], Tick(row[2]), row[3]) for row in rows}
        return tuple(standing[clock] for clock in Clock)

    def signs_at(self, place: NodeId) -> tuple[Sign, ...]:
        """The signs in PLACE, in clock then stage order."""
        rows = cast(
            "list[tuple[str, int]]",
            self._conn.execute("SELECT clock, stage FROM signs WHERE node = ?", (place,)).fetchall(),
        )
        return _signs(rows)

    def signs_seen(self) -> tuple[Sign, ...]:
        """The signs the current clone has come across, in clock then stage order."""
        rows = cast(
            "list[tuple[str, int]]",
            self._conn.execute("SELECT clock, stage FROM signs_seen WHERE run = (SELECT max(n) FROM runs)").fetchall(),
        )
        return _signs(rows)

    def bodies_at(self, place: NodeId) -> tuple[Body, ...]:
        """Every clone that died in PLACE, oldest first, with how long ago it died, in ticks."""
        rows = cast(
            "list[tuple[int, int]]",
            self._conn.execute(
                "SELECT n, (SELECT tick FROM world) - died FROM runs WHERE death_node = ? AND died IS NOT NULL"
                " ORDER BY n",
                (place,),
            ).fetchall(),
        )
        return tuple(Body(run=row[0], ticks=row[1]) for row in rows)


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
        case PlaceAdded(place=place, layer=layer, kind=kind, name=name, description=description, water=water):
            conn.execute(
                "INSERT INTO nodes (id, layer, kind, name, description, water) VALUES (?, ?, ?, ?, ?, ?)",
                (place, layer, kind, name, description, int(water)),
            )
        case CloneWoke(run=run, pc=pc, place=place):
            conn.execute(
                "INSERT INTO characters (id, kind, node, thirst, hunger, fatigue, wounds, breath)"
                " VALUES (?, 'pc', ?, 0, 0, 0, 0, 0)",
                (pc, place),
            )
            conn.execute(
                "INSERT INTO runs (n, pc, home, started_tick) SELECT ?, ?, ?, tick FROM world", (run, pc, place)
            )
        case PathAdded(place=place, to=to, direction=direction, ticks=ticks):
            conn.execute(
                "INSERT INTO edges (from_node, to_node, direction, ticks) VALUES (?, ?, ?, ?)",
                (place, to, direction, ticks),
            )
            conn.execute(
                "INSERT INTO edges (from_node, to_node, direction, ticks) VALUES (?, ?, ?, ?)",
                (to, place, direction.opposite, ticks),
            )
        case PcMoved(pc=pc, origin=origin, destination=destination):
            moved = conn.execute(
                "UPDATE characters SET node = ?, came_from = ? WHERE id = ? AND node = ?",
                (destination, origin, pc, origin),
            )
            assert moved.rowcount == 1, f"character {pc} was not at {origin}"
        case PlaceVisited(place=place):
            # The primary key refuses a second row for one place, so recording a visit twice fails loudly.
            conn.execute("INSERT INTO visited (node, tick) SELECT ?, tick FROM world", (place,))
        case ItemHidden() | ItemFound() | ItemTaken() | ItemDropped():
            _apply_items(conn, fact)
        case Ate() | ItemFilled() | DrankFrom():
            _apply_carried(conn, fact)
        case PlaceSearchedBare(run=run, place=place):
            conn.execute("INSERT INTO searched_bare (run, node, tick) SELECT ?, ?, tick FROM world", (run, place))
        case ClockStarted() | ClockAdvanced() | SignLeft() | SignSeen() | RepairWorked() | AirRepaired():
            _apply_clocks(conn, fact)
        case PredatorAttacked() | PredatorDrivenOff() | PredatorRetreated() | PcEscaped():
            _apply_predator(conn, fact)
        case PcWounded(pc=pc, wounds=wounds) | WoundsChanged(pc=pc, wounds=wounds):
            set_wounds = conn.execute("UPDATE characters SET wounds = ? WHERE id = ?", (wounds, pc))
            assert set_wounds.rowcount == 1, f"no character {pc} to set the wounds of"
        case BreathChanged(pc=pc, breath=breath):
            set_breath = conn.execute("UPDATE characters SET breath = ? WHERE id = ?", (breath, pc))
            assert set_breath.rowcount == 1, f"no character {pc} to grow breathless"
        case PcDied(pc=pc, cause=cause, place=place):
            died = conn.execute(
                "UPDATE runs SET died = (SELECT tick FROM world), cause = ?, death_node = ?"
                " WHERE n = (SELECT max(n) FROM runs) AND pc = ? AND died IS NULL",
                (cause, place, pc),
            )
            assert died.rowcount == 1, f"character {pc} was not the current living clone"
            conn.execute("DELETE FROM attack")  # any attack under way dies with the clone
            # the body stays where it fell, and everything it carried lies in the open around it
            conn.execute("UPDATE items SET node = ?, holder = NULL WHERE holder = ?", (place, pc))
        case TimePassed(start=start, end=end):
            assert end > start, "time only moves forward"
            moved = conn.execute("UPDATE world SET tick = ? WHERE tick = ?", (end, start))
            assert moved.rowcount == 1, f"time passed from tick {start}, which isn't now"
        case NeedsChanged(pc=pc, thirst=thirst, hunger=hunger, fatigue=fatigue):
            moved = conn.execute(
                "UPDATE characters SET thirst = ?, hunger = ?, fatigue = ? WHERE id = ?",
                (thirst, hunger, fatigue, pc),
            )
            assert moved.rowcount == 1, f"no character {pc} to grow needs in"
        case Rolled():
            pass  # a roll changes nothing by itself; what follows from it is a fact of its own
        case _:
            assert_never(fact)


def _apply_clocks(
    conn: sqlite3.Connection, fact: ClockStarted | ClockAdvanced | SignLeft | SignSeen | RepairWorked | AirRepaired
) -> None:
    """Apply the hazard clocks' facts: a clock starts quiet, advances one stage at a time, leaves each stage's
    sign, and is come across by a clone. A repair works its clock's progress along and, done, quiets it and
    clears its signs and every clone's sightings of them."""
    match fact:
        case ClockStarted(clock=clock):
            conn.execute(
                "INSERT INTO clocks (clock, stage, since, progress) VALUES (?, 0, (SELECT tick FROM world), 0)",
                (clock,),
            )
        case ClockAdvanced(clock=clock, stage=stage, at=at):
            moved = conn.execute(
                "UPDATE clocks SET stage = ?, since = ? WHERE clock = ? AND stage = ?",
                (stage, at, clock, stage - 1),
            )
            assert moved.rowcount == 1, f"clock {clock} was not one stage below {stage}"
        case SignLeft(clock=clock, stage=stage, place=place, at=at):
            conn.execute("INSERT INTO signs (clock, stage, node, tick) VALUES (?, ?, ?, ?)", (clock, stage, place, at))
        case SignSeen(run=run, clock=clock, stage=stage):
            conn.execute(
                "INSERT INTO signs_seen (run, clock, stage, tick) SELECT ?, ?, ?, tick FROM world",
                (run, clock, stage),
            )
        case RepairWorked(progress=progress):
            worked = conn.execute(
                "UPDATE clocks SET progress = ? WHERE clock = ? AND progress < ?", (progress, Clock.AIR, progress)
            )
            assert worked.rowcount == 1, f"the air clock's progress already stood at {progress}"
        case AirRepaired():
            fixed = conn.execute(
                "UPDATE clocks SET stage = 0, since = (SELECT tick FROM world), progress = 0 WHERE clock = ?",
                (Clock.AIR,),
            )
            assert fixed.rowcount == 1, "no air clock to repair"
            conn.execute("DELETE FROM signs WHERE clock = ?", (Clock.AIR,))
            conn.execute("DELETE FROM signs_seen WHERE clock = ?", (Clock.AIR,))
        case _:
            assert_never(fact)


def _apply_items(conn: sqlite3.Connection, fact: ItemHidden | ItemFound | ItemTaken | ItemDropped) -> None:
    """Apply the item facts: a thing hidden at worldgen, found by a search, taken up, or dropped."""
    match fact:
        case ItemHidden(item=item, kind=kind, place=place):
            conn.execute(
                "INSERT INTO items (id, kind, node, hidden, drinks) VALUES (?, ?, ?, 1, 0)", (item, kind, place)
            )
        case ItemFound(item=item, place=place):
            found = conn.execute("UPDATE items SET hidden = 0 WHERE id = ? AND node = ? AND hidden = 1", (item, place))
            assert found.rowcount == 1, f"item {item} was not hidden at {place}"
        case ItemTaken(pc=pc, item=item, place=place):
            took = conn.execute(
                "UPDATE items SET node = NULL, holder = ? WHERE id = ? AND node = ? AND hidden = 0", (pc, item, place)
            )
            assert took.rowcount == 1, f"item {item} was not lying in the open at {place}"
        case ItemDropped(pc=pc, item=item, place=place):
            dropped = conn.execute(
                "UPDATE items SET node = ?, holder = NULL WHERE id = ? AND holder = ?", (place, item, pc)
            )
            assert dropped.rowcount == 1, f"character {pc} was not carrying item {item}"
        case _:
            assert_never(fact)


def _apply_predator(
    conn: sqlite3.Connection, fact: PredatorAttacked | PredatorDrivenOff | PredatorRetreated | PcEscaped
) -> None:
    """Apply the attack's facts: the predator corners the PC, and then is driven off, retreats wounded, or loses
    its hold as the PC escapes. Driving it off quiets its clock and clears its signs entirely; a retreat only
    sets the clock back to its cries."""
    match fact:
        case PredatorAttacked(place=place, at=at):
            conn.execute("INSERT INTO attack (id, node, tick) VALUES (1, ?, ?)", (place, at))
        case PredatorDrivenOff():
            _end_attack(conn)
            quieted = conn.execute(
                "UPDATE clocks SET stage = 0, since = (SELECT tick FROM world) WHERE clock = ?",
                (Clock.PREDATOR,),
            )
            assert quieted.rowcount == 1, "no predator clock to quiet"
            conn.execute("DELETE FROM signs WHERE clock = ?", (Clock.PREDATOR,))
            conn.execute("DELETE FROM signs_seen WHERE clock = ?", (Clock.PREDATOR,))
        case PredatorRetreated():
            _end_attack(conn)
            backed = conn.execute(
                "UPDATE clocks SET stage = 3, since = (SELECT tick FROM world) WHERE clock = ?",
                (Clock.PREDATOR,),
            )
            assert backed.rowcount == 1, "no predator clock to set back"
            conn.execute("DELETE FROM signs_seen WHERE clock = ? AND stage = 4", (Clock.PREDATOR,))
        case PcEscaped():
            _end_attack(conn)
        case _:
            assert_never(fact)


def _end_attack(conn: sqlite3.Connection) -> None:
    """The attack is over: exactly one was under way."""
    ended = conn.execute("DELETE FROM attack")
    assert ended.rowcount == 1, "no attack was under way"


def _apply_carried(conn: sqlite3.Connection, fact: Ate | ItemFilled | DrankFrom) -> None:
    """Apply the facts that eat or drink what the PC carries: eating destroys the item and answers hunger, and
    filling and drinking set the drinks in it. Each changes exactly the rows it must, or the assert fails the
    action."""
    match fact:
        case Ate(pc=pc, item=item, hunger=hunger):
            eaten = conn.execute("DELETE FROM items WHERE id = ? AND holder = ?", (item, pc))
            assert eaten.rowcount == 1, f"character {pc} was not carrying item {item}"
            fed = conn.execute("UPDATE characters SET hunger = ? WHERE id = ?", (hunger, pc))
            assert fed.rowcount == 1, f"no character {pc} to feed"
        case ItemFilled(item=item, drinks=drinks) | DrankFrom(item=item, drinks=drinks):
            set_drinks = conn.execute(
                "UPDATE items SET drinks = ? WHERE id = ? AND holder = (SELECT pc FROM runs ORDER BY n DESC LIMIT 1)",
                (drinks, item),
            )
            assert set_drinks.rowcount == 1, f"item {item} was not carried by the clone"
        case _:
            assert_never(fact)


def _kind(fact: Fact) -> str:
    """The log's name for a fact: `TimePassed` is `time_passed`."""
    return re.sub(r"(?<=[a-z])(?=[A-Z])", "_", type(fact).__name__).lower()
