# app/ws_routing/fire_logic.py



# Logic mit KI aus battle.py für Server anpassen lassen



import random

from app.ws_routing.state import _in_bounds, _other_role
from app.ws_routing.board_logic import _apply_napalm_shot_rules, _all_ships_destroyed


def _neighbors4(cell):
    r, c = cell
    cand = [(r - 1, c), (r + 1, c), (r, c - 1), (r, c + 1)]
    return [x for x in cand if _in_bounds(x)]


async def _tick_all_fires(room, code: str, broadcast) -> None:
    """
    1 Tick für alle aktiven Feuer.

    Fire:
      {
        "target_role": "host"/"guest",
        "turns_left": int,
        "burning_cells": set((r,c)),
        "expanded_to": set((r,c))
      }
    """
    fires = getattr(room, "fires", None)
    if not fires:
        return

    tick_results = []
    game_over_winner = None

    for fire in list(fires):
        if fire.get("turns_left", 0) <= 0:
            continue

        target_role = fire["target_role"]
        target_board = room.boards.get(target_role)
        if not target_board:
            fire["turns_left"] = 0
            continue

        # Kandidaten sammeln: von allen brennenden Zellen aus 4er-Nachbarn
        candidates = set()
        for cell in fire["burning_cells"]:
            for nb in _neighbors4(cell):
                if nb in fire["expanded_to"]:
                    continue

                # bereits "normal beschossen" => als visited markieren und skip
                if nb in target_board["shots"]:
                    fire["expanded_to"].add(nb)
                    continue
                candidates.add(nb)

        if not candidates:
            fire["turns_left"] -= 1
            continue

        spread_targets = list(candidates)
        random.shuffle(spread_targets)
        spread_targets = spread_targets[:3]

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


    room.fires = [f for f in room.fires if f.get("turns_left", 0) > 0]

    if tick_results:
        await broadcast({
            "type": "fire_tick",
            "results": tick_results,
        })

    if game_over_winner:
        room.phase = "finished"
        await broadcast({"type": "game_over", "winner": game_over_winner})