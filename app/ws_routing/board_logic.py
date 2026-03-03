# app/ws_routing/board_logic.py

from __future__ import annotations
from typing import Any, Dict, List, Set, Tuple, Optional
from app.ws_routing.types import Coord
from app.ws_routing.state import _in_bounds


IMMUNE_TO_NAPALM_NAMES = {"U-Boot"}


def _base_ship_name(name: Optional[str]) -> Optional[str]:
    if not isinstance(name, str):
        return None
    n = name.strip()
    if not n:
        return None
    return n.split(" #", 1)[0].strip()


def _parse_ships(data: Dict[str, Any]) -> Tuple[List[Set[Coord]], List[Dict[str, Any]]]:
    ships_raw = data.get("ships")
    if not isinstance(ships_raw, list):
        raise ValueError("ships must be a list")

    ships: List[Set[Coord]] = []
    meta: List[Dict[str, Any]] = []

    for ship_raw in ships_raw:
        ship_name: Optional[str] = None
        immune_override: Optional[bool] = None
        cells_raw = None

        if isinstance(ship_raw, dict):
            ship_name = ship_raw.get("name")
            if "immune_to_napalm" in ship_raw:
                immune_override = bool(ship_raw.get("immune_to_napalm"))
            cells_raw = ship_raw.get("cells")
        else:
            cells_raw = ship_raw

        if not isinstance(cells_raw, list) or len(cells_raw) == 0:
            raise ValueError("each ship must be a non-empty list of coordinates (or dict with cells)")

        ship_cells: Set[Coord] = set()
        for cell in cells_raw:
            if (
                not isinstance(cell, (list, tuple))
                or len(cell) != 2
                or not isinstance(cell[0], int)
                or not isinstance(cell[1], int)
            ):
                raise ValueError("each cell must be [row, col] ints")
            r, c = int(cell[0]), int(cell[1])
            if not _in_bounds((r, c)):
                raise ValueError("cell out of bounds")
            ship_cells.add((r, c))

        ships.append(ship_cells)

        base_name = _base_ship_name(ship_name)

        immune = immune_override if immune_override is not None else bool(base_name in IMMUNE_TO_NAPALM_NAMES)

        meta.append({
            "name": base_name,
            "immune_to_napalm": immune,
        })

    return ships, meta


def _board_from_ships(ships: List[Set[Coord]], ships_meta: List[Dict[str, Any]]) -> Dict[str, Any]:
    occupied: Set[Coord] = set()
    ship_by_cell: Dict[Coord, int] = {}

    for idx, s in enumerate(ships):
        occupied |= s
        for cell in s:
            ship_by_cell[cell] = idx

    return {
        "ships": ships,
        "ships_meta": ships_meta,
        "ship_by_cell": ship_by_cell,
        "occupied": occupied,
        "hits": set(),
        "shots": set(),
        "destroyed_ships": set(),
        "napalm": set(),
    }


def _check_destroyed(board: Dict[str, Any], hit_cell: Coord) -> Tuple[bool, List[List[int]]]:
    ships: List[Set[Coord]] = board["ships"]
    hits: Set[Coord] = board["hits"]

    for idx, ship in enumerate(ships):
        if hit_cell in ship:
            if ship.issubset(hits):
                board["destroyed_ships"].add(idx)
                destroyed_cells = [[r, c] for (r, c) in ship]
                return True, destroyed_cells
            break
    return False, []


def _all_ships_destroyed(board: Dict[str, Any]) -> bool:
    ships: List[Set[Coord]] = board["ships"]
    destroyed: Set[int] = board["destroyed_ships"]
    return len(ships) > 0 and len(destroyed) == len(ships)


def _apply_shot_to_board(target_board: Dict[str, Any], cell: Coord) -> Dict[str, Any]:
    if not _in_bounds(cell):
        return {"ok": False, "error": "Out of bounds"}

    if cell in target_board["shots"]:
        return {"ok": False, "error": "Cell already shot"}

    target_board["shots"].add(cell)
    # Normal shot löscht Napalm-Markierung wie im Client
    target_board["napalm"].discard(cell)

    hit = cell in target_board["occupied"]
    destroyed = False
    destroyed_cells: List[List[int]] = []

    if hit:
        target_board["hits"].add(cell)
        destroyed, destroyed_cells = _check_destroyed(target_board, cell)

    return {
        "ok": True,
        "hit": hit,
        "destroyed": destroyed,
        "destroyed_cells": destroyed_cells,
        "napalm_only": False,
    }


def _ship_idx_for_cell(target_board: Dict[str, Any], cell: Coord) -> Optional[int]:
    ship_by_cell: Dict[Coord, int] = target_board.get("ship_by_cell", {})
    return ship_by_cell.get(cell)


def _is_napalm_immune_cell(target_board: Dict[str, Any], cell: Coord) -> bool:
    idx = _ship_idx_for_cell(target_board, cell)
    if idx is None:
        return False
    meta: List[Dict[str, Any]] = target_board.get("ships_meta", [])
    if 0 <= idx < len(meta):
        return bool(meta[idx].get("immune_to_napalm", False))
    return False


def _apply_napalm_mark(target_board: Dict[str, Any], cell: Coord) -> Dict[str, Any]:
    if not _in_bounds(cell):
        return {"ok": False, "error": "Out of bounds"}

    if cell in target_board["shots"]:
        return {"ok": False, "error": "Cell already shot"}

    target_board["napalm"].add(cell)
    return {
        "ok": True,
        "hit": False,
        "destroyed": False,
        "destroyed_cells": [],
        "napalm_only": True,
    }


def _apply_napalm_shot_rules(target_board: Dict[str, Any], cell: Coord) -> Dict[str, Any]:
    if not _in_bounds(cell):
        return {"ok": False, "error": "Out of bounds"}

    if cell in target_board["shots"]:
        return {"ok": False, "error": "Cell already shot"}

    has_ship = cell in target_board["occupied"]
    if not has_ship:
        return _apply_napalm_mark(target_board, cell)

    # ✅ HIER ist der wichtige Teil:
    if _is_napalm_immune_cell(target_board, cell):
        return _apply_napalm_mark(target_board, cell)

    return _apply_shot_to_board(target_board, cell)