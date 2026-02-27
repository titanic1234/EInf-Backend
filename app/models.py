from dataclasses import dataclass, field
from typing import Optional


BOARD_SIZE = 12


@dataclass
class PlayerState:
    token: str
    name: str
    ships: list[list[tuple[int, int]]] = field(default_factory=list)
    shots_received: set[tuple[int, int]] = field(default_factory=set)
    ready: bool = False


@dataclass
class GameRoom:
    code: str
    host: PlayerState
    guest: Optional[PlayerState] = None
    phase: str = "waiting"   # waiting, setup, playing, finished
    turn: str = "host"       # host or guest
    winner: Optional[str] = None