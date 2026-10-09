"""Search algorithms, written as generators for step-by-step animation.

Every algorithm takes a Grid and yields a ``Step`` after each node
expansion (a node is "expanded" when it is taken off the frontier and its
neighbors are examined). When the search ends, the generator *returns* a
``SearchResult``; the caller receives it as ``StopIteration.value``.

The algorithms only read the grid (walls, weights, start, end). They never
change cell states, so painting VISITED/FRONTIER/PATH is left to the GUI and
the same grid can be searched repeatedly, e.g. by compare mode.

Notation for complexity: V = number of cells (rows * cols) and E = number of
edges between neighboring cells (at most 4V on a 4-connected grid).

Path cost is the sum of the weights of every cell entered after the start,
so on an unweighted grid cost equals path length.
"""

import heapq
import time
from collections import deque, namedtuple

Step = namedtuple("Step", ["current", "discovered"])
Step.__doc__ = """One expansion: the node expanded and the nodes newly added to the frontier."""


class SearchResult:
    """Outcome of a search. ``path`` is empty when the end is unreachable."""

    def __init__(self, path, expanded):
        self.path = path
        self.expanded = expanded
        self.cost = sum(node.weight for node in path[1:])
        self.elapsed_ms = 0.0

    @property
    def found(self):
        return bool(self.path)

    @property
    def length(self):
        """Number of moves along the path (cells in the path minus one)."""
        return len(self.path) - 1 if self.path else 0


def _reconstruct(parent, end):
    path = []
    node = end
    while node is not None:
        path.append(node)
        node = parent[node]
    path.reverse()
    return path


def manhattan(a, b):
    """Manhattan distance between two nodes on a 4-connected grid."""
    return abs(a.row - b.row) + abs(a.col - b.col)


def bfs(grid):
    """Breadth-first search.

    Idea: explore the grid in rings of increasing distance from the start
    using a FIFO queue. Every node at distance d is expanded before any node
    at distance d + 1, so the first time the end is reached the path has the
    fewest possible moves.

    Ignores weights: the path is shortest in steps, not necessarily in cost.

    Time: O(V + E). Space: O(V).
    """
    start, end = grid.start, grid.end
    parent = {start: None}
    queue = deque([start])
    expanded = 0
    while queue:
        node = queue.popleft()
        expanded += 1
        if node is end:
            yield Step(node, ())
            return SearchResult(_reconstruct(parent, end), expanded)
        discovered = []
        for neighbor in grid.neighbors(node):
            if neighbor not in parent:
                parent[neighbor] = node
                queue.append(neighbor)
                discovered.append(neighbor)
        yield Step(node, tuple(discovered))
    return SearchResult([], expanded)


def dfs(grid):
    """Depth-first search.

    Idea: always continue from the most recently discovered node (a LIFO
    stack), following one corridor as deep as possible before backtracking.
    It finds *a* path if one exists, but usually not a short one.

    Ignores weights and gives no optimality guarantee.

    Time: O(V + E). Space: O(V).
    """
    start, end = grid.start, grid.end
    parent = {}
    stack = [(start, None)]
    expanded = 0
    while stack:
        node, came_from = stack.pop()
        if node in parent:
            continue  # already expanded via another branch
        parent[node] = came_from
        expanded += 1
        if node is end:
            yield Step(node, ())
            return SearchResult(_reconstruct(parent, end), expanded)
        discovered = []
        # Push in reverse so the first direction in DIRECTIONS is tried first.
        for neighbor in reversed(list(grid.neighbors(node))):
            if neighbor not in parent:
                stack.append((neighbor, node))
                discovered.append(neighbor)
        yield Step(node, tuple(discovered))
    return SearchResult([], expanded)


def dijkstra(grid):
    """Dijkstra's algorithm.

    Idea: keep a priority queue ordered by g(n), the cheapest known cost
    from the start to n. Repeatedly expand the cheapest node; because all
    weights are positive, its cost can never improve afterwards, so it is
    final. Neighbors whose cost improves through it are (re)queued.

    Respects weights and always returns a minimum-cost path.

    Time: O((V + E) log V) with a binary heap. Space: O(V).
    """
    start, end = grid.start, grid.end
    cost = {start: 0}
    parent = {start: None}
    closed = set()
    counter = 0  # tie-breaker so the heap never compares Node objects
    heap = [(0, counter, start)]
    expanded = 0
    while heap:
        g, _, node = heapq.heappop(heap)
        if node in closed:
            continue  # stale heap entry; a cheaper one was already expanded
        closed.add(node)
        expanded += 1
        if node is end:
            yield Step(node, ())
            return SearchResult(_reconstruct(parent, end), expanded)
        discovered = []
        for neighbor in grid.neighbors(node):
            if neighbor in closed:
                continue
            new_cost = g + neighbor.weight
            if neighbor not in cost or new_cost < cost[neighbor]:
                cost[neighbor] = new_cost
                parent[neighbor] = node
                counter += 1
                heapq.heappush(heap, (new_cost, counter, neighbor))
                discovered.append(neighbor)
        yield Step(node, tuple(discovered))
    return SearchResult([], expanded)


def astar(grid):
    """A* search with the Manhattan-distance heuristic.

    Idea: Dijkstra, but order the priority queue by f(n) = g(n) + h(n),
    where h(n) estimates the remaining cost to the end. This steers the
    search toward the goal and usually expands far fewer nodes.

    h is the Manhattan distance. Every move costs at least 1, so h never
    overestimates (admissible) and never drops by more than one move's cost
    (consistent), which guarantees a minimum-cost path and lets each node
    be expanded at most once. Ties on f are broken by smaller h, favoring
    nodes closer to the goal.

    Respects weights and always returns a minimum-cost path.

    Time: O((V + E) log V) worst case, like Dijkstra; in practice much less
    of the grid is explored. Space: O(V).
    """
    start, end = grid.start, grid.end
    cost = {start: 0}
    parent = {start: None}
    closed = set()
    counter = 0
    h = manhattan(start, end)
    heap = [(h, h, counter, start)]
    expanded = 0
    while heap:
        _, _, _, node = heapq.heappop(heap)
        if node in closed:
            continue
        closed.add(node)
        expanded += 1
        if node is end:
            yield Step(node, ())
            return SearchResult(_reconstruct(parent, end), expanded)
        discovered = []
        g = cost[node]
        for neighbor in grid.neighbors(node):
            if neighbor in closed:
                continue
            new_cost = g + neighbor.weight
            if neighbor not in cost or new_cost < cost[neighbor]:
                cost[neighbor] = new_cost
                parent[neighbor] = node
                h = manhattan(neighbor, end)
                counter += 1
                heapq.heappush(heap, (new_cost + h, h, counter, neighbor))
                discovered.append(neighbor)
        yield Step(node, tuple(discovered))
    return SearchResult([], expanded)


# Display name -> generator function, in the order shown in the GUI.
ALGORITHMS = {
    "BFS": bfs,
    "DFS": dfs,
    "Dijkstra": dijkstra,
    "A*": astar,
}


def run_to_completion(algorithm, grid):
    """Exhaust a search generator without animation and time it.

    Returns the SearchResult with ``elapsed_ms`` filled in.
    """
    search = algorithm(grid)
    t0 = time.perf_counter()
    while True:
        try:
            next(search)
        except StopIteration as stop:
            result = stop.value
            break
    result.elapsed_ms = (time.perf_counter() - t0) * 1000.0
    return result
