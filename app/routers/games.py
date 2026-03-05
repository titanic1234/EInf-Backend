# games.py

"""Routing für create / join game"""

from fastapi import APIRouter, HTTPException
from app.schemas import (
    JoinGameRequest,
    GameCreatedResponse,
    JoinGameResponse,
    CreateGameRequest,
)
from app.store import create_room, games, generate_token
from app.models import PlayerState

router = APIRouter()


@router.post("/games", response_model=GameCreatedResponse)
def create_game(payload: CreateGameRequest):
    room, token = create_room(theme=payload.theme)
    return GameCreatedResponse(
        code=room.code,
        player_token=token,
        role="host",
    )


@router.post("/games/join", response_model=JoinGameResponse)
def join_game(payload: JoinGameRequest):
    room = games.get(payload.code)
    if not room:
        raise HTTPException(status_code=404, detail="Game not found")

    if room.guest is not None:
        raise HTTPException(status_code=400, detail="Game already full")

    if room.phase != "waiting":
        raise HTTPException(status_code=400, detail="Game already started")

    token = generate_token()
    room.guest = PlayerState(token=token, name=payload.name)
    room.phase = "setup"

    return JoinGameResponse(
        code=room.code,
        player_token=token,
        role="guest",
        theme=room.theme
    )