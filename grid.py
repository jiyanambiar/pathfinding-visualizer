"""Grid model for the pathfinding visualizer.

The grid is a pure data model with no tkinter dependency, so the search
algorithms and the save/load code can run (and be tested) without a GUI.
"""

import json
import random

# Cell states. START/END/WALL/EMPTY describe the maze itself; VISITED,
# FRONTIER and PATH are overlays painted by a search and removed by
# Grid.clear_path().
EMPTY = "empty"
WALL = "wall"
START = "start"
END = "end"
VISITED = "visited"
FRONTIER = "frontier"
PATH = "path"

SEARCH_STATES = frozenset({VISITED, FRONTIER, PATH})

DEFAULT_WEIGHT = 1
HEAVY_WEIGHT = 5

SAVE_FORMAT_VERSION = 1

# Neighbor order (up, right, down, left). Kept fixed so runs are reproducible.
DIRECTIONS = ((-1, 0), (0, 1), (1, 0), (0, -1))


class Node:
    """A single grid cell.

    ``weight`` is the cost of *entering* this cell. Ordinary cells cost
    DEFAULT_WEIGHT; weighted cells cost HEAVY_WEIGHT. Walls are impassable
    regardless of weight.
    """

    __slots__ = ("row", "col", "state", "weight")

    def __init__(self, row, col):
        self.row = row
        self.col = col
        self.state = EMPTY
        self.weight = DEFAULT_WEIGHT

    @property
    def pos(self):
        return (self.row, self.col)

    @property
    def is_wall(self):
        return self.state == WALL

    def __repr__(self):
        return "Node({}, {}, {!r}, w={})".format(self.row, self.col, self.state, self.weight)


