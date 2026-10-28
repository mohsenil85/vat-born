"""The engine: resolves intents against an open world. A free intent reads a `View` and reports. A timed intent records
facts on a `Txn`, in one transaction, and always takes time."""

import heapq
from dataclasses import dataclass
from pathlib import Path
from typing import Self, assert_never, final

from vat_born import worldgen
from vat_born.clock import Tick, game_time, ticks_until
from vat_born.content import Content
from vat_born.dice import Dice
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
    Report,
    Resumed,
    Route,
    StatusReport,
    TimePassed,
    WorldCreated,
)
from vat_born.intents import (
    FreeIntent,
    Intent,
    Look,
    Map,
    Move,
    Status,
    TimedIntent,
    Wait,
    WaitUntil,
    Where,
)
from vat_born.needs import Need, level, tick
from vat_born.store import LogEntry, Store, Txn, View, WorldError
from vat_born.world import CharacterId, Direction, Layer, NodeId


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
                stream = txn.stream("worldgen", "decks")
                beyond = worldgen.decks(content, stream, nodes[home.gate.place], NodeId(len(home.places) + 1))
                for fact in beyond:
                    txn.record(fact)
                txn.record(CloneWoke(run=1, pc=CharacterId(1), place=nodes[home.start], place_name=start.name))
                txn.record(PlaceVisited(nodes[home.start]))
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
            case Status() | Where() | Look() | Map():
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
            needs = view.needs()
            levels = tuple(NeedLevel(need, level(need, needs.count(need))) for need in Need)
            return (StatusReport(game_time(view.tick()), view.run(), levels),)
        case Where():
            return (PlaceReport(view.pc_place().name, _route_home(view)),)
        case Look():
            return (_look(view),)
        case Map():
            here = view.pc_place().id
            entries = tuple(
                MapEntry(place.name, place.id == here, view.exits(place.id))
                for place in (view.place(node) for node in view.visited())
            )
            return (MapReport(entries),)
        case _:
            assert_never(intent)


def _resolve_timed(intent: TimedIntent, txn: Txn) -> tuple[Report, ...]:
    """Do what the intent says, recording its facts, and return the reports to show after them. A refused action
    records nothing and returns the report that says why."""
    match intent:
        case Wait(ticks=ticks):
            return _pass(txn, ticks, Activity.WAITING, interruptible=True)
        case WaitUntil(minute_of_day=minute):
            return _pass(txn, ticks_until(txn.tick(), minute), Activity.WAITING, interruptible=True)
        case Move(direction=direction):
            place = txn.pc_place()
            way = next((out for out in txn.exits(place.id) if out.direction == direction), None)
            if way is None:
                return (NoPath(direction),)
            reports = _pass(txn, way.ticks, Activity.WALKING, interruptible=False)
            txn.record(PcMoved(txn.pc(), place.id, way.to, direction, way.place_name))
            if not txn.is_visited(way.to):
                txn.record(PlaceVisited(way.to))
            return (*reports, _look(txn))
        case _:
            assert_never(intent)


def _pass(txn: Txn, ticks: int, activity: Activity, *, interruptible: bool) -> tuple[Report, ...]:
    """Let TICKS ticks pass for ACTIVITY, one at a time. This is the scheduler (design §6): every time-driven system
    takes its turn each tick, in a fixed order. Needs are the only system so far; the hazard clocks (M4) and the
    allies (M7) take their turns in this loop too. A need getting worse is reported as it happens, and stops an
    interruptible action with ticks left, so the player can react."""
    assert ticks > 0, "an action takes at least one tick"
    start = txn.tick()
    pc = txn.pc()
    needs = txn.needs()
    reports: list[Report] = []
    passed = 0
    for _ in range(ticks):
        stepped = tick(needs)
        passed += 1
        worsened = False
        for need in Need:
            now = level(need, stepped.count(need))
            if now > level(need, needs.count(need)):
                reports.append(NeedWorsened(need, now))
                worsened = True
        needs = stepped
        if worsened and interruptible and passed < ticks:
            reports.append(Interrupted(activity))
            break
    txn.record(TimePassed(start, Tick(start + passed), activity))
    txn.record(NeedsChanged(pc, needs.thirst, needs.hunger, needs.fatigue))
    return tuple(reports)


def _look(view: View) -> LookReport:
    """What a clone sees when it looks, arrives somewhere, or wakes."""
    place = view.pc_place()
    return LookReport(place.name, place.description, view.exits(place.id))


# Definition order is the order routes break ties in.
_WAYS = tuple(Direction)


def _route_home(view: View) -> Route | None:
    """The PC's route home over known ground, meaning paths between two visited places: a clone can't be sent over
    ground nobody has walked. Shortest by total ticks; among equally short ones, the route whose steps come first
    in `Direction` order, step by step, which is what Dijkstra over the priority `(ticks, steps)` finds. Every edge
    adds ticks and lengthens the steps, so a popped node's route can't be improved on later."""
    start = view.pc_place().id
    home = view.home().id
    if start == home:
        return Route((), 0)
    known = frozenset(view.visited())
    step_of = {way: n for n, way in enumerate(_WAYS)}
    walked: set[NodeId] = set()
    frontier: list[tuple[int, tuple[int, ...], NodeId]] = [(0, (), start)]
    while frontier:
        ticks, steps, node = heapq.heappop(frontier)
        if node == home:
            return Route(tuple(_WAYS[n] for n in steps), ticks)
        if node in walked:
            continue  # a better route here was already expanded
        walked.add(node)
        for out in view.exits(node):
            if out.to in known:
                heapq.heappush(frontier, (ticks + out.ticks, (*steps, step_of[out.direction]), out.to))
    return None
