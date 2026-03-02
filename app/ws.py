from collections import defaultdict
from typing import Any, Dict, List, Set, Tuple
from fastapi import WebSocket, WebSocketDisconnect

from app.store import games, get_player_role

# !!! ANPASSEN: Dein Client-Board ist 12x12 (A-L, 1-12)
GRID_SIZE = 12

connections: dict[str, dict[str, WebSocket]] = defaultdict(dict)

Coord = Tuple[int, int]  # (row, col)


async def broadcast(code: str, message: dict):
    for ws in connections[code].values():
        await ws.send_json(message)


def _ensure_room_mp_state(room) -> None:
    if not hasattr(room, "boards"):
        room.boards = {}  # type: ignore[attr-defined]
    if not hasattr(room, "phase"):
        room.phase = "lobby"
    if not hasattr(room, "turn"):
        room.turn = "host"


def _other_role(role: str) -> str:
    return "guest" if role == "host" else "host"


def _in_bounds(cell: Coord) -> bool:
    r, c = cell
    return 0 <= r < GRID_SIZE and 0 <= c < GRID_SIZE


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
    return len(ships) > 0 and len(destroyed) == len(ships)


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


def _ability_targets(ability: str, row: int, col: int) -> List[Coord]:
    if ability == "airstrike":
        return [(row, col), (row - 1, col), (row + 1, col), (row, col - 1), (row, col + 1)]
    if ability == "sonar":
        return [(r, c) for r in range(row - 1, row + 2) for c in range(col - 1, col + 2)]
    if ability == "napalm":
        return [(row, col)]
    return [(row, col)]


async def handle_websocket(websocket: WebSocket, code: str, token: str):
    room = games.get(code)
    if not room:
        await websocket.close(code=4004)
        return

    role = get_player_role(room, token)
    if not role:
        await websocket.close(code=4001)
        return

    _ensure_room_mp_state(room)

    await websocket.accept()
    connections[code][role] = websocket

    await broadcast(code, {
        "type": "presence",
        "host_connected": "host" in connections[code],
        "guest_connected": "guest" in connections[code],
        "host_name": room.host.name if room.host else "",
        "guest_name": room.guest.name if room.guest else "",
        "host_board_set": bool(getattr(room, "boards", {}).get("host")),
        "guest_board_set": bool(getattr(room, "boards", {}).get("guest")),
        "grid_size": GRID_SIZE,
    })

    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type")

            # set_board
            if msg_type == "set_board":
                try:
                    ships = _parse_ships(data)
                    room.boards[role] = _board_from_ships(ships)  # type: ignore[attr-defined]
                except Exception as e:
                    await websocket.send_json({"type": "error", "detail": f"Invalid set_board payload: {e}"})
                    continue

                await broadcast(code, {
                    "type": "board_set",
                    "role": role,
                    "host_board_set": bool(room.boards.get("host")),   # type: ignore[attr-defined]
                    "guest_board_set": bool(room.boards.get("guest")), # type: ignore[attr-defined]
                })
                continue

            # ready
            if msg_type == "ready":
                if role == "host":
                    room.host.ready = True
                elif role == "guest" and room.guest:
                    room.guest.ready = True

                await broadcast(code, {
                    "type": "ready_update",
                    "host_ready": room.host.ready,
                    "guest_ready": room.guest.ready if room.guest else False,
                    "host_name": room.host.name if room.host else "",
                    "guest_name": room.guest.name if room.guest else "",
                })

                host_set = bool(getattr(room, "boards", {}).get("host"))
                guest_set = bool(getattr(room, "boards", {}).get("guest"))

                if room.guest and room.host.ready and room.guest.ready and host_set and guest_set:
                    room.phase = "playing"
                    await broadcast(code, {"type": "game_started", "turn": room.turn})
                continue

            # shot
            if msg_type == "shot":
                if room.phase != "playing":
                    await websocket.send_json({"type": "error", "detail": "Game not running"})
                    continue

                if room.turn != role:
                    await websocket.send_json({"type": "error", "detail": "Not your turn"})
                    continue

                x = data.get("x")  # col
                y = data.get("y")  # row
                if not isinstance(x, int) or not isinstance(y, int):
                    await websocket.send_json({"type": "error", "detail": "Invalid coordinates"})
                    continue

                target_role = _other_role(role)
                target_board = room.boards.get(target_role)  # type: ignore[attr-defined]
                if not target_board:
                    await websocket.send_json({"type": "error", "detail": "Opponent board not set yet"})
                    continue

                res = _apply_shot_to_board(target_board, (y, x))
                if not res["ok"]:
                    await websocket.send_json({"type": "error", "detail": res["error"]})
                    continue

                hit = bool(res["hit"])
                destroyed = bool(res["destroyed"])
                destroyed_cells = res["destroyed_cells"]

                # Turn nur bei MISS wechseln
                if not hit:
                    room.turn = _other_role(role)

                await broadcast(code, {
                    "type": "shot_result",
                    "by": role,
                    "x": x,
                    "y": y,
                    "hit": hit,
                    "destroyed": destroyed,
                    "destroyed_cells": destroyed_cells,
                    "next_turn": room.turn,
                })

                if _all_ships_destroyed(target_board):
                    room.phase = "finished"
                    await broadcast(code, {"type": "game_over", "winner": role})
                continue

            # ability
            if msg_type == "ability":
                if room.phase != "playing":
                    await websocket.send_json({"type": "error", "detail": "Game not running"})
                    continue

                if room.turn != role:
                    await websocket.send_json({"type": "error", "detail": "Not your turn"})
                    continue

                ability = data.get("ability")
                if ability not in ("airstrike", "sonar", "napalm", "guided"):
                    await websocket.send_json({"type": "error", "detail": "Unknown ability"})
                    continue

                target_role = _other_role(role)
                target_board = room.boards.get(target_role)  # type: ignore[attr-defined]
                if not target_board:
                    await websocket.send_json({"type": "error", "detail": "Opponent board not set yet"})
                    continue

                # guided: server pick
                if ability == "guided":
                    candidates = list(target_board["occupied"] - target_board["shots"])
                    if not candidates:
                        await websocket.send_json({"type": "error", "detail": "No valid guided target"})
                        continue
                    targets = [candidates[0]]
                else:
                    x = data.get("x")
                    y = data.get("y")
                    if not isinstance(x, int) or not isinstance(y, int):
                        await websocket.send_json({"type": "error", "detail": "Invalid coordinates"})
                        continue
                    targets = [c for c in _ability_targets(ability, y, x) if _in_bounds(c)]

                if ability == "sonar":
                    found = []
                    for (r, c) in targets:
                        if (r, c) in target_board["occupied"] and (r, c) not in target_board["shots"]:
                            found.append([r, c])

                    await websocket.send_json({
                        "type": "sonar_result",
                        "by": role,
                        "cells": [[r, c] for (r, c) in targets],
                        "found": found,
                    })

                    # Sonar kostet Zug
                    room.turn = _other_role(role)
                    await broadcast(code, {"type": "turn_update", "turn": room.turn})
                    continue

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

                # Turn: nur bei "kein Hit" wechseln
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
                continue

            await websocket.send_json({"type": "error", "detail": f"Unknown message type: {msg_type}"})

    except WebSocketDisconnect:
        connections[code].pop(role, None)
        await broadcast(code, {
            "type": "presence",
            "host_connected": "host" in connections[code],
            "guest_connected": "guest" in connections[code],
        })