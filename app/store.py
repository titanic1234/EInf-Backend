import secrets
import string
from app.models import GameRoom, PlayerState

games: dict[str, GameRoom] = {}


def generate_code(length: int = 6) -> str:
    alphabet = string.ascii_uppercase + string.digits
    while True:
        code = "".join(secrets.choice(alphabet) for _ in range(length))
        if code not in games:
            return code


def generate_token() -> str:
    return secrets.token_urlsafe(24)


def create_room() -> tuple[GameRoom, str]:
    code = generate_code()
    token = generate_token()
    room = GameRoom(
        code=code,
        host=PlayerState(token=token),
    )
    games[code] = room
    return room, token


def get_player_role(room: GameRoom, token: str) -> str | None:
    if room.host.token == token:
        return "host"
    if room.guest and room.guest.token == token:
        return "guest"
    return None