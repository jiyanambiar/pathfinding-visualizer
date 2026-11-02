"""Tests for the GUI-free parts: the grid model and the search algorithms.

Run from the repository root:  python -m unittest
"""

import random
import unittest

from algorithms import ALGORITHMS, astar, bfs, dijkstra, run_to_completion
from grid import HEAVY_WEIGHT, Grid


def open_grid(rows=5, cols=5, start=(0, 0), end=(4, 4)):
    grid = Grid(rows, cols)
    grid.set_start(*start)
    grid.set_end(*end)
    return grid


class AlgorithmTests(unittest.TestCase):
    def test_every_algorithm_finds_a_path_on_an_open_grid(self):
        for name, algorithm in ALGORITHMS.items():
            with self.subTest(name):
                result = run_to_completion(algorithm, open_grid())
                self.assertTrue(result.found)
                self.assertEqual(result.path[0].pos, (0, 0))
                self.assertEqual(result.path[-1].pos, (4, 4))

    def test_bfs_dijkstra_and_astar_are_shortest_without_weights(self):
        for algorithm in (bfs, dijkstra, astar):
            with self.subTest(algorithm.__name__):
                result = run_to_completion(algorithm, open_grid())
                self.assertEqual(result.length, 8)
                self.assertEqual(result.cost, 8)

    def test_paths_are_connected_and_avoid_walls(self):
        grid = open_grid()
        for r in range(4):
            grid.set_wall(r, 2)
        for name, algorithm in ALGORITHMS.items():
            with self.subTest(name):
                path = run_to_completion(algorithm, grid).path
                for a, b in zip(path, path[1:]):
                    self.assertEqual(abs(a.row - b.row) + abs(a.col - b.col), 1)
                self.assertFalse(any(node.is_wall for node in path))

    def test_unreachable_end_reports_no_path(self):
        grid = open_grid()
        for r in range(5):
            grid.set_wall(r, 2)
        for name, algorithm in ALGORITHMS.items():
            with self.subTest(name):
                result = run_to_completion(algorithm, grid)
                self.assertFalse(result.found)
                self.assertEqual(result.length, 0)

    def test_dijkstra_and_astar_route_around_weights(self):
        # A weighted column with one gap: going through the gap is cheaper
        # than the straight weighted route, even though it is longer.
        grid = open_grid(rows=5, cols=5, start=(3, 0), end=(3, 4))
        for r in range(4):
            grid.set_weight(r, 2, HEAVY_WEIGHT)
        for algorithm in (dijkstra, astar):
            with self.subTest(algorithm.__name__):
                result = run_to_completion(algorithm, grid)
                self.assertEqual(result.cost, 6)
        self.assertEqual(run_to_completion(bfs, grid).cost, 8)

    def test_astar_matches_dijkstra_cost_on_random_weighted_grids(self):
        rng = random.Random(7)
        for _ in range(50):
            grid = open_grid(rows=8, cols=8, start=(0, 0), end=(7, 7))
            for r in range(8):
                for c in range(8):
                    roll = rng.random()
                    if roll < 0.2:
                        grid.set_wall(r, c)
                    elif roll < 0.4:
                        grid.set_weight(r, c, HEAVY_WEIGHT)
            d = run_to_completion(dijkstra, grid)
            a = run_to_completion(astar, grid)
            self.assertEqual(d.found, a.found)
            if d.found:
                self.assertEqual(d.cost, a.cost)
                self.assertLessEqual(a.expanded, d.expanded)


class GridTests(unittest.TestCase):
    def test_maze_always_connects_start_and_end(self):
        for seed in range(20):
            grid = Grid(25, 40)
            grid.generate_maze(random.Random(seed))
            self.assertTrue(run_to_completion(bfs, grid).found)

    def test_save_and_load_round_trip(self):
        grid = open_grid()
        grid.set_wall(1, 1)
        grid.set_weight(2, 2, HEAVY_WEIGHT)
        data = grid.to_dict()

        other = Grid(5, 5)
        other.load_dict(data)
        self.assertEqual(other.to_dict(), data)

    def test_load_rejects_bad_files_without_changing_the_grid(self):
        good = open_grid().to_dict()
        bad_files = [
            dict(good, version=99),
            dict(good, rows=6),
            dict(good, start=[0, 0, 0]),
            dict(good, start=[True, 0]),
            dict(good, end=[9, 9]),
            dict(good, walls=[[0, 0]]),
            dict(good, weights=[[1, 1]]),
            dict(good, weights=[[1, 1, 0]]),
            {"version": 1},
        ]
        for data in bad_files:
            with self.subTest(data=data):
                grid = open_grid()
                before = grid.to_dict()
                with self.assertRaises(ValueError):
                    grid.load_dict(data)
                self.assertEqual(grid.to_dict(), before)


if __name__ == "__main__":
    unittest.main()
