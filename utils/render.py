#!/usr/bin/env python3

import time
from typing import Any, Callable
from utils.cell import Cell

from mlx import Mlx

CELL = 20
PANEL_HEIGHT = 120
PANEL_WIDTH = 250
COLOR_BG = 0x1E1E1E
COLOR_WALL = 0xFFFFFF
COLOR_ENTRY = 0x00FF00
COLOR_EXIT = 0xFF0000
COLOR_SPECIAL = 0x808080
COLOR_PANEL = 0x111111

# X11 keysyms (what mlx_key_hook gives you on Linux)
KEY_ESC = 65307
KEY_Q = 113
KEYS_1 = (49, 65457)   # '1', keypad 1
KEYS_2 = (50, 65458)
KEYS_3 = (51, 65459)
KEYS_4 = (52, 65460)
KEYS_5 = (53, 65461)

ANIM_DELAY = 0.03  # seconds between animation steps


class MazeVisualizer:
    def __init__(
        self,
        maze: list[list[Cell]],
        config: Any,
        solution: list[tuple[int, int]],
        on_regenerate: Callable[
            [],
            tuple[list[list[Cell]], list[tuple[int, int]]]
        ] | None = None,
    ) -> None:
        self.maze = maze
        self.config = config
        self.solution = solution
        self.on_regenerate = on_regenerate
        self.path_style = 0
        self.closed = False

        self.show_path_flag = False
        self.color_index = 0
        self.wall_colors = [COLOR_WALL, 0x00FFFF, 0xFFD700, 0xFF69B4]

        self.animating_path = False
        self.anim_index = 0
        self.anim_set: set[tuple[int, int]] = set()
        self.last_step = 0.0

        self.solution_set = set(self.solution)

        self.maze_width = config.width * CELL
        self.maze_height = config.height * CELL
        self.win_width = max(self.maze_width, PANEL_WIDTH)
        self.win_height = self.maze_height + PANEL_HEIGHT

        self.m = Mlx()
        self.ptr = self.m.mlx_init()
        self.win = self.m.mlx_new_window(
            self.ptr, self.win_width, self.win_height, "A-Maze-ing")
        self.img = self.m.mlx_new_image(
            self.ptr, self.win_width, self.win_height)
        (self.data, self.bpp, self.size_line,
         self.fmt) = self.m.mlx_get_data_addr(self.img)

        # Events
        self.m.mlx_key_hook(self.win, self.on_key, None)
        # EXPOSE: the window content is lost whenever the window is
        # (re)mapped/uncovered -> we MUST redraw there. This is what makes
        # the display stable.
        self.m.mlx_expose_hook(self.win, self.on_expose, None)
        # WM_DELETE_WINDOW (clicking the X) is event 33, not 17
        self.m.mlx_hook(self.win, 33, 0, self.on_close_event, None)
        self.m.mlx_loop_hook(self.ptr, self.loop_hook, None)

    # ---------------------------------------------------------- drawing
    def draw_rect(self, x: int, y: int, w: int, h: int, color: int) -> None:
        """Fast rectangle: one slice assignment per row (no per-pixel loop)."""
        x0, y0 = max(x, 0), max(y, 0)
        x1 = min(x + w, self.win_width)
        y1 = min(y + h, self.win_height)
        if x1 <= x0 or y1 <= y0:
            return
        pixel = bytes([color & 0xFF, (color >> 8) & 0xFF,
                       (color >> 16) & 0xFF, 255])
        row = pixel * (x1 - x0)
        for yy in range(y0, y1):
            off = yy * self.size_line + x0 * 4
            self.data[off:off + len(row)] = row

    def draw_horizontal(self, x: int, y: int, color: int) -> None:
        self.draw_rect(x, y, CELL, 1, color)

    def draw_vertical(self, x: int, y: int, color: int) -> None:
        self.draw_rect(x, y, 1, CELL, color)

    def draw_path_marker(self, x: int, y: int) -> None:
        px, py = x * CELL, y * CELL
        if self.path_style == 0:
            self.draw_rect(px + 6, py + 6, 8, 8, 0x00FFFF)
        elif self.path_style == 1:
            self.draw_rect(px + 8, py + 5, 4, 10, 0xFF00FF)
            self.draw_rect(px + 6, py + 7, 8, 6, 0xFF00FF)
        elif self.path_style == 2:
            self.draw_rect(px + 8, py + 4, 4, 12, 0xFFD700)
            self.draw_rect(px + 4, py + 8, 12, 4, 0xFFD700)
        elif self.path_style == 3:
            self.draw_rect(px + 8, py + 7, 4, 6, 0x00FF00)
            self.draw_rect(px + 7, py + 8, 6, 4, 0x00FF00)

    def render_maze(self, *args: Any) -> int:
        if self.closed:
            return 0
        self.draw_rect(0, 0, self.win_width, self.win_height, COLOR_BG)
        self.draw_rect(0, self.maze_height, self.win_width,
                       PANEL_HEIGHT, COLOR_PANEL)
        wall = self.wall_colors[self.color_index]

        for y, row in enumerate(self.maze):
            for x, cell in enumerate(row):
                px, py = x * CELL, y * CELL

                if getattr(cell, "is_special", False):
                    self.draw_rect(px, py, CELL, CELL, COLOR_SPECIAL)
                if cell.north:
                    self.draw_horizontal(px, py, wall)
                if cell.west:
                    self.draw_vertical(px, py, wall)
                if cell.south:
                    self.draw_horizontal(px, py + CELL - 1, wall)
                if cell.east:
                    self.draw_vertical(px + CELL - 1, py, wall)

                if self.show_path_flag and not self.animating_path \
                        and (x, y) in self.solution_set:
                    self.draw_path_marker(x, y)
                if self.animating_path and (x, y) in self.anim_set:
                    self.draw_path_marker(x, y)

                if (x, y) == self.config.entry:
                    self.draw_rect(px + 4, py + 4, CELL - 8, CELL - 8,
                                   COLOR_ENTRY)
                if (x, y) == self.config.exit:
                    self.draw_rect(px + 4, py + 4, CELL - 8, CELL - 8,
                                   COLOR_EXIT)

        self.m.mlx_put_image_to_window(self.ptr, self.win, self.img, 0, 0)

        # Text must be drawn AFTER the image
        by = self.maze_height + 5
        put = self.m.mlx_string_put
        put(self.ptr, self.win, 5, by, 0xFFFFFF, "=== A-Maze-ing ===")
        put(self.ptr, self.win, 5, by + 20, 0x00FF00, "1. Re-generate maze")
        put(self.ptr, self.win, 5, by + 35, 0x00FFFF, "2. Show/Hide path")
        put(self.ptr, self.win, 5, by + 50, 0xFFD700, "3. Rotate wall colours")
        put(self.ptr, self.win, 5, by + 65, 0xFF0000, "4. Quit (ESC)")
        put(self.ptr, self.win, 5, by + 80, 0xFF00FF, "5. Animate path")
        return 0

    # ----------------------------------------------------------- events
    def on_expose(self, *args: Any) -> None:
        self.render_maze()

    def loop_hook(self, *args: Any) -> None:
        if self.closed or not self.animating_path:
            return
        now = time.monotonic()
        if now - self.last_step < ANIM_DELAY:
            return
        self.last_step = now

        if self.anim_index < len(self.solution):
            self.anim_set.add(self.solution[self.anim_index])
            self.anim_index += 1
        else:
            self.animating_path = False
        self.render_maze()

    def on_key(self, keycode: int, *args: Any) -> None:
        if keycode in (KEY_ESC, KEY_Q) + KEYS_4:
            self.close()
            return

        if keycode in KEYS_1:
            self.animating_path = False
            self.anim_index = 0
            self.anim_set = set()
            self.show_path_flag = False
            if self.on_regenerate:
                try:
                    new_maze, new_solution = self.on_regenerate()
                    self.maze = new_maze
                    self.solution = list(new_solution)
                    self.solution_set = set(self.solution)
                except Exception as error:
                    print(f"Error regenerating maze: {error}")
            self.render_maze()

        elif keycode in KEYS_2:
            self.animating_path = False
            self.show_path_flag = not self.show_path_flag
            self.render_maze()

        elif keycode in KEYS_3:
            self.color_index = (self.color_index + 1) % len(self.wall_colors)
            self.render_maze()

        elif keycode in KEYS_5:
            self.show_path_flag = False
            self.animating_path = True
            self.anim_index = 0
            self.anim_set = set()
            self.path_style = (self.path_style + 1) % 4
            self.last_step = 0.0
            self.render_maze()

    def on_close_event(self, *args: Any) -> None:
        self.close()

    def close(self, *args: Any) -> int:
        """Stop the loop. Cleanup happens in start() after the loop ends.

        Do NOT raise SystemExit here: this runs inside a ctypes callback,
        where exceptions are swallowed, so the program would never quit.
        """
        if not self.closed:
            self.closed = True
            self.m.mlx_loop_exit(self.ptr)
        return 0

    def start(self) -> None:
        try:
            self.render_maze()
            self.m.mlx_loop(self.ptr)
        except Exception as error:
            print(f"Error detected: {error}")
        finally:
            self.closed = True
            try:
                if self.img:
                    self.m.mlx_destroy_image(self.ptr, self.img)
                    self.img = None
                if self.win:
                    self.m.mlx_destroy_window(self.ptr, self.win)
                    self.win = None
            except Exception as error:
                print(f"Error while closing: {error}")
