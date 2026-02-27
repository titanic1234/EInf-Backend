from collections import defaultdict
from fastapi import WebSocket, WebSocketDisconnect
from app.store import games, get_player_role

connections: dict[str, dict[str, WebSocket]] = defaultdict(dict)


async def broadcast(code: str, message: dict):
    for ws in connections[code].values():
        await ws.send_json(message)


async def handle_websocket(websocket: WebSocket, code: str, token: str):
    room = games.get(code)
    if not room:
        await websocket.close(code=4004)
        return

    role = get_player_role(room, token)
    if not role:
        await websocket.close(code=4001)
        return

    await websocket.accept()
    connections[code][role] = websocket

    await broadcast(code, {
        "type": "presence",
        "host_connected": "host" in connections[code],
        "guest_connected": "guest" in connections[code],
    })

    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type")

            if msg_type == "ready":
                if role == "host":
                    room.host.ready = True
                elif room.guest:
                    room.guest.ready = True

                await broadcast(code, {
                    "type": "ready_update",
                    "host_ready": room.host.ready,
                    "guest_ready": room.guest.ready if room.guest else False,
                })

                if room.guest and room.host.ready and room.guest.ready:
                    room.phase = "playing"
                    await broadcast(code, {
                        "type": "game_started",
                        "turn": room.turn,
                    })

            elif msg_type == "shot":
                if room.phase != "playing":
                    await websocket.send_json({"type": "error", "detail": "Game not running"})
                    continue

                if room.turn != role:
                    await websocket.send_json({"type": "error", "detail": "Not your turn"})
                    continue

                x = data.get("x")
                y = data.get("y")

                if not isinstance(x, int) or not isinstance(y, int):
                    await websocket.send_json({"type": "error", "detail": "Invalid coordinates"})
                    continue

                # Hier später echte Trefferlogik
                hit = False

                room.turn = "guest" if role == "host" else "host"

                await broadcast(code, {
                    "type": "shot_result",
                    "by": role,
                    "x": x,
                    "y": y,
                    "hit": hit,
                    "next_turn": room.turn,
                })

    except WebSocketDisconnect:
        connections[code].pop(role, None)
        await broadcast(code, {
            "type": "presence",
            "host_connected": "host" in connections[code],
            "guest_connected": "guest" in connections[code],
        })