class Grid:
    """A rows x cols grid of Nodes with a single start and end node."""

    def __init__(self, rows=25, cols=40):
        if rows < 2 or cols < 2:
            raise ValueError("grid must be at least 2x2")
        self.rows = rows
        self.cols = cols
        self.nodes = [[Node(r, c) for c in range(cols)] for r in range(rows)]
        self.start = None
        self.end = None
        self.set_start(rows // 2, cols // 4)
        self.set_end(rows // 2, cols - 1 - cols // 4)

    # ------------------------------------------------------------------ access

    def __iter__(self):
        for row in self.nodes:
            yield from row

    def in_bounds(self, row, col):
        return 0 <= row < self.rows and 0 <= col < self.cols

    def node(self, row, col):
        return self.nodes[row][col]

    def neighbors(self, node):
        """Yield the passable 4-connected neighbors of ``node``."""
        for dr, dc in DIRECTIONS:
            r, c = node.row + dr, node.col + dc
            if self.in_bounds(r, c):
                neighbor = self.nodes[r][c]
                if not neighbor.is_wall:
                    yield neighbor

    # ----------------------------------------------------------------- editing
    # Each editing method returns True if the grid changed, so the GUI only
    # redraws cells that actually need it.

    def _is_endpoint(self, node):
        return node is self.start or node is self.end

    def set_start(self, row, col):
        return self._move_endpoint("start", START, row, col)

    def set_end(self, row, col):
        return self._move_endpoint("end", END, row, col)

    def _move_endpoint(self, attr, state, row, col):
        node = self.nodes[row][col]
        current = getattr(self, attr)
        if node is current or self._is_endpoint(node):
            return False
        if current is not None:
            current.state = EMPTY
        node.state = state
        node.weight = DEFAULT_WEIGHT
        setattr(self, attr, node)
        return True

    def set_wall(self, row, col):
        node = self.nodes[row][col]
        if self._is_endpoint(node) or node.is_wall:
            return False
        node.state = WALL
        node.weight = DEFAULT_WEIGHT
        return True

    def set_weight(self, row, col, weight=HEAVY_WEIGHT):
        node = self.nodes[row][col]
        if self._is_endpoint(node) or (node.state == EMPTY and node.weight == weight):
            return False
        node.state = EMPTY
        node.weight = weight
        return True

    def erase(self, row, col):
        node = self.nodes[row][col]
        if self._is_endpoint(node) or (node.state == EMPTY and node.weight == DEFAULT_WEIGHT):
            return False
        node.state = EMPTY
        node.weight = DEFAULT_WEIGHT
        return True

    def clear_path(self):
        """Remove search overlays, keeping walls, weights and endpoints."""
        for node in self:
            if node.state in SEARCH_STATES:
                node.state = EMPTY

    def clear_all(self):
        """Remove walls, weights and overlays, keeping endpoint positions."""
        for node in self:
            if not self._is_endpoint(node):
                node.state = EMPTY
            node.weight = DEFAULT_WEIGHT

    # ------------------------------------------------------------------- maze

    def generate_maze(self, rng=None):
        """Replace the grid with a perfect maze using recursive backtracking.

        Cells at even (row, col) coordinates are maze "rooms"; the odd cells
        between them are walls that get knocked down. Starting from (0, 0)
        we walk to a random unvisited room two steps away, carving the wall
        in between, and backtrack when stuck. The recursion is run with an
        explicit stack so large grids cannot hit Python's recursion limit.

        Every room ends up connected by exactly one route, so the maze always
        has a path from start to end. Runs in O(rows * cols).
        """
        rng = rng or random.Random()
        for node in self:
            node.state = WALL
            node.weight = DEFAULT_WEIGHT
        self.start = None
        self.end = None

        self.nodes[0][0].state = EMPTY
        stack = [(0, 0)]
        while stack:
            r, c = stack[-1]
            options = [
                (r + 2 * dr, c + 2 * dc)
                for dr, dc in DIRECTIONS
                if self.in_bounds(r + 2 * dr, c + 2 * dc)
                and self.nodes[r + 2 * dr][c + 2 * dc].is_wall
            ]
            if not options:
                stack.pop()
                continue
            nr, nc = rng.choice(options)
            self.nodes[(r + nr) // 2][(c + nc) // 2].state = EMPTY
            self.nodes[nr][nc].state = EMPTY
            stack.append((nr, nc))

        # With an even dimension the last row/column has no rooms; open a few
        # random dead-end stubs into it so it isn't a solid wall.
        if self.cols % 2 == 0:
            for r in range(0, self.rows, 2):
                if rng.random() < 0.35:
                    self.nodes[r][self.cols - 1].state = EMPTY
        if self.rows % 2 == 0:
            for c in range(0, self.cols, 2):
                if rng.random() < 0.35:
                    self.nodes[self.rows - 1][c].state = EMPTY

        passages = [node for node in self if node.state == EMPTY]
        self.set_start(*passages[0].pos)
        self.set_end(*passages[-1].pos)

    # ------------------------------------------------------------ persistence

    def to_dict(self):
        return {
            "version": SAVE_FORMAT_VERSION,
            "rows": self.rows,
            "cols": self.cols,
            "start": list(self.start.pos),
            "end": list(self.end.pos),
            "walls": [list(n.pos) for n in self if n.is_wall],
            "weights": [[n.row, n.col, n.weight] for n in self
                        if not n.is_wall and n.weight != DEFAULT_WEIGHT],
        }

    def load_dict(self, data):
        """Replace walls, weights and endpoints from a dict made by to_dict().

        Validates everything before touching the grid, so a bad file leaves
        the current grid unchanged. Raises ValueError on invalid data.
        """
        try:
            if data.get("version") != SAVE_FORMAT_VERSION:
                raise ValueError("unsupported save format version: {!r}".format(data.get("version")))
            if (data["rows"], data["cols"]) != (self.rows, self.cols):
                raise ValueError("grid is {}x{} but file is {}x{}".format(
                    self.cols, self.rows, data["cols"], data["rows"]))
            start = self._parse_pos(data["start"])
            end = self._parse_pos(data["end"])
            if start == end:
                raise ValueError("start and end are the same cell")
            walls = {self._parse_pos(p) for p in data["walls"]}
            if start in walls or end in walls:
                raise ValueError("start or end is a wall")
            weights = {}
            for r, c, w in data["weights"]:
                pos = self._parse_pos([r, c])
                if not isinstance(w, int) or isinstance(w, bool) or w < 1:
                    raise ValueError("invalid weight {!r} at {}".format(w, pos))
                weights[pos] = w
        except (AttributeError, KeyError, TypeError) as exc:
            raise ValueError("malformed grid file ({!r})".format(exc)) from exc

        for node in self:
            if node.pos in walls:
                node.state = WALL
                node.weight = DEFAULT_WEIGHT
            else:
                node.state = EMPTY
                node.weight = weights.get(node.pos, DEFAULT_WEIGHT)
        self.start = None
        self.end = None
        self.set_start(*start)
        self.set_end(*end)

    def _parse_pos(self, value):
        r, c = value
        if not (isinstance(r, int) and isinstance(c, int)) or not self.in_bounds(r, c):
            raise ValueError("cell {!r} is out of bounds".format(value))
        return (r, c)

    def save(self, path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2)

    def load(self, path):
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.load_dict(data)
