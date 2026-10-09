"""tkinter front end for the pathfinding visualizer.

Animation is driven entirely by ``canvas.after()``: each tick pulls one or
more steps from the active search generator, paints them, and schedules the
next tick. The Tk event loop is never blocked, so the window stays
responsive and Pause/Step/Clear work mid-search.
"""

import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from algorithms import ALGORITHMS, run_to_completion
from grid import (
    DEFAULT_WEIGHT,
    EMPTY,
    END,
    FRONTIER,
    HEAVY_WEIGHT,
    PATH,
    START,
    VISITED,
    WALL,
    Grid,
)

CELL_SIZE = 24
GRID_LINE_COLOR = "#d4d4d8"

COLORS = {
    EMPTY: "#ffffff",
    WALL: "#27272a",
    START: "#16a34a",
    END: "#dc2626",
    VISITED: "#7dd3fc",
    FRONTIER: "#fde047",
    PATH: "#f97316",
}
WEIGHT_SHADE = 0.62  # weighted cells are drawn at 62% brightness

LEGEND = (
    ("Start", COLORS[START]),
    ("End", COLORS[END]),
    ("Wall", COLORS[WALL]),
    ("Empty", COLORS[EMPTY]),
    ("Weighted (cost {})".format(HEAVY_WEIGHT), None),  # filled in below
    ("Frontier", COLORS[FRONTIER]),
    ("Visited", COLORS[VISITED]),
    ("Path", COLORS[PATH]),
)

SHIFT_MASK = 0x0001
CONTROL_MASK = 0x0004

MAX_DELAY_MS = 300
FAST_SPEED = 85  # above this speed, process several steps per tick


def shade(hex_color, factor):
    """Darken a #rrggbb color by multiplying each channel by ``factor``."""
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    return "#{:02x}{:02x}{:02x}".format(int(r * factor), int(g * factor), int(b * factor))


def cell_color(node):
    color = COLORS[node.state]
    if node.weight != DEFAULT_WEIGHT and node.state not in (WALL, START, END):
        color = shade(color, WEIGHT_SHADE)
    return color


