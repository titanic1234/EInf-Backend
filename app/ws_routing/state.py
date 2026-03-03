from app.ws_routing.types import GRID_SIZE, Coord

def _ensure_room_mp_state(room) -> None:
    if not hasattr(room, "boards"):
        room.boards = {}  # type: ignore[attr-defined]
    if not hasattr(room, "phase"):
        room.phase = "lobby"
    if not hasattr(room, "turn"):
        room.turn = "host"

    # NEW: aktive Feuer (Napalm)
    if not hasattr(room, "fires"):
        # Liste von Fire-Objekten (dict)
        room.fires = []  # type: ignore[attr-defined]



def _other_role(role: str) -> str:
    return "guest" if role == "host" else "host"



def _in_bounds(cell: Coord) -> bool:
    r, c = cell
    return 0 <= r < GRID_SIZE and 0 <= c < GRID_SIZE
