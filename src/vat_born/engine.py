"""The engine: resolves intents against an open world. A free intent reads a `View` and reports. A timed intent records
facts on a `Txn`, in one transaction, and always takes time."""

import heapq
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Self, assert_never, final

from vat_born import worldgen
from vat_born.clock import TICKS_PER_HOUR, GameTime, Phase, Tick, game_time, ticks_until
from vat_born.content import Content
from vat_born.dice import Dice, Modifier, Odds
from vat_born.events import (
    Ate,
    Attacked,
    ClockAdvanced,
    ClockStarted,
    CloneWoke,
    Cornered,
    Danger,
    Dead,
    DrankFrom,
    Event,
    Fact,
    FightStakes,
    FleeStakes,
    HeardCries,
    Interrupted,
    InventoryReport,
    ItemDropped,
    ItemFilled,
    ItemFound,
    ItemHidden,
    ItemStack,
    ItemTaken,
    LookReport,
    MapEntry,
    MapReport,
    NeedEased,
    NeedLevel,
    NeedMet,
    NeedsChanged,
    NeedWorsened,
    NoPath,
    NotCarried,
    NotFood,
    NotHere,
    NothingCarried,
    NothingHere,
    NothingToDrink,
    NothingToFight,
    NothingToFill,
    NothingToFlee,
    NotTired,
    NoWater,
    NowhereLeft,
    PathAdded,
    PcDied,
    PcEscaped,
    PcMoved,
    PcWounded,
    PhaseChanged,
    PlaceAdded,
    PlaceReport,
    PlaceSearchedBare,
    PlaceVisited,
    PredatorAttacked,
    PredatorDrivenOff,
    PredatorRetreated,
    Report,
    Resumed,
    Route,
    Sign,
    SignLeft,
    SignNoticed,
    SignSeen,
    StatusReport,
    TimePassed,
    WhichOne,
    WorldCreated,
    Wounded,
    WoundsChanged,
    WoundsHealed,
)
from vat_born.hazards import Clock, attack_odds, daily_chance, due, is_midnight, may_move, tick_chance
from vat_born.intents import (
    Drink,
    Drop,
    DropAll,
    Eat,
    Fight,
    Fill,
    Flee,
    FreeIntent,
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
    TimedIntent,
    Wait,
    WaitUntil,
    Where,
)
from vat_born.needs import Activity, Need, Needs, heal, level, take_wound, tick, wound_level
from vat_born.store import ClockState, LogEntry, PlaceWithKind, Store, Txn, View, WorldError
from vat_born.world import CharacterId, Direction, Exit, Item, ItemId, ItemKind, Layer, NodeId


@dataclass(frozen=True, slots=True)
class Turn:
    """What one command did: the events for the frontend, and the entries it appended to the log."""

    events: tuple[Event, ...]
    logged: tuple[LogEntry, ...] = ()