class App:
    """Main window: grid canvas, control panel, stats, legend and status bar."""

    def __init__(self, root, rows=25, cols=40):
        self.root = root
        self.grid = Grid(rows, cols)

        self._search = None          # active search generator, or None
        self._search_name = None
        self._search_ms = 0.0        # time spent inside the generator only
        self._after_id = None
        self._paused = False
        self._has_overlay = False    # VISITED/FRONTIER/PATH cells are showing
        self._drag_mode = None       # "draw", "erase" or None
        self._last_pos = None        # last cell painted during a drag
        self._w_held = False
        self._w_release_id = None

        root.title("Pathfinding Visualizer")
        root.resizable(False, False)
        self._build_widgets()
        self._bind_events()
        self.redraw_all()
        self._set_status("Ready. Draw walls, pick an algorithm and press Run.")

    # ================================================================== layout

    def _build_widgets(self):
        rows, cols = self.grid.rows, self.grid.cols
        self.canvas = tk.Canvas(
            self.root,
            width=cols * CELL_SIZE,
            height=rows * CELL_SIZE,
            highlightthickness=0,
            bg=COLORS[EMPTY],
        )
        self.canvas.grid(row=0, column=0, padx=(10, 5), pady=10, sticky="n")
        self._rects = [
            [
                self.canvas.create_rectangle(
                    c * CELL_SIZE, r * CELL_SIZE,
                    (c + 1) * CELL_SIZE, (r + 1) * CELL_SIZE,
                    outline=GRID_LINE_COLOR,
                )
                for c in range(cols)
            ]
            for r in range(rows)
        ]

        panel = ttk.Frame(self.root)
        panel.grid(row=0, column=1, padx=(5, 10), pady=10, sticky="ns")
        self._build_controls(panel)
        self._build_stats(panel)
        self._build_legend(panel)

        self.status_var = tk.StringVar()
        status = ttk.Label(self.root, textvariable=self.status_var, anchor="w",
                           relief="sunken", padding=(6, 2))
        status.grid(row=1, column=0, columnspan=2, sticky="ew")

    def _build_controls(self, panel):
        box = ttk.LabelFrame(panel, text="Controls", padding=8)
        box.pack(fill="x")

        ttk.Label(box, text="Algorithm").grid(row=0, column=0, sticky="w")
        self.algo_var = tk.StringVar(value="A*")
        algo = ttk.Combobox(box, textvariable=self.algo_var, values=list(ALGORITHMS),
                            state="readonly", width=12)
        algo.grid(row=0, column=1, sticky="ew", pady=2)

        ttk.Label(box, text="Speed").grid(row=1, column=0, sticky="w")
        self.speed_var = tk.IntVar(value=60)
        tk.Scale(box, from_=1, to=100, orient="horizontal", variable=self.speed_var,
                 showvalue=False, length=130).grid(row=1, column=1, sticky="ew", pady=2)

        buttons = (
            ("Run", self.run), ("Pause", self.pause),
            ("Step", self.step), ("Clear Path", self.clear_path),
            ("Clear All", self.clear_all), ("Random Maze", self.random_maze),
            ("Compare All", self.compare), ("Save...", self.save),
            ("Load...", self.load),
        )
        for i, (label, command) in enumerate(buttons):
            ttk.Button(box, text=label, command=command).grid(
                row=2 + i // 2, column=i % 2, sticky="ew", padx=1, pady=1)
        box.columnconfigure(0, weight=1)
        box.columnconfigure(1, weight=1)

    def _build_stats(self, panel):
        box = ttk.LabelFrame(panel, text="Last run", padding=8)
        box.pack(fill="x", pady=(10, 0))
        self.stat_vars = {}
        fields = ("Algorithm", "Result", "Nodes expanded", "Path length", "Path cost", "Time (ms)")
        for i, field in enumerate(fields):
            ttk.Label(box, text=field + ":").grid(row=i, column=0, sticky="w")
            var = tk.StringVar(value="-")
            ttk.Label(box, textvariable=var, width=12).grid(row=i, column=1, sticky="w", padx=(6, 0))
            self.stat_vars[field] = var

    def _build_legend(self, panel):
        box = ttk.LabelFrame(panel, text="Legend", padding=8)
        box.pack(fill="x", pady=(10, 0))
        for i, (label, color) in enumerate(LEGEND):
            if color is None:
                color = shade(COLORS[EMPTY], WEIGHT_SHADE)
            swatch = tk.Canvas(box, width=16, height=16, highlightthickness=0)
            swatch.create_rectangle(1, 1, 15, 15, fill=color, outline="#71717a")
            swatch.grid(row=i, column=0, pady=1)
            ttk.Label(box, text=label).grid(row=i, column=1, sticky="w", padx=(6, 0))

        hints = (
            "Left-drag: draw walls\n"
            "Hold W + left-drag: weights\n"
            "Right-drag: erase\n"
            "Shift+click: move start\n"
            "Ctrl+click: move end"
        )
        ttk.Label(panel, text=hints, justify="left", foreground="#52525b").pack(
            fill="x", pady=(10, 0))

    def _bind_events(self):
        c = self.canvas
        c.bind("<ButtonPress-1>", self._on_left_press)
        c.bind("<B1-Motion>", self._on_drag)
        c.bind("<ButtonRelease-1>", self._on_release)

        # macOS (aqua) reports the right mouse button as button 2.
        right = "2" if self.root.tk.call("tk", "windowingsystem") == "aqua" else "3"
        c.bind("<ButtonPress-{}>".format(right), self._on_right_press)
        c.bind("<B{}-Motion>".format(right), self._on_drag)
        c.bind("<ButtonRelease-{}>".format(right), self._on_release)

        for key in ("w", "W"):
            self.root.bind("<KeyPress-{}>".format(key), self._on_w_press)
            self.root.bind("<KeyRelease-{}>".format(key), self._on_w_release)

    # ================================================================ drawing

    def draw_cell(self, node):
        self.canvas.itemconfigure(self._rects[node.row][node.col], fill=cell_color(node))

    def redraw_all(self):
        for node in self.grid:
            self.draw_cell(node)

    def _set_status(self, text):
        self.status_var.set(text)

    # ========================================================= mouse/keyboard

    def _cell_at(self, event):
        row, col = event.y // CELL_SIZE, event.x // CELL_SIZE
        if self.grid.in_bounds(row, col):
            return row, col
        return None

    def _on_left_press(self, event):
        pos = self._cell_at(event)
        if pos is None:
            return
        if event.state & SHIFT_MASK:
            self._move_endpoint(self.grid.set_start, "start", pos)
        elif event.state & CONTROL_MASK:
            self._move_endpoint(self.grid.set_end, "end", pos)
        elif self._begin_edit():
            self._drag_mode = "draw"
            self._paint(pos)

    def _on_right_press(self, event):
        pos = self._cell_at(event)
        if pos is not None and self._begin_edit():
            self._drag_mode = "erase"
            self._paint(pos)

    def _on_drag(self, event):
        if self._drag_mode is None:
            return
        pos = self._cell_at(event)
        if pos is None or pos == self._last_pos:
            return
        # Motion events can skip cells on a fast drag, so fill in the line
        # between the previous cell and this one.
        (r0, c0), (r1, c1) = self._last_pos or pos, pos
        steps = max(abs(r1 - r0), abs(c1 - c0))
        for i in range(1, steps + 1):
            self._paint((round(r0 + (r1 - r0) * i / steps), round(c0 + (c1 - c0) * i / steps)))

    def _on_release(self, _event):
        self._drag_mode = None
        self._last_pos = None

    def _on_w_press(self, _event):
        # Keyboard auto-repeat sends release/press pairs while a key is held;
        # cancelling the pending release keeps the flag steady.
        if self._w_release_id is not None:
            self.root.after_cancel(self._w_release_id)
            self._w_release_id = None
        self._w_held = True

    def _on_w_release(self, _event):
        self._w_release_id = self.root.after(60, self._w_released)

    def _w_released(self):
        self._w_release_id = None
        self._w_held = False

    def _begin_edit(self):
        """Return True if the grid may be edited now, clearing old overlays."""
        if self._search is not None:
            self._set_status("A search is in progress. Press Clear Path before editing.")
            return False
        if self._has_overlay:
            self.clear_path()
        return True

    def _paint(self, pos):
        row, col = pos
        if self._drag_mode == "erase":
            changed = self.grid.erase(row, col)
        elif self._w_held:
            changed = self.grid.set_weight(row, col, HEAVY_WEIGHT)
        else:
            changed = self.grid.set_wall(row, col)
        self._last_pos = pos
        if changed:
            self.draw_cell(self.grid.node(row, col))

    def _move_endpoint(self, setter, name, pos):
        if not self._begin_edit():
            return
        old = getattr(self.grid, name)
        if setter(*pos):
            self.draw_cell(old)
            self.draw_cell(getattr(self.grid, name))
            self._set_status("Moved {} to row {}, col {}.".format(name, pos[0], pos[1]))

    # ============================================================== animation

    def _delay_ms(self):
        speed = self.speed_var.get()
        return max(1, int(MAX_DELAY_MS * ((100 - speed) / 99) ** 2))

    def _steps_per_tick(self):
        speed = self.speed_var.get()
        return 1 if speed < FAST_SPEED else 1 + (speed - FAST_SPEED) // 3

    def _start_search(self):
        self._clear_overlay()
        self._search_name = self.algo_var.get()
        self._search = ALGORITHMS[self._search_name](self.grid)
        self._search_ms = 0.0
        self._has_overlay = True
        self._show_stats(self._search_name, "running...")

    def _cancel_tick(self):
        if self._after_id is not None:
            self.canvas.after_cancel(self._after_id)
            self._after_id = None

    def _schedule_tick(self):
        self._after_id = self.canvas.after(self._delay_ms(), self._tick)

    def _tick(self):
        self._after_id = None
        if self._search is None or self._paused:
            return
        if self._advance(self._steps_per_tick()):
            self._schedule_tick()

    def _advance(self, count):
        """Pull up to ``count`` steps. Returns False once the search ends."""
        for _ in range(count):
            t0 = time.perf_counter()
            try:
                step = next(self._search)
            except StopIteration as stop:
                self._search_ms += (time.perf_counter() - t0) * 1000.0
                self._finish(stop.value)
                return False
            self._search_ms += (time.perf_counter() - t0) * 1000.0
            self._render_step(step)
        return True

    def _render_step(self, step):
        current = step.current
        if current.state in (EMPTY, FRONTIER):
            current.state = VISITED
            self.draw_cell(current)
        for node in step.discovered:
            if node.state == EMPTY:
                node.state = FRONTIER
                self.draw_cell(node)

    def _finish(self, result):
        self._search = None
        self._cancel_tick()
        for node in result.path:
            if node.state not in (START, END):
                node.state = PATH
                self.draw_cell(node)
        result.elapsed_ms = self._search_ms
        self._show_stats(self._search_name, result=result)
        if result.found:
            self._set_status("{}: path found ({} moves, cost {}).".format(
                self._search_name, result.length, result.cost))
        else:
            self._set_status("{}: no path to the end node.".format(self._search_name))

    def _show_stats(self, name, status=None, result=None):
        v = self.stat_vars
        v["Algorithm"].set(name or "-")
        if result is None:
            v["Result"].set(status or "-")
            for field in ("Nodes expanded", "Path length", "Path cost", "Time (ms)"):
                v[field].set("-")
            return
        v["Result"].set("path found" if result.found else "no path")
        v["Nodes expanded"].set(str(result.expanded))
        v["Path length"].set(str(result.length) if result.found else "-")
        v["Path cost"].set(str(result.cost) if result.found else "-")
        v["Time (ms)"].set("{:.2f}".format(result.elapsed_ms))

    # =============================================================== commands

    def run(self):
        if self._search is None:
            self._start_search()
        elif not self._paused:
            return  # already running
        self._paused = False
        self._set_status("Running {}...".format(self._search_name))
        self._schedule_tick()

    def pause(self):
        if self._search is None or self._paused:
            return
        self._paused = True
        self._cancel_tick()
        self._set_status("Paused. Press Run to resume or Step to advance.")

    def step(self):
        if self._search is None:
            self._start_search()
        self._paused = True
        self._cancel_tick()
        if self._advance(1):
            self._set_status("Stepping {}. Press Run to continue.".format(self._search_name))

    def _stop_search(self):
        self._cancel_tick()
        self._search = None
        self._paused = False

    def _clear_overlay(self):
        self.grid.clear_path()
        self.redraw_all()
        self._has_overlay = False

    def clear_path(self):
        self._stop_search()
        self._clear_overlay()
        self._set_status("Path cleared.")

    def clear_all(self):
        self._stop_search()
        self.grid.clear_all()
        self.redraw_all()
        self._has_overlay = False
        self._show_stats(None)
        self._set_status("Grid cleared.")

    def random_maze(self):
        self._stop_search()
        self.grid.generate_maze()
        self.redraw_all()
        self._has_overlay = False
        self._set_status("Generated a maze with recursive backtracking.")

    def compare(self):
        """Run every algorithm on the current grid without animation."""
        rows = []
        for name, algorithm in ALGORITHMS.items():
            rows.append((name, run_to_completion(algorithm, self.grid)))
        found_costs = [r.cost for _, r in rows if r.found]
        best_cost = min(found_costs) if found_costs else None
        self._show_compare_window(rows, best_cost)
        self._set_status("Compared {} algorithms on the current grid.".format(len(rows)))

    def _show_compare_window(self, rows, best_cost):
        win = tk.Toplevel(self.root)
        win.title("Algorithm comparison")
        win.transient(self.root)
        columns = ("algorithm", "expanded", "length", "cost", "optimal", "time")
        headings = ("Algorithm", "Nodes expanded", "Path length", "Path cost",
                    "Optimal cost?", "Time (ms)")
        table = ttk.Treeview(win, columns=columns, show="headings", height=len(rows))
        for col, heading in zip(columns, headings):
            table.heading(col, text=heading)
            table.column(col, anchor="center", width=110)
        for name, result in rows:
            if result.found:
                values = (name, result.expanded, result.length, result.cost,
                          "yes" if result.cost == best_cost else "no",
                          "{:.2f}".format(result.elapsed_ms))
            else:
                values = (name, result.expanded, "-", "-", "no path",
                          "{:.2f}".format(result.elapsed_ms))
            table.insert("", "end", values=values)
        table.pack(padx=10, pady=(10, 5))
        ttk.Label(
            win,
            text="BFS and DFS ignore weights; Dijkstra and A* minimize path cost.",
            foreground="#52525b",
        ).pack(padx=10)
        ttk.Button(win, text="Close", command=win.destroy).pack(pady=(5, 10))

    def save(self):
        path = filedialog.asksaveasfilename(
            parent=self.root, title="Save grid", defaultextension=".json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")])
        if not path:
            return
        try:
            self.grid.save(path)
        except OSError as exc:
            messagebox.showerror("Save failed", str(exc), parent=self.root)
            return
        self._set_status("Saved grid to {}.".format(path))

    def load(self):
        path = filedialog.askopenfilename(
            parent=self.root, title="Load grid",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")])
        if not path:
            return
        self._stop_search()
        try:
            self.grid.load(path)  # ValueError covers json.JSONDecodeError too
        except (OSError, ValueError) as exc:
            messagebox.showerror("Load failed", str(exc), parent=self.root)
            return
        self.redraw_all()
        self._has_overlay = False
        self._set_status("Loaded grid from {}.".format(path))
