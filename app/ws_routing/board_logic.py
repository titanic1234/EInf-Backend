# app/ws_routing/board_logic.py



from __future__ import annotations
from typing import Any
from app.ws_routing.state import _in_bounds


# Basenames, die Napalm NICHT beschädigen darf
IMMUNE_TO_NAPALM_NAMES = {"U-Boot"}

"""Returned den reinen Schiffsname"""
def _base_ship_name(name: str | None) -> str | None:
    if not isinstance(name, str):
        return None
    name = name.strip()
    if not name:
        return None
    return name.split(" #", 1)[0].strip()

"""Verarbeitet Position, Name und Besonderheiten der Schiffe"""
def _parse_ships(data: dict) -> tuple[list[set[tuple[int, int]]], list[dict[str, Any]]]:
    """
    Akzeptiert:
      ships = [
        [[row,col], ...],                           # legacy
        {"name":"U-Boot", "cells":[[r,c],...]}       # optional meta
        {"cells":[...], "immune_to_napalm": True}
      ]
    """
    ships_raw = data.get("ships")
    if not isinstance(ships_raw, list):
        raise ValueError("ships must be a list")

    ships: list[set[tuple[int, int]]] = []
    meta: list[dict[str, Any]] = []

    for ship_raw in ships_raw:
        ship_name = None
        immune_override = None

        if isinstance(ship_raw, dict):
            ship_name = ship_raw.get("name")
            if "immune_to_napalm" in ship_raw:
                immune_override = bool(ship_raw.get("immune_to_napalm"))
            cells_raw = ship_raw.get("cells")
        else:
            cells_raw = ship_raw

        if not isinstance(cells_raw, list) or not cells_raw:
            raise ValueError("each ship must be a non-empty list of coordinates (or dict with cells)")

        ship_cells: set[tuple[int, int]] = set()
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
        immune_default = bool(base_name in IMMUNE_TO_NAPALM_NAMES)
        immune = immune_default if immune_override is None else bool(immune_override)

        meta.append({
            "name": base_name,
            "immune_to_napalm": immune,
        })

    return ships, meta

"""Returned ein Board anhand der Schiffe"""
def _board_from_ships(ships: list[set[tuple[int, int]]], ships_meta: list[dict[str, Any]]) -> dict[str, Any]:
    occupied: set[tuple[int, int]] = set()
    ship_by_cell: dict[tuple[int, int], int] = {}

    for idx, ship in enumerate(ships):
        occupied |= ship
        for cell in ship:
            ship_by_cell[cell] = idx

    return {
        "ships": ships,
        "ships_meta": ships_meta,
        "ship_by_cell": ship_by_cell,
        "occupied": occupied,
        "hits": set(),
        "shots": set(),          # normale Shots (blocken nochmal schießen)
        "destroyed_ships": set(),
        "napalm": set(),         # napalm-only marks
    }

"""Überprüft ob ein Schiff vollständig zerstört wurde"""
def _check_destroyed(board: dict[str, Any], hit_cell: tuple[int, int]) -> tuple[bool, list[list[int]]]:
    ships: list[set[tuple[int, int]]] = board["ships"]
    hits: set[tuple[int, int]] = board["hits"]

    for idx, ship in enumerate(ships):
        if hit_cell not in ship:
            continue
        if ship.issubset(hits):
            board["destroyed_ships"].add(idx)
            return True, [[r, c] for (r, c) in ship]
        return False, []

    return False, []

"""Überprüft ob alle Schiffe zerstört wurden"""
def _all_ships_destroyed(board: dict[str, Any]) -> bool:
    ships: list[set[tuple[int, int]]] = board["ships"]
    destroyed: set[int] = board["destroyed_ships"]
    return 0 < len(ships) == len(destroyed)

"""Führt einen Schuss auf das Board aus"""
def _apply_shot_to_board(board: dict[str, Any], cell: tuple[int, int]) -> dict[str, Any]:
    if not _in_bounds(cell):
        return {"ok": False, "error": "Out of bounds"}

    if cell in board["shots"]:
        return {"ok": False, "error": "Cell already shot"}

    board["shots"].add(cell)
    board["napalm"].discard(cell)  # normal shot entfernt napalm mark

    hit = cell in board["occupied"]
    destroyed = False
    destroyed_cells: list[list[int]] = []

    if hit:
        board["hits"].add(cell)
        destroyed, destroyed_cells = _check_destroyed(board, cell)

    return {
        "ok": True,
        "hit": hit,
        "destroyed": destroyed,
        "destroyed_cells": destroyed_cells,
        "napalm_only": False,
    }

"""Returned ein Schiff anhand der Zelle"""
def _ship_idx_for_cell(board: dict[str, Any], cell: tuple[int, int]) -> int | None:
    return board.get("ship_by_cell", {}).get(cell)


"""Überprüft ob ein Schiff immun gegen Napalm ist (UBoot)"""
def _is_napalm_immune_cell(board: dict[str, Any], cell: tuple[int, int]) -> bool:
    idx = _ship_idx_for_cell(board, cell)
    if idx is None:
        return False

    meta = board.get("ships_meta", [])
    if not (0 <= idx < len(meta)):
        return False

    return bool(meta[idx].get("immune_to_napalm", False))


"""Fügt ein Napalm-Marker zu einem Zellen hinzu"""
def _apply_napalm_mark(board: dict[str, Any], cell: tuple[int, int]) -> dict[str, Any]:
    if not _in_bounds(cell):
        return {"ok": False, "error": "Out of bounds"}

    if cell in board["shots"]:
        return {"ok": False, "error": "Cell already shot"}

    board["napalm"].add(cell)

    return {
        "ok": True,
        "hit": False,
        "destroyed": False,
        "destroyed_cells": [],
        "napalm_only": True,
    }

"""Überprüft ob napalm in der Zelle erlaubt ist"""
def _apply_napalm_shot_rules(board: dict[str, Any], cell: tuple[int, int]) -> dict[str, Any]:
    """
    Napalm-Regeln wie im Singleplayer:
    - Wasser => napalm_only (Marker)
    - U-Boot => napalm_only (Marker)
    - sonst => normaler Shot
    """
    if not _in_bounds(cell):
        return {"ok": False, "error": "Out of bounds"}

    if cell in board["shots"]:
        return {"ok": False, "error": "Cell already shot"}

    if cell not in board["occupied"]:
        return _apply_napalm_mark(board, cell)

    if _is_napalm_immune_cell(board, cell):
        return _apply_napalm_mark(board, cell)

    return _apply_shot_to_board(board, cell)