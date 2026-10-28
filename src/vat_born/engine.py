"""The engine: resolves intents against an open world. A free intent reads a `View` and reports. A timed intent records
facts on a `Txn`, in one transaction, and always takes time."""

from dataclasses import dataclass
from pathlib import Path
from typing import Self, assert_never, final

from vat_born.clock import Tick, game_time, ticks_until
from vat_born.content import Content
from vat_born.dice import Dice
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
    Report,
    Resumed,
    StatusReport,
    TimePassed,
    WorldCreated,
)
from vat_born.intents import (
    FreeIntent,
    Intent,
    Look,
    Move,
    Status,
    TimedIntent,
    Wait,
    WaitUntil,
    Where,
)
from vat_born.store import LogEntry, Store, Txn, View, WorldError
from vat_born.world import CharacterId, Layer, NodeId


@dataclass(frozen=True, slots=True)
class Turn:
    """What one command did: the events for the frontend, and the entries it appended to the log."""

    events: tuple[Event, ...]
    logged: tuple[LogEntry, ...] = ()


@final
class Game:
    """An open world. Create or resume one, call `act` once per command, then `close` it."""

    def __init__(self, store: Store, dice: Dice) -> None:
        self._store = store
        self._dice = dice

    @classmethod
    def create(cls, path: Path, seed: int, content: Content) -> tuple[Self, Turn]:
        """Make a new world at PATH, which must not exist yet, and wake its first clone in the home section."""
        home = content.home
        nodes = {kind: NodeId(n) for n, kind in enumerate(home.places, start=1)}
        start = content.place(home.start)
        store = Store.create(path)
        dice = Dice(seed)
        try:
            with store.transaction(dice) as txn:
                txn.record(WorldCreated(seed))
                for kind in home.places:
                    place = content.place(kind)
                    txn.record(PlaceAdded(nodes[kind], Layer.DECKS, kind, place.name, place.description))
                for way in home.paths:
                    txn.record(PathAdded(nodes[way.origin], nodes[way.to], way.direction, way.ticks))
                txn.record(CloneWoke(run=1, pc=CharacterId(1), place=nodes[home.start], place_name=start.name))
            turn = Turn((*txn.facts, _look(store.view())), txn.logged)
        except BaseException:
            store.close()
            path.unlink()  # a half-made world would only fail later, as "not a world"
            raise
        return cls(store, dice), turn

    @classmethod
    def resume(cls, path: Path, seed: int | None) -> tuple[Self, Turn]:
        """Open the existing world at PATH. If SEED is given, it must be the world's."""
        store = Store.open(path)
        view = store.view()
        stored = view.seed()
        if seed is not None and seed != stored:
            store.close()
            raise WorldError(f"{path} is the world for seed {stored}, not {seed}")
        report = Resumed(stored, view.run(), game_time(view.tick()), view.pc_place().name)
        return cls(store, Dice(stored)), Turn((report,))

    def act(self, intent: Intent) -> Turn:
        match intent:
            case Status() | Where() | Look():
                return Turn(_resolve_free(intent, self._store.view()))
            case Wait() | WaitUntil() | Move():
                return self._timed(intent)
            case _:
                assert_never(intent)

    def close(self) -> None:
        self._store.close()

    def _timed(self, intent: TimedIntent) -> Turn:
        with self._store.transaction(self._dice) as txn:
            start = txn.tick()
            reports = _resolve_timed(intent, txn)
            end = txn.tick()
        if not txn.facts:  # refused: nothing changed and no time passed
            assert reports, f"{intent} did nothing and said nothing"
            return Turn(reports)
        assert end > start, f"{intent} took no time"
        before, after = game_time(start), game_time(end)
        notices = (PhaseChanged(before, after),) if after != before else ()
        return Turn((*txn.facts, *notices, *reports), txn.logged)


def _resolve_free(intent: FreeIntent, view: View) -> tuple[Event, ...]:
    match intent:
        case Status():
            return (StatusReport(game_time(view.tick()), view.run()),)
        case Where():
            return (PlaceReport(view.pc_place().name),)
        case Look():
            return (_look(view),)
        case _:
            assert_never(intent)


def _resolve_timed(intent: TimedIntent, txn: Txn) -> tuple[Report, ...]:
    """Do what the intent says, recording its facts, and return the reports to show after them. A refused action
    records nothing and returns the report that says why."""
    match intent:
        case Wait(ticks=ticks):
            start = txn.tick()
            txn.record(TimePassed(start, Tick(start + ticks), Activity.WAITING))
            return ()
        case WaitUntil(minute_of_day=minute):
            start = txn.tick()
            txn.record(TimePassed(start, Tick(start + ticks_until(start, minute)), Activity.WAITING))
            return ()
        case Move(direction=direction):
            place = txn.pc_place()
            way = next((out for out in txn.exits(place.id) if out.direction == direction), None)
            if way is None:
                return (NoPath(direction),)
            start = txn.tick()
            txn.record(TimePassed(start, Tick(start + way.ticks), Activity.WALKING))
            txn.record(PcMoved(txn.pc(), place.id, way.to, direction, way.place_name))
            return (_look(txn),)
        case _:
            assert_never(intent)


def _look(view: View) -> LookReport:
    """What a clone sees when it looks, arrives somewhere, or wakes."""
    place = view.pc_place()
    return LookReport(place.name, place.description, view.exits(place.id))
