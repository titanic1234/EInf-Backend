from typing import List, Set
import random

from app.ws_routing.types import Coord
from app.ws_routing.state import _in_bounds, _other_role
from app.ws_routing.board_logic import _apply_shot_to_board, _all_ships_destroyed


def _neighbors4(cell: Coord) -> List[Coord]:
    r, c = cell
    cand = [(r - 1, c), (r + 1, c), (r, c - 1), (r, c + 1)]
    return [x for x in cand if _in_bounds(x)]



async def _tick_all_fires(room, code: str, broadcast) -> None:
    """
    Führt 1 Tick für alle aktiven Feuer aus.
    Jede Fire hat:
      {
        "target_role": "host"/"guest",
        "turns_left": int,
        "burning_cells": set((r,c)),
        "expanded_to": set((r,c))
      }
    """
    if not getattr(room, "fires", None):
        return

    tick_results = []

    game_over_winner = None

    for fire in list(room.fires):  # type: ignore[attr-defined]
        if fire["turns_left"] <= 0:
            continue

        target_role = fire["target_role"]
        target_board = room.boards.get(target_role)  # type: ignore[attr-defined]
        if not target_board:
            fire["turns_left"] = 0
            continue

        candidates: Set[Coord] = set()
        for (r, c) in fire["burning_cells"]:
            for nb in _neighbors4((r, c)):
                if nb in fire["expanded_to"]:
                    continue
                if nb in target_board["shots"]:
                    fire["expanded_to"].add(nb)
                    continue
                candidates.add(nb)

        # bis zu 3 neue Zellen pro Tick
        cand_list = list(candidates)
        random.shuffle(cand_list)
        spread_targets = cand_list[:3]

        new_burning = set()
        any_destroyed_cells = []

        for cell in spread_targets:
            fire["expanded_to"].add(cell)
            new_burning.add(cell)

            res = _apply_shot_to_board(target_board, cell)
            if not res["ok"]:
                continue

            destroyed_cells = res["destroyed_cells"]
            if destroyed_cells:
                any_destroyed_cells.extend(destroyed_cells)

            tick_results.append({
                "target_role": target_role,
                "row": cell[0],
                "col": cell[1],
                "hit": bool(res["hit"]),
                "destroyed": bool(res["destroyed"]),
                "destroyed_cells": destroyed_cells,
            })

        fire["burning_cells"] |= new_burning
        fire["turns_left"] -= 1

        if _all_ships_destroyed(target_board):
            # Das Feuer hat das Spiel beendet -> Gewinner ist der ANDERE als target_role
            game_over_winner = _other_role(target_role)

    # Feuer entfernen, die fertig sind
    room.fires = [f for f in room.fires if f["turns_left"] > 0]  # type: ignore[attr-defined]

    if tick_results:
        await broadcast(code, {
            "type": "fire_tick",
            "results": tick_results,
        })

    if game_over_winner:
        room.phase = "finished"
        await broadcast(code, {"type": "game_over", "winner": game_over_winner})