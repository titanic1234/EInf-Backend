# app/ws_routing/state.py

from app.ws_routing.types import GRID_SIZE, Coord

"""Überprüft ob Attribute vorhanden sind und setzt diese notfalls"""
def _ensure_room_mp_state(room) -> None:
    if not hasattr(room, "boards"):
        room.boards = {}  # type: ignore[attr-defined]
    if not hasattr(room, "phase"):
        room.phase = "lobby"
    if not hasattr(room, "turn"):
        room.turn = "host"
    if not hasattr(room, "fires"):
        room.fires = []  # type: ignore[attr-defined]

"""Returned die andere Rolle"""
def _other_role(role: str) -> str:
    return "guest" if role == "host" else "host"

"""Überprüft ob ein Zelle auf dem Board liegt"""
def _in_bounds(cell: Coord) -> bool:
    r, c = cell
    return 0 <= r < GRID_SIZE and 0 <= c < GRID_SIZE