@final
class Game:
    """An open world. Create or resume one, call `act` once per command, then `close` it."""

    def __init__(self, store: Store, dice: Dice, content: Content) -> None:
        self._store = store
        self._dice = dice
        self._content = content

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
                    txn.record(PlaceAdded(nodes[kind], Layer.DECKS, kind, place.name, place.description, place.water))
                for way in home.paths:
                    txn.record(PathAdded(nodes[way.origin], nodes[way.to], way.direction, way.ticks))
                stream = txn.stream("worldgen", "decks")
                beyond = worldgen.decks(content, stream, nodes[home.gate.place], NodeId(len(home.places) + 1))
                for fact in beyond:
                    txn.record(fact)
                placed = [(nodes[kind], kind) for kind in home.places]
                placed += [(fact.place, fact.kind) for fact in beyond if isinstance(fact, PlaceAdded)]
                item = 1
                for node, kind in placed:  # node ID order: the home places, then the decks' places from first up
                    for found in worldgen.finds(content, kind, txn.stream("worldgen", "finds", node)):
                        txn.record(ItemHidden(ItemId(item), found, node))
                        item += 1
                for clock in Clock:
                    txn.record(ClockStarted(clock))
                txn.record(CloneWoke(run=1, pc=CharacterId(1), place=nodes[home.start], place_name=start.name))
                txn.record(PlaceVisited(nodes[home.start]))
            turn = Turn((*txn.facts, _look(store.view(), content)), txn.logged)
        except BaseException:
            store.close()
            path.unlink()  # a half-made world would only fail later, as "not a world"
            raise
        return cls(store, dice, content), turn

    @classmethod
    def resume(cls, path: Path, seed: int | None, content: Content) -> tuple[Self, Turn]:
        """Open the existing world at PATH. If SEED is given, it must be the world's."""
        store = Store.open(path)
        view = store.view()
        stored = view.seed()
        if seed is not None and seed != stored:
            store.close()
            raise WorldError(f"{path} is the world for seed {stored}, not {seed}")
        report = Resumed(stored, view.run(), game_time(view.tick()), view.pc_place().name)
        return cls(store, Dice(stored), content), Turn((report,))

    def act(self, intent: Intent) -> Turn:
        view = self._store.view()
        if view.dead():  # M5 builds what comes after a death; until then, only quitting is left
            return Turn((Dead(),))
        match intent:
            case Status() | Where() | Look() | Map() | Inventory():
                return Turn(_resolve_free(intent, view, self._content))
            case Fight() | Flee():
                return self._timed(intent)
            case (
                Wait()
                | WaitUntil()
                | Move()
                | Drink()
                | Fill()
                | Search()
                | Rest()
                | RestUntil()
                | Take()
                | TakeAll()
                | Drop()
                | DropAll()
                | Eat()
            ):
                if view.attack() is not None:  # the predator is on the PC: nothing else will do
                    return Turn((Cornered(),))
                return self._timed(intent)
            case _:
                assert_never(intent)

    def stakes(self, intent: Intent) -> Report | None:
        """What acting on INTENT risks, for the frontend to ask about before acting (design §10.3): the fight and
        the flight from an attack, either of which can kill. Anything else risks nothing that needs asking."""
        match intent:
            case Fight() | Flee():
                view = self._store.view()
                if view.attack() is None:
                    return None
                needs, wounds = view.needs(), view.wounds()
                condition = _condition(needs, wounds)
                survive = None if wound_level(wounds) == 2 else Odds(_SURVIVE_BASE, condition)
                match intent:
                    case Fight():
                        return FightStakes(Odds(_FIGHT_BASE, condition), survive)
                    case Flee():
                        return FleeStakes(Odds(_FLEE_BASE, condition), survive)
                    case _:
                        assert_never(intent)
            case _:
                return None

    def close(self) -> None:
        self._store.close()

    def _timed(self, intent: TimedIntent) -> Turn:
        with self._store.transaction(self._dice) as txn:
            start = txn.tick()
            reports = _resolve_timed(intent, txn, self._content)
            end = txn.tick()
        if not txn.facts:  # refused: nothing changed and no time passed
            assert reports, f"{intent} did nothing and said nothing"
            return Turn(reports)
        assert end > start, f"{intent} took no time"
        before, after = game_time(start), game_time(end)
        notices = (PhaseChanged(before, after),) if after != before else ()
        return Turn((*txn.facts, *notices, *reports), txn.logged)


def _resolve_free(intent: FreeIntent, view: View, content: Content) -> tuple[Event, ...]:
    match intent:
        case Status():
            needs = view.needs()
            levels = tuple(NeedLevel(need, level(need, needs.count(need))) for need in Need)
            now = game_time(view.tick())
            dangers: list[Danger] = []
            for clock in Clock:
                worst = max((sign.stage for sign in view.signs_seen() if sign.clock is clock), default=None)
                if worst is None:
                    continue
                # A predator the clone has seen hunting is a danger of striking where the PC is, not of growing worse
                striking = _attack_odds(view, content, now) if clock is Clock.PREDATOR and worst == 4 else None
                dangers.append(Danger(clock, worst, daily_chance(clock, now.day), striking))
            return (StatusReport(now, view.run(), levels, wound_level(view.wounds()), tuple(dangers)),)
        case Where():
            return (PlaceReport(view.pc_place().name, _route_home(view)),)
        case Look():
            return (_look(view, content),)
        case Inventory():
            return (InventoryReport(_stacked(view.carried(), content)),)
        case Map():
            here = view.pc_place().id
            entries = tuple(
                MapEntry(place.name, place.id == here, view.exits(place.id))
                for place in (view.place(node) for node in view.visited())
            )
            return (MapReport(entries),)
        case _:
            assert_never(intent)


