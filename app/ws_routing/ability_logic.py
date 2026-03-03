from typing import Any, Dict, List
from app.ws_routing.types import Coord
from app.ws_routing.state import _other_role, _in_bounds
from app.ws_routing.board_logic import _apply_shot_to_board, _all_ships_destroyed
from app.ws_routing.fire_logic import _tick_all_fires



def _ability_targets(ability: str, row: int, col: int) -> List[Coord]:
    if ability == "airstrike":
        return [(row, col), (row - 1, col), (row + 1, col), (row, col - 1), (row, col + 1)]
    if ability == "sonar":
        return [(r, c) for r in range(row - 1, row + 2) for c in range(col - 1, col + 2)]
    if ability == "napalm":
        return [(row, col)]
    return [(row, col)]


async def handle_ability(room, code: str, role: str, data: Dict[str, Any], broadcast, websocket_send_json):

    ability = data.get("ability")
    if ability not in ("airstrike", "sonar", "napalm", "guided"):
        await websocket_send_json({"type": "error", "detail": "Unknown ability"})
        return

    target_role = _other_role(role)
    target_board = room.boards.get(target_role)
    if not target_board:
        await websocket_send_json({"type": "error", "detail": "Opponent board not set yet"})
        return

    # guided
    if ability == "guided":
        candidates = list(target_board["occupied"] - target_board["shots"])
        if not candidates:
            await websocket_send_json({"type": "error", "detail": "No valid guided target"})
            return
        targets = [candidates[0]]
    else:
        x = data.get("x")
        y = data.get("y")
        if not isinstance(x, int) or not isinstance(y, int):
            await websocket_send_json({"type": "error", "detail": "Invalid coordinates"})
            return
        targets = [c for c in _ability_targets(ability, y, x) if _in_bounds(c)]

    # sonar
    if ability == "sonar":
        found = []
        for (r, c) in targets:
            if (r, c) in target_board["occupied"] and (r, c) not in target_board["shots"]:
                found.append([r, c])

        await websocket_send_json({
            "type": "sonar_result",
            "by": role,
            "cells": [[r, c] for (r, c) in targets],
            "found": found,
        })

        room.turn = _other_role(role)
        await broadcast(code, {"type": "turn_update", "turn": room.turn})
        await _tick_all_fires(room, code, broadcast)
        return

    # napalm
    if ability == "napalm":
        (nr, nc) = targets[0]
        res0 = _apply_shot_to_board(target_board, (nr, nc))
        if not res0["ok"]:
            await websocket_send_json({"type": "error", "detail": res0["error"]})
            return

        hit0 = bool(res0["hit"])
        destroyed0 = bool(res0["destroyed"])
        destroyed_cells0 = res0["destroyed_cells"]

        room.fires.append({
            "target_role": target_role,
            "turns_left": 3,
            "burning_cells": {(nr, nc)},
            "expanded_to": {(nr, nc)},
        })

        room.turn = _other_role(role)

        await broadcast(code, {
            "type": "ability_result",
            "by": role,
            "ability": "napalm",
            "results": [{
                "row": nr,
                "col": nc,
                "hit": hit0,
                "destroyed": destroyed0,
                "destroyed_cells": destroyed_cells0,
            }],
            "next_turn": room.turn,
            "fire_started": True,
            "fire_origin": {"row": nr, "col": nc, "target_role": target_role},
        })

        if _all_ships_destroyed(target_board):
            room.phase = "finished"
            await broadcast(code, {"type": "game_over", "winner": role})
            return

        await _tick_all_fires(room, code, broadcast)
        return

    # airstrike / guided
    results = []
    any_hit = False
    all_destroyed_cells: List[List[int]] = []

    for (r, c) in targets:
        res = _apply_shot_to_board(target_board, (r, c))
        if not res["ok"]:
            continue

        hit = bool(res["hit"])
        destroyed = bool(res["destroyed"])
        destroyed_cells = res["destroyed_cells"]

        any_hit = any_hit or hit
        if destroyed and destroyed_cells:
            all_destroyed_cells.extend(destroyed_cells)

        results.append({
            "row": r,
            "col": c,
            "hit": hit,
            "destroyed": destroyed,
            "destroyed_cells": destroyed_cells,
        })

    if not any_hit:
        room.turn = _other_role(role)

    await broadcast(code, {
        "type": "ability_result",
        "by": role,
        "ability": ability,
        "results": results,
        "next_turn": room.turn,
    })

    if all_destroyed_cells:
        await broadcast(code, {"type": "destroyed_update", "cells": all_destroyed_cells})

    if _all_ships_destroyed(target_board):
        room.phase = "finished"
        await broadcast(code, {"type": "game_over", "winner": role})
        return

    await _tick_all_fires(room, code, broadcast)