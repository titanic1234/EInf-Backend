# app/ws_routing/ability_logic.py

#Ability Logic mit KI aus Singleplayer übertragen


from typing import List
from app.ws_routing.types import Coord
from app.ws_routing.state import _in_bounds


def _ability_targets(ability: str, row: int, col: int) -> List[Coord]:
    if ability == "airstrike":
        cells = [(row, col), (row - 1, col), (row + 1, col), (row, col - 1), (row, col + 1)]
        return [c for c in cells if _in_bounds(c)]
    if ability == "sonar":
        cells = [(r, c) for r in range(row - 1, row + 2) for c in range(col - 1, col + 2)]
        return [c for c in cells if _in_bounds(c)]
    if ability == "napalm":
        return [(row, col)] if _in_bounds((row, col)) else []
    return [(row, col)] if _in_bounds((row, col)) else []