def _resolve_timed(intent: TimedIntent, txn: Txn, content: Content) -> tuple[Report, ...]:
    """Do what the intent says, recording its facts, and return the reports to show after them. A refused action
    records nothing and returns the report that says why."""
    match intent:
        case Wait(ticks=ticks):
            return _pass(txn, ticks, content, Activity.WAITING, interruptible=True)
        case WaitUntil(minute_of_day=minute):
            return _pass(txn, ticks_until(txn.tick(), minute), content, Activity.WAITING, interruptible=True)
        case Move(direction=direction):
            way = next((out for out in txn.exits(txn.pc_place().id) if out.direction == direction), None)
            if way is None:
                return (NoPath(direction),)
            return _walk(txn, content, way)
        case Drink():
            return _drink(txn, content)
        case Fill():
            return _fill(txn, content)
        case Search():
            return _search(txn, content)
        case Take(words=words):
            place = txn.pc_place()
            match _meant(words, txn.items_at(place.id), content):
                case None:
                    return (NotHere(words),)
                case WhichOne() as which:
                    return (which,)
                case items:
                    return _handle(txn, content, items, taking=True)
        case TakeAll():
            items = txn.items_at(txn.pc_place().id)
            return (NothingHere(),) if not items else _handle(txn, content, items, taking=True)
        case Drop(words=words):
            match _meant(words, txn.carried(), content):
                case None:
                    return (NotCarried(words),)
                case WhichOne() as which:
                    return (which,)
                case items:
                    return _handle(txn, content, items, taking=False)
        case DropAll():
            items = txn.carried()
            return (NothingCarried(),) if not items else _handle(txn, content, items, taking=False)
        case Eat(words=words):
            match _meant(words, txn.carried(), content):
                case None:
                    return (NotCarried(words),)
                case WhichOne() as which:
                    return (which,)
                case items:
                    return _eat(txn, content, items[0])  # eating is always one item: the lowest ID
        case Rest(ticks=ticks):
            if ticks is None:  # until rested
                fatigue = txn.needs().fatigue
                if fatigue == 0:
                    return (NotTired(),)
                ticks = (fatigue + 1) // 2  # just long enough to reach 0
            return _pass(txn, ticks, content, Activity.RESTING, interruptible=True)
        case RestUntil(minute_of_day=minute):
            return _pass(txn, ticks_until(txn.tick(), minute), content, Activity.RESTING, interruptible=True)
        case Fight():
            return _fight(txn, content)
        case Flee():
            return _flee(txn, content)
        case _:
            assert_never(intent)


# A search takes an hour, and rolls to turn up the next hidden thing: 50%, plus the points of everything carried
# that helps a search, less when fatigue clouds it or wounds slow the hands.
_SEARCH_TICKS = TICKS_PER_HOUR
_SEARCH_BASE = 0.50

# The gambles with the predator (M4): a roll to drive it off, one to get away, and — failing either — one to live
# through it wounded. Fatigue and wounds cost each of them, and searches, the same points.
_FIGHT_BASE = 0.35
_FLEE_BASE = 0.50
_SURVIVE_BASE = 0.70
_VERY_TIRED = Modifier("very tired", -0.10)
_EXHAUSTED = Modifier("exhausted", -0.20)
_WOUNDED = Modifier("wounded", -0.10)
_BADLY_WOUNDED = Modifier("badly wounded", -0.20)

# What the PC can be doing for the hunting predator to catch it lingering: anything but walking, drinking,
# handling things, and eating — and fighting, which is its own gamble.
_LINGERING = frozenset((Activity.WAITING, Activity.RESTING, Activity.SEARCHING))

