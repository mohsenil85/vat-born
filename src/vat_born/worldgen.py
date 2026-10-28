"""Worldgen: the map as the seed lays it out. Pure code that draws only from the stream it's handed, in a fixed
order, so the same seed and content always give the same facts. It changes nothing itself; the engine records
them."""

from vat_born.content import Content
from vat_born.dice import Stream
from vat_born.events import PathAdded, PlaceAdded
from vat_born.world import Direction, Layer, NodeId, PlaceKind


def decks(content: Content, stream: Stream, gate: NodeId, first: NodeId) -> tuple[PlaceAdded | PathAdded, ...]:
    """The decks beyond the home section's gate, as facts to record: places with node IDs from FIRST up, and the
    paths between them, starting with the one from GATE."""
    plan = content.decks
    heading = content.home.gate.direction
    corridor = content.place(plan.corridor.kind)

    segments = stream.randint(plan.corridor.segments.least, plan.corridor.segments.most)
    frames = [plan.corridor.first_frame]
    for _ in range(segments - 1):
        frames.append(frames[-1] + stream.randint(plan.corridor.frame_step.least, plan.corridor.frame_step.most))
    walks = [stream.randint(plan.corridor.ticks.least, plan.corridor.ticks.most) for _ in range(segments)]
    count = stream.randint(plan.side_rooms.count.least, plan.side_rooms.count.most)
    kinds = stream.sample(plan.side_rooms.kinds, count)
    sides = _sides(heading)
    openings = [(i, side) for i in range(segments) for side in sides]
    drawn = stream.sample(openings, count)
    # `sample` returns its picks in selection order; the map wants them in corridor order, so sort by where each
    # pair sits in the list rather than by the pairs themselves (Direction compares as a string, not usefully).
    place_of = {pair: n for n, pair in enumerate(openings)}
    rooms = sorted(drawn, key=lambda pair: place_of[pair])
    ladder = stream.randint(1, segments - 1)

    def node(offset: int) -> NodeId:
        return NodeId(first + offset)

    def beyond_place(offset: int, kind: PlaceKind) -> PlaceAdded:
        place = content.place(kind)
        return PlaceAdded(node(offset), Layer.DECKS, kind, place.name, place.description)

    places = [
        PlaceAdded(node(i), Layer.DECKS, plan.corridor.kind, f"{corridor.name} at frame {frame}", corridor.description)
        for i, frame in enumerate(frames)
    ]
    places += [beyond_place(segments + j, kind) for j, kind in enumerate(kinds)]
    places += [beyond_place(segments + count + k, kind) for k, kind in enumerate(plan.lower_deck.kinds)]

    paths = [PathAdded(gate, node(0), heading, walks[0])]
    paths += [PathAdded(node(i - 1), node(i), heading, walks[i]) for i in range(1, segments)]
    paths += [PathAdded(node(i), node(segments + j), side, plan.side_rooms.ticks) for j, (i, side) in enumerate(rooms)]
    paths += [PathAdded(node(ladder), node(segments + count), Direction.DOWN, plan.lower_deck.ticks)]
    paths += [
        PathAdded(node(segments + count + k - 1), node(segments + count + k), Direction.EAST, plan.lower_deck.ticks)
        for k in range(1, len(plan.lower_deck.kinds))
    ]
    return (*places, *paths)


def _sides(heading: Direction) -> tuple[Direction, Direction]:
    """The two horizontal directions at right angles to the corridor's heading, in `Direction` order."""
    if heading in (Direction.NORTH, Direction.SOUTH):
        return (Direction.EAST, Direction.WEST)
    assert heading in (Direction.EAST, Direction.WEST), "the gate's direction was checked horizontal at load"
    return (Direction.NORTH, Direction.SOUTH)
