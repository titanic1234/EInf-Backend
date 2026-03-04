# app/ws_routing/ws_handler.py

from collections import defaultdict
from fastapi import WebSocket, WebSocketDisconnect

from app.store import games, get_player_role
from app.ws_routing.state import _ensure_room_mp_state
from app.ws_routing.protocol import Protocol

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

    _ensure_room_mp_state(room)

    await websocket.accept()
    connections[code][role] = websocket

    proto = Protocol(
        room=room,
        code=code,
        role=role,
        send=websocket.send_json,
        broadcast=lambda msg: broadcast(code, msg),
    )


    await proto.send_presence(connections[code])

    try:
        while True:
            data = await websocket.receive_json()
            await proto.handle_message(data)

    except WebSocketDisconnect:
        connections[code].pop(role, None)
        await broadcast(code, {
            "type": "presence",
            "host_connected": "host" in connections[code],
            "guest_connected": "guest" in connections[code],
        })