# The predator as a cause of death, as the log names it.
_THE_PREDATOR = "the predator"


def _search(txn: Txn, content: Content) -> tuple[Report, ...]:
    """Spend an hour searching where the PC is. A place hides only so much: once a search finds nothing left, the
    clone knows not to search there again."""
    place = txn.pc_place()
    if txn.searched_bare(place.id):
        return (NowhereLeft(),)
    start = txn.tick()
    reports = _pass(txn, _SEARCH_TICKS, content, Activity.SEARCHING, interruptible=True)
    if txn.tick() - start < _SEARCH_TICKS or txn.attack() is not None:
        # stopped short, or the predator came: an interrupted search finds nothing, even on its last tick
        return reports
    hidden = txn.next_hidden(place.id)
    if hidden is None:
        txn.record(PlaceSearchedBare(txn.run(), place.id))
    elif txn.roll(_search_odds(txn, content), "search", place.id):
        txn.record(ItemFound(hidden.id, place.id, content.item(hidden.kind).name))
    return reports


def _search_odds(txn: Txn, content: Content) -> Odds:
    """A search's odds, read from what the PC carries and its condition as the search ends. Each kind of thing
    carried that helps a search adds its points, however many of it are carried."""
    modifiers = [
        Modifier(defn.name, defn.search / 100)
        for kind in _kinds_carried(txn, content)
        if (defn := content.item(kind)).search
    ]
    modifiers.extend(_condition(txn.needs(), txn.wounds()))
    return Odds(_SEARCH_BASE, tuple(modifiers))


def _kinds_carried(txn: Txn, content: Content) -> tuple[ItemKind, ...]:
    """The kinds of thing the PC carries, in items.toml order."""
    order = {kind: n for n, kind in enumerate(content.items)}
    return tuple(sorted({item.kind for item in txn.carried()}, key=order.__getitem__))


def _condition(needs: Needs, wounds: int) -> tuple[Modifier, ...]:
    """What the PC's condition costs a roll, in a fixed order: fatigue first, then wounds, each level worth more
    than the last."""
    modifiers: list[Modifier] = []
    tired = level(Need.FATIGUE, needs.fatigue)
    if tired >= 3:
        modifiers.append(_EXHAUSTED)
    elif tired == 2:
        modifiers.append(_VERY_TIRED)
    hurt = wound_level(wounds)
    if hurt == 2:
        modifiers.append(_BADLY_WOUNDED)
    elif hurt == 1:
        modifiers.append(_WOUNDED)
    return tuple(modifiers)


def _gamble(base: float, txn: Txn) -> Odds:
    """A gamble against the predator, at BASE, as the PC stands for it."""
    return Odds(base, _condition(txn.needs(), txn.wounds()))


def _attack_odds(view: View, content: Content, at: GameTime) -> Odds:
    """The hunting predator's odds of attacking the PC where it is, at the time AT."""
    place = view.pc_place().id
    return attack_odds(at_home=_at_home(view.places(), place, content), at_night=at.phase is Phase.NIGHT)


def _at_home(places: tuple[PlaceWithKind, ...], place: NodeId, content: Content) -> bool:
    """Whether PLACE is one of the home section's places."""
    kind = next(entry.kind for entry in places if entry.place == place)
    return kind in content.home.places


