from pydantic import BaseModel


class CreateGameRequest(BaseModel):
    theme: str


class JoinGameRequest(BaseModel):
    name: str
    code: str



class GameCreatedResponse(BaseModel):
    code: str
    player_token: str
    role: str


class JoinGameResponse(BaseModel):
    code: str
    player_token: str
    role: str
    theme: str