# app/ws_routing/fire_logic.py

from typing import List, Set, Optional, Callable, Awaitable, Any, Dict
import random

from app.ws_routing.types import Coord
from app.ws_routing.state import _in_bounds, _other_role
from app.ws_routing.board_logic import _apply_napalm_shot_rules, _all_ships_destroyed


BroadcastFn = Callable[[Dict[str, Any]], Awaitable[None]]


def _neighbors4(cell: Coord) -> List[Coord]:
    r, c = cell
    cand = [(r - 1, c), (r + 1, c), (r, c - 1), (r, c + 1)]
    return [x for x in cand if _in_bounds(x)]


async def _tick_all_fires(room, code: str, broadcast: BroadcastFn) -> None:
    if not getattr(room, "fires", None):
        return

    tick_results = []
    game_over_winner: Optional[str] = None

    for fire in list(room.fires):  # type: ignore[attr-defined]
        if fire.get("turns_left", 0) <= 0:
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

                # Wenn schon normal geschossen: visuell nichts mehr -> "verbrauchen"
                if nb in target_board["shots"]:
                    fire["expanded_to"].add(nb)
                    continue

                candidates.add(nb)

        cand_list = list(candidates)
        random.shuffle(cand_list)
        spread_targets = cand_list[:3]

        new_burning = set()

        for cell in spread_targets:
            fire["expanded_to"].add(cell)
            new_burning.add(cell)

            res = _apply_napalm_shot_rules(target_board, cell)
            if not res["ok"]:
                continue

            tick_results.append({
                "target_role": target_role,
                "row": cell[0],
                "col": cell[1],
                "hit": bool(res["hit"]),
                "destroyed": bool(res["destroyed"]),
                "destroyed_cells": res.get("destroyed_cells", []),
                "napalm_only": bool(res.get("napalm_only", False)),
            })

        fire["burning_cells"] |= new_burning
        fire["turns_left"] -= 1

        if _all_ships_destroyed(target_board):
            game_over_winner = _other_role(target_role)

    # fertige Feuer entfernen
    room.fires = [f for f in room.fires if f.get("turns_left", 0) > 0]  # type: ignore[attr-defined]

    if tick_results:
        await broadcast({
            "type": "fire_tick",
            "results": tick_results,
        })

    if game_over_winner:
        room.phase = "finished"
        await broadcast({"type": "game_over", "winner": game_over_winner})