@dataclass(slots=True)
class _Hazards:
    """The hazard clocks' side of one action's ticks: each clock as the ticks find it, the signs this clone has come
    across, and the facts to record once the ticks are done. The rolls that decide a move come from the keyed
    streams, not logged rolls — the exception to every roll being logged (hazards.py). Here too belongs the
    predator's hunt: once its clock stands at the hunt, it may attack a clone that lingers."""

    txn: Txn
    content: Content
    run: int
    here: NodeId
    at_home: bool
    clocks: dict[Clock, ClockState]
    seen: set[Sign]
    facts: list[Fact]
    struck: bool = False

    def turn(self, at: Tick, activity: Activity, reports: list[Report]) -> bool:
        """Each clock's turn at tick AT, in `Clock` order: it may move up a stage and leave its sign, which the clone
        notices if it is left right where the clone is, and the cries carry at midnight once the predator is far
        enough along. Then the predator's own turn: hunting, it may attack. Returns whether something happened the
        player can react to."""
        stopped = False
        for clock in Clock:
            state = self.clocks[clock]
            standing = state
            if may_move(state.stage, state.since, at):
                day = game_time(at).day
                daily = daily_chance(clock, day)
                certain = due(clock, state.stage + 1, at)
                if certain or self.txn.stream("clock", clock, at).random() < tick_chance(daily):
                    stage = state.stage + 1
                    standing = ClockState(clock, stage, at)
                    self.facts.append(ClockAdvanced(clock, stage, at, daily, certain))
                    if stage < 4:  # the threat (stage 4) leaves no sign
                        place = _sign_place(self.txn, self.content, clock, stage, at)
                        self.facts.append(SignLeft(clock, stage, place, at))
                        sign = Sign(clock, stage)
                        if place == self.here and sign not in self.seen:
                            self.facts.append(SignSeen(self.run, clock, stage))
                            self.seen.add(sign)
                            reports.append(SignNoticed(clock, stage))
                            stopped = True
            if clock is Clock.PREDATOR and is_midnight(at) and standing.stage >= 3:
                reports.append(HeardCries())
                cries = Sign(Clock.PREDATOR, 3)
                if cries not in self.seen:  # the first time a clone hears them is its coming across them
                    self.facts.append(SignSeen(self.run, Clock.PREDATOR, 3))
                    self.seen.add(cries)
                stopped = True
            self.clocks[clock] = standing
        if self._strikes(activity, at):
            self.struck = True
            reports.append(Attacked())
            odds = attack_odds(at_home=self.at_home, at_night=game_time(at).phase is Phase.NIGHT)
            self.facts.append(PredatorAttacked(self.here, at, odds))
            hunt = Sign(Clock.PREDATOR, 4)
            if hunt not in self.seen:  # the attack itself is the clone's sight of the hunt
                self.facts.append(SignSeen(self.run, Clock.PREDATOR, 4))
                self.seen.add(hunt)
            return True
        return stopped

    def _strikes(self, activity: Activity, at: Tick) -> bool:
        """Whether the predator attacks at tick AT. Only a clone that lingers is exposed, and only one attack is
        under way at a time. Like the clocks' rolls, the draw comes from a keyed stream and is logged only when it
        fires, in the fact it causes (hazards.py)."""
        hunting = self.clocks[Clock.PREDATOR].stage >= 4
        if not hunting or activity not in _LINGERING or self.txn.attack() is not None:
            return False
        odds = attack_odds(at_home=self.at_home, at_night=game_time(at).phase is Phase.NIGHT)
        return self.txn.stream("attack", at).random() < tick_chance(odds.chance)


def _pass(txn: Txn, ticks: int, content: Content, activity: Activity, *, interruptible: bool) -> tuple[Report, ...]:
    """Let TICKS ticks pass for ACTIVITY, one at a time. This is the scheduler (design §6): every time-driven system
    takes its turn each tick, in a fixed order: the needs, then the wounds' healing, then the hazard clocks
    (design §7.2), then the predator's
    hunt. A need getting worse, or a sign coming to the clone's notice, is reported as it happens and stops an
    interruptible action with ticks left, so the player can react; a need coming back down to 0 is reported too,
    but only getting worse and the clocks stop anything. An attack stops the action at that tick even on its last
    one. The clocks' facts are recorded after the needs', in the order they happened: each advance, then the sign
    it left, then the clone coming across it."""
    assert ticks > 0, "an action takes at least one tick"
    start = txn.tick()
    pc = txn.pc()
    needs = txn.needs()
    place = txn.pc_place()
    hazards = _Hazards(
        txn,
        content,
        txn.run(),
        place.id,
        _at_home(txn.places(), place.id, content),
        {state.clock: state for state in txn.clocks()},
        set(txn.signs_seen()),
        [],
    )
    wounds_at_start = txn.wounds()
    wounds = wounds_at_start
    reports: list[Report] = []
    passed = 0
    for _ in range(ticks):
        stepped = tick(needs, activity)
        healing = heal(wounds, activity)
        passed += 1
        at = Tick(start + passed)
        worsened = _needs_turn(needs, stepped, reports)
        if wound_level(healing) < wound_level(wounds):
            reports.append(WoundsHealed(wound_level(healing)))
        wounds = healing
        noticed = hazards.turn(at, activity, reports)  # every clock takes its turn every tick, whatever the needs did
        needs = stepped
        if hazards.struck:  # the predator has the PC: the action stops, even on its last tick, attack or nothing
            break
        stopped = worsened or noticed
        if stopped and interruptible and passed < ticks:
            reports.append(Interrupted(activity))
            break
    txn.record(TimePassed(start, Tick(start + passed), activity))
    txn.record(NeedsChanged(pc, needs.thirst, needs.hunger, needs.fatigue))
    if wounds != wounds_at_start:  # nothing heals and nothing is recorded while the clone is unhurt
        txn.record(WoundsChanged(pc, wounds))
    for fact in hazards.facts:
        txn.record(fact)
    return tuple(reports)


