from typing import Any, Dict, List, Set, Tuple
from app.ws_routing.types import Coord
from app.ws_routing.state import _in_bounds



def _parse_ships(data: Dict[str, Any]) -> List[Set[Coord]]:
    ships_raw = data.get("ships")
    if not isinstance(ships_raw, list):
        raise ValueError("ships must be a list")

    ships: List[Set[Coord]] = []
    for ship_raw in ships_raw:
        if not isinstance(ship_raw, list) or len(ship_raw) == 0:
            raise ValueError("each ship must be a non-empty list of coordinates")

        ship_cells: Set[Coord] = set()
        for cell in ship_raw:
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

    return ships



def _board_from_ships(ships: List[Set[Coord]]) -> Dict[str, Any]:
    occupied: Set[Coord] = set()
    for s in ships:
        occupied |= s
    return {
        "ships": ships,
        "occupied": occupied,
        "hits": set(),
        "shots": set(),
        "destroyed_ships": set(),
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
    return 0 < len(ships) == len(destroyed)



def _apply_shot_to_board(target_board: Dict[str, Any], cell: Coord) -> Dict[str, Any]:
    if not _in_bounds(cell):
        return {"ok": False, "error": "Out of bounds"}

    if cell in target_board["shots"]:
        return {"ok": False, "error": "Cell already shot"}

    target_board["shots"].add(cell)

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
    }