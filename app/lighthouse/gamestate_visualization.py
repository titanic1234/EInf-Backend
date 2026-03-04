from __future__ import annotations
from typing import Any
from app.ws_routing.types import GRID_SIZE

DISPLAY_HEIGHT = 14
DISPLAY_WIDTH = 28
BOARD_SIZE = GRID_SIZE

# Farben
BLACK = (0, 0, 0)
BRIGHT_RED = (255, 0, 0)       # hit
WHITE = (255, 255, 255)        # miss
LIGHT_BLUE = (100, 200, 255)   # scan
GREEN = (0, 255, 0)            # scan + ship gefunden
ORANGE = (255, 140, 0)         # napalm
DARK_RED = (120, 0, 0)         # destroyed
DARK_BLUE = (0, 0, 80)         # blank



def _empty_frame() -> list[list[tuple[int, int, int]]]:
    return [[BLACK for _ in range(DISPLAY_WIDTH)] for _ in range(DISPLAY_HEIGHT)]


def _status_for_cell(board: dict[str, Any], cell: tuple[int, int]) -> str:
    shots = board.get("shots", set())
    hits = board.get("hits", set())
    occupied = board.get("occupied", set())
    napalm = board.get("napalm", set())
    scans = board.get("scans", set())
    scan_hits = board.get("scan_hits", set())

    ship_by_cell = board.get("ship_by_cell", {})
    destroyed_ship_ids = board.get("destroyed_ships", set())

    ship_idx = ship_by_cell.get(cell)
    if ship_idx is not None and ship_idx in destroyed_ship_ids and cell in occupied:
        return "destroyed"

    if cell in hits:
        return "hit"

    if cell in napalm:
        return "napalm"

    if cell in scan_hits:
        return "scan_found"

    if cell in scans:
        return "scan"

    if cell in shots and cell not in occupied:
        return "miss"

    return "blank"


def _color_for_status(status: str) -> tuple[int, int, int]:
    color_map = {
        "destroyed": DARK_RED,
        "hit": BRIGHT_RED,
        "napalm": ORANGE,
        "scan_found": GREEN,
        "scan": LIGHT_BLUE,
        "miss": WHITE,
        "blank": DARK_BLUE,
    }
    return color_map.get(status, DARK_BLUE)


def _draw_board(frame: list[list[tuple[int, int, int]]], board: dict[str, Any], row_off: int, col_off: int) -> None:
    for r in range(BOARD_SIZE):
        for c in range(BOARD_SIZE):
            status = _status_for_cell(board, (r, c))
            frame[row_off + r][col_off + c] = _color_for_status(status)


def build_gamestate_frame(room: Any) -> list[list[tuple[int, int, int]]]:
    frame = _empty_frame()

    boards = getattr(room, "boards", {}) or {}
    host_board = boards.get("host")
    guest_board = boards.get("guest")

    # 14x28: 1 Zeile oben/unten schwarz, 1 Spalte links/rechts schwarz,
    # sowie 2 schwarze Spalten in der Mitte.
    row_off = 1
    host_col_off = 1
    guest_col_off = 15

    if host_board:
        _draw_board(frame, host_board, row_off=row_off, col_off=host_col_off)
    if guest_board:
        _draw_board(frame, guest_board, row_off=row_off, col_off=guest_col_off)

    return frame