def _walk(txn: Txn, content: Content, way: Exit) -> tuple[Report, ...]:
    """Walk a path: its ticks, the move, the first visit, the signs at the far end, and a look around."""
    place = txn.pc_place()
    reports = _pass(txn, way.ticks, content, Activity.WALKING, interruptible=False)
    txn.record(PcMoved(txn.pc(), place.id, way.to, way.direction, way.place_name))
    if not txn.is_visited(way.to):
        txn.record(PlaceVisited(way.to))
    seen = set(txn.signs_seen())
    for sign in txn.signs_at(way.to):  # the arrival comes across every sign there the clone hasn't seen
        if sign not in seen:
            txn.record(SignSeen(txn.run(), sign.clock, sign.stage))
    return (*reports, _look(txn, content))


def _run(txn: Txn, content: Content) -> tuple[Report, ...]:
    """The PC's flight, once it is free: back the way it came, or — if it hasn't walked since it woke — down the
    first path out, in `Direction` order. The run is a walk like any other."""
    exits = txn.exits(txn.pc_place().id)
    assert exits, "nowhere to run"
    way = next((out for out in exits if out.to == txn.came_from()), exits[0])
    return _walk(txn, content, way)


def _fight(txn: Txn, content: Content) -> tuple[Report, ...]:
    """Fight the predator off, in the place it has the PC: a tick of it, then a roll to drive it off — and failing
    that, what it costs, as `_mauled` deals out. The fight is never interrupted: nothing else is left."""
    place = txn.attack()
    if place is None:
        return (NothingToFight(),)
    reports = _pass(txn, 1, content, Activity.FIGHTING, interruptible=False)
    if txn.roll(_gamble(_FIGHT_BASE, txn), "fight", place):
        txn.record(PredatorDrivenOff())
        return reports
    return _mauled(txn, place, reports)


def _flee(txn: Txn, content: Content) -> tuple[Report, ...]:
    """Run from the predator that has the PC: a roll to get away — and on it, the run back the way the PC came.
    Failing it, a tick of fighting for its life, as `_mauled` deals out."""
    place = txn.attack()
    if place is None:
        return (NothingToFlee(),)
    if txn.roll(_gamble(_FLEE_BASE, txn), "flee", place):
        txn.record(PcEscaped())
        return _run(txn, content)
    reports = _pass(txn, 1, content, Activity.FIGHTING, interruptible=False)
    return _mauled(txn, place, reports)


def _mauled(txn: Txn, place: NodeId, reports: tuple[Report, ...]) -> tuple[Report, ...]:
    """The predator got its teeth in. A badly wounded clone has no third wound to spare: it dies with no roll to
    save it. Otherwise, a roll to live through it wounded, after which the predator retreats to its cries; a clone
    that dies leaves it hunting."""
    if wound_level(txn.wounds()) == 2 or not txn.roll(_gamble(_SURVIVE_BASE, txn), "survive", place):
        txn.record(PcDied(txn.pc(), _THE_PREDATOR, place))
        return reports
    wounds = take_wound(txn.wounds())
    txn.record(PcWounded(txn.pc(), wounds))
    txn.record(PredatorRetreated())
    return (*reports, Wounded(wound_level(wounds)))


def _needs_turn(needs: Needs, stepped: Needs, reports: list[Report]) -> bool:
    """The needs' turn in one tick, on the counts after it (STEPPED) against the counts before (NEEDS): the needs that
    got worse are reported first, then the needs met. Returns whether any got worse."""
    worsened = False
    for need in Need:
        now = level(need, stepped.count(need))
        if now > level(need, needs.count(need)):
            reports.append(NeedWorsened(need, now))
            worsened = True
    reports.extend(NeedMet(need) for need in Need if needs.count(need) > 0 and stepped.count(need) == 0)
    return worsened


def _sign_place(txn: Txn, content: Content, clock: Clock, stage: int, at: Tick) -> NodeId | None:
    """Where a clock's stage leaves its sign: the predator's tracks in a corridor and its kill in a room beyond the
    home section, drawn where there's a choice; the air recycler's signs all at the vat bay, where it hums. The
    cries (predator 3) are heard, not placed, so they are nowhere."""
    places = txn.places()
    match clock, stage:
        case Clock.AIR, 1 | 2 | 3:
            return next(entry.place for entry in places if entry.kind == content.home.start)
        case Clock.PREDATOR, 1:
            corridors = tuple(e.place for e in places if e.kind == content.decks.corridor.kind)
            return _sign_choice(txn, clock, stage, at, corridors)
        case Clock.PREDATOR, 2:
            beyond = tuple(
                e.place for e in places if e.kind != content.decks.corridor.kind and e.kind not in content.home.places
            )
            return _sign_choice(txn, clock, stage, at, beyond)
        case Clock.PREDATOR, 3:
            return None
        case _:
            raise AssertionError(f"stage {stage} of {clock} leaves no sign")


def _sign_choice(txn: Txn, clock: Clock, stage: int, at: Tick, candidates: tuple[NodeId, ...]) -> NodeId:
    """Pick one of CANDIDATES, in node ID order, with the clock's stream: the seed chooses where each sign lands."""
    assert candidates, f"nowhere for {clock}'s stage {stage} sign to land"
    return txn.stream("clock", clock, "sign", stage, at).choice(candidates)


def _look(view: View, content: Content) -> LookReport:
    """What a clone sees when it looks, arrives somewhere, or wakes: the place, the signs it carries, what lies in
    the open there, and the paths out."""
    place = view.pc_place()
    stacks = _stacked(view.items_at(place.id), content)
    return LookReport(place.name, place.description, view.signs_at(place.id), stacks, view.exits(place.id))


def _stacked(items: tuple[Item, ...], content: Content) -> tuple[ItemStack, ...]:
    """Items counted into stacks, in items.toml order: how `look` lists a place and `inventory` a clone's hands.
    Things that hold water stack by kind and how full they are, fullest first, so a full canteen and an empty one
    are two stacks."""
    counts: Counter[tuple[ItemKind, int | None]] = Counter()
    for item in items:
        holds_water = _capacity(content, item.kind) > 0
        counts[(item.kind, item.drinks if holds_water else None)] += 1
    order = {kind: n for n, kind in enumerate(content.items)}  # items.toml order, for stacking

    def fullest_first(pair: tuple[tuple[ItemKind, int | None], int]) -> tuple[int, int]:
        (kind, drinks), _count = pair
        return (order[kind], -(drinks or 0))  # within a kind, the fullest stack comes first

    return tuple(
        ItemStack(
            content.item(kind).name,
            content.item(kind).plural,
            count,
            drinks,
            _capacity(content, kind),
        )
        for (kind, drinks), count in sorted(counts.items(), key=fullest_first)
    )


def _capacity(content: Content, kind: ItemKind) -> int:
    """How many drinks a thing of this kind holds when full: 0 when it holds no water."""
    return content.item(kind).drinks


