from typing import Any, Dict

from app.ws_routing.state import _ensure_room_mp_state, _other_role
from app.ws_routing.board_logic import _parse_ships, _board_from_ships, _apply_shot_to_board, _all_ships_destroyed
from app.ws_routing.fire_logic import _tick_all_fires
from app.ws_routing.ability_logic import handle_ability

async def _send_presence(room, code: str, connections: dict, broadcast):
    await broadcast(code, {
        "type": "presence",
        "host_connected": "host" in connections[code],
        "guest_connected": "guest" in connections[code],
        "host_name": (room.host.name or "") if room.host else "",
        "guest_name": (room.guest.name or "") if room.guest else "",
        "host_board_set": bool(getattr(room, "boards", {}).get("host")),
        "guest_board_set": bool(getattr(room, "boards", {}).get("guest")),
        "grid_size": 12,
    })


async def _handle_message(
    *,
    room,
    code: str,
    role: str,
    data: Dict[str, Any],
    broadcast,
    websocket_send_json,
    connections
):
    """
    Enthält die komplette "Game-Logic" (wie vorher), aber kein WS accept/close.
    """
    _ensure_room_mp_state(room)

    msg_type = data.get("type")

    # set_board
    if msg_type == "set_board":
        try:
            ships = _parse_ships(data)
            room.boards[role] = _board_from_ships(ships)
        except Exception as e:
            await websocket_send_json({"type": "error", "detail": f"Invalid set_board payload: {e}"})
            return

        await broadcast(code, {
            "type": "board_set",
            "role": role,
            "host_board_set": bool(room.boards.get("host")),
            "guest_board_set": bool(room.boards.get("guest")),
        })
        return

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
            "host_name": (room.host.name or "") if room.host else "",
            "guest_name": (room.guest.name or "") if room.guest else "",
        })

        host_set = bool(getattr(room, "boards", {}).get("host"))
        guest_set = bool(getattr(room, "boards", {}).get("guest"))

        if room.guest and room.host.ready and room.guest.ready and host_set and guest_set:
            room.phase = "playing"
            await broadcast(code, {"type": "game_started", "turn": room.turn})
        return

    # shot
    if msg_type == "shot":
        if room.phase != "playing":
            await websocket_send_json({"type": "error", "detail": "Game not running"})
            return
        if room.turn != role:
            await websocket_send_json({"type": "error", "detail": "Not your turn"})
            return

        x = data.get("x")
        y = data.get("y")
        if not isinstance(x, int) or not isinstance(y, int):
            await websocket_send_json({"type": "error", "detail": "Invalid coordinates"})
            return

        target_role = _other_role(role)
        target_board = room.boards.get(target_role)
        if not target_board:
            await websocket_send_json({"type": "error", "detail": "Opponent board not set yet"})
            return

        res = _apply_shot_to_board(target_board, (y, x))
        if not res["ok"]:
            await websocket_send_json({"type": "error", "detail": res["error"]})
            return

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
            return

        # Nach jeder Aktion: 1 Feuer-Tick
        await _tick_all_fires(room, code, broadcast)
        return

    # ability
    if msg_type == "ability":
        if room.phase != "playing":
            await websocket_send_json({"type": "error", "detail": "Game not running"})
            return
        if room.turn != role:
            await websocket_send_json({"type": "error", "detail": "Not your turn"})
            return

        await handle_ability(room, code, role, data, broadcast, websocket_send_json)
        return

    await websocket_send_json({"type": "error", "detail": f"Unknown message type: {msg_type}"})