def _meant(words: tuple[str, ...], pool: tuple[Item, ...], content: Content) -> tuple[Item, ...] | WhichOne | None:
    """The items in POOL that WORDS mean. A kind answers when every word is a word of its name or of its plural.
    One kind answering means its items — all of them when the words answer only to the plural ("take bars"),
    otherwise just the one with the lowest ID — and more than one kind answering is a question for the player.
    The words arrive lowercased, with any leading article already dropped by the parser."""
    order = {kind: n for n, kind in enumerate(content.items)}  # items.toml order, for WhichOne
    answering: list[tuple[ItemKind, bool]] = []
    for kind in sorted({item.kind for item in pool}, key=order.__getitem__):
        by_name = all(word in content.item(kind).name.split() for word in words)
        by_plural = all(word in content.item(kind).plural.split() for word in words)
        if by_name or by_plural:
            answering.append((kind, by_name))
    if not answering:
        return None
    if len(answering) > 1:
        return WhichOne(tuple(content.item(kind).name for kind, _ in answering))
    kind, by_name = answering[0]
    of_kind = tuple(item for item in pool if item.kind == kind)  # the pool is in ID order
    return of_kind[:1] if by_name else of_kind


def _handle(txn: Txn, content: Content, items: tuple[Item, ...], *, taking: bool) -> tuple[Report, ...]:
    """Move ITEMS between the open where the PC stands and its hands — taking them up, or with TAKING false
    putting them down — as one tick of handling, each item in ID order."""
    place = txn.pc_place().id
    pc = txn.pc()
    reports = _pass(txn, 1, content, Activity.HANDLING, interruptible=False)
    for item in items:
        name = content.item(item.kind).name
        fact = ItemTaken(pc, item.id, place, name) if taking else ItemDropped(pc, item.id, place, name)
        txn.record(fact)
    return reports


def _drink(txn: Txn, content: Content) -> tuple[Report, ...]:
    """Drink your fill: from the place, where there's water, and elsewhere from the thing carried with the fewest
    drinks left, so a nearly empty one drains before a full one is opened."""
    if txn.pc_place().water:
        return _pass(txn, 1, content, Activity.DRINKING, interruptible=False)
    carried = txn.carried()
    held = [item for item in carried if _capacity(content, item.kind) and item.drinks > 0]
    if held:
        chosen = min(held, key=lambda item: (item.drinks, item.id))
        reports = _pass(txn, 1, content, Activity.DRINKING, interruptible=False)
        txn.record(DrankFrom(chosen.id, content.item(chosen.kind).name, chosen.drinks - 1))
        return reports
    empty = [item for item in carried if _capacity(content, item.kind)]
    if empty:
        return (NothingToDrink(content.item(empty[0].kind).name),)
    return (NoWater(),)


def _fill(txn: Txn, content: Content) -> tuple[Report, ...]:
    """Fill everything carried that holds water and isn't full, as one tick of handling, each item in ID order."""
    if not txn.pc_place().water:
        return (NoWater(),)
    carried = txn.carried()
    fillable = [
        item for item in carried if _capacity(content, item.kind) and item.drinks < _capacity(content, item.kind)
    ]
    if not fillable:
        return (NothingToFill(),)
    reports = _pass(txn, 1, content, Activity.HANDLING, interruptible=False)
    for item in fillable:
        txn.record(ItemFilled(item.id, content.item(item.kind).name, _capacity(content, item.kind)))
    return reports


def _eat(txn: Txn, content: Content, item: Item) -> tuple[Report, ...]:
    """Eat one item: a tick of eating, then the meal off the PC's hunger. Hunger builds through the tick like any
    other; the meal is taken off after it, and what remains of the hunger is said by its level."""
    defn = content.item(item.kind)
    if not defn.meal:
        return (NotFood(defn.name),)
    reports = _pass(txn, 1, content, Activity.EATING, interruptible=False)
    before = txn.needs().hunger
    after = max(before - defn.meal, 0)
    txn.record(Ate(txn.pc(), item.id, defn.name, after))
    return (*reports, NeedEased(Need.HUNGER, level(Need.HUNGER, before), level(Need.HUNGER, after)))


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
