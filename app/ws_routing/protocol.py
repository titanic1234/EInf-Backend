# app/ws_routing/protocol.py

from __future__ import annotations
from typing import Any, Awaitable, Callable, Dict, List

from app.ws_routing.state import _other_role
from app.ws_routing.ability_logic import _ability_targets
from app.ws_routing.board_logic import (
    _apply_shot_to_board,
    _apply_napalm_shot_rules,
    _all_ships_destroyed,
    _parse_ships,
    _board_from_ships,
)
from app.ws_routing.fire_logic import _tick_all_fires
from app.ws_routing.state import _in_bounds


SendFn = Callable[[Dict[str, Any]], Awaitable[None]]
BroadcastFn = Callable[[Dict[str, Any]], Awaitable[None]]


class Protocol:
    """
    Enthält die gesamte WS-Game-Logik. WS-Handler ruft nur handle_message().
    """

    def __init__(self, room, code: str, role: str, send: SendFn, broadcast: BroadcastFn):
        self.room = room
        self.code = code
        self.role = role
        self.send = send
        self.broadcast = broadcast

    async def send_presence(self, connections_for_code: Dict[str, Any]) -> None:
        await self.broadcast({
            "type": "presence",
            "host_connected": "host" in connections_for_code,
            "guest_connected": "guest" in connections_for_code,
            "host_name": (self.room.host.name or "") if self.room.host else "",
            "guest_name": (self.room.guest.name or "") if self.room.guest else "",
            "host_board_set": bool(getattr(self.room, "boards", {}).get("host")),
            "guest_board_set": bool(getattr(self.room, "boards", {}).get("guest")),
        })

    async def handle_message(self, data: Dict[str, Any]) -> None:
        msg_type = data.get("type")

        match msg_type:
            case "host_name":
                self.room.host.name = data.get("name")

            case "set_board":
                await self._handle_set_board(data)

            case "ready":
                await self._handle_ready()

            case "shot":
                await self._handle_shot(data)

            case "ability":
                await self._handle_ability(data)

            case _:
                await self.send({"type": "error", "detail": f"Unknown message type: {msg_type}"})


    async def _handle_set_board(self, data: Dict[str, Any]) -> None:
        try:
            ships, meta = _parse_ships(data)
            self.room.boards[self.role] = _board_from_ships(ships, meta)  # type: ignore[attr-defined]
        except Exception as e:
            await self.send({"type": "error", "detail": f"Invalid set_board payload: {e}"})
            return

        await self.broadcast({
            "type": "board_set",
            "role": self.role,
            "host_board_set": bool(self.room.boards.get("host")),   # type: ignore[attr-defined]
            "guest_board_set": bool(self.room.boards.get("guest")), # type: ignore[attr-defined]
        })


    async def _handle_ready(self) -> None:
        if self.role == "host":
            self.room.host.ready = True
        elif self.role == "guest" and self.room.guest:
            self.room.guest.ready = True

        await self.broadcast({
            "type": "ready_update",
            "host_ready": self.room.host.ready,
            "guest_ready": self.room.guest.ready if self.room.guest else False,
            "host_name": (self.room.host.name or "") if self.room.host else "",
            "guest_name": (self.room.guest.name or "") if self.room.guest else "",
        })

        host_set = bool(getattr(self.room, "boards", {}).get("host"))
        guest_set = bool(getattr(self.room, "boards", {}).get("guest"))

        if self.room.guest and self.room.host.ready and self.room.guest.ready and host_set and guest_set:
            self.room.phase = "playing"
            await self.broadcast({"type": "game_started", "turn": self.room.turn})


    async def _handle_shot(self, data: Dict[str, Any]) -> None:
        if self.room.phase != "playing":
            await self.send({"type": "error", "detail": "Game not running"})
            return

        if self.room.turn != self.role:
            await self.send({"type": "error", "detail": "Not your turn"})
            return

        x = data.get("x")  # col
        y = data.get("y")  # row
        if not isinstance(x, int) or not isinstance(y, int):
            await self.send({"type": "error", "detail": "Invalid coordinates"})
            return

        target_role = _other_role(self.role)
        target_board = self.room.boards.get(target_role)  # type: ignore[attr-defined]
        if not target_board:
            await self.send({"type": "error", "detail": "Opponent board not set yet"})
            return

        res = _apply_shot_to_board(target_board, (y, x))
        if not res["ok"]:
            await self.send({"type": "error", "detail": res["error"]})
            return

        hit = bool(res["hit"])
        destroyed = bool(res["destroyed"])
        destroyed_cells = res["destroyed_cells"]

        # Turn nur bei MISS wechseln (deine Regel)
        if not hit:
            self.room.turn = _other_role(self.role)

        await self.broadcast({
            "type": "shot_result",
            "by": self.role,
            "x": x,
            "y": y,
            "hit": hit,
            "destroyed": destroyed,
            "destroyed_cells": destroyed_cells,
            "next_turn": self.room.turn,
        })

        if _all_ships_destroyed(target_board):
            self.room.phase = "finished"
            await self.broadcast({"type": "game_over", "winner": self.role})
            return

        await _tick_all_fires(self.room, self.code, self.broadcast)


    async def _handle_ability(self, data: Dict[str, Any]) -> None:
        if self.room.phase != "playing":
            await self.send({"type": "error", "detail": "Game not running"})
            return

        if self.room.turn != self.role:
            await self.send({"type": "error", "detail": "Not your turn"})
            return

        ability = data.get("ability")
        if ability not in ("airstrike", "sonar", "napalm", "guided"):
            await self.send({"type": "error", "detail": "Unknown ability"})
            return

        target_role = _other_role(self.role)
        target_board = self.room.boards.get(target_role)  # type: ignore[attr-defined]
        if not target_board:
            await self.send({"type": "error", "detail": "Opponent board not set yet"})
            return

        # guided: server pick
        if ability == "guided":
            candidates = list(target_board["occupied"] - target_board["shots"])
            if not candidates:
                await self.send({"type": "error", "detail": "No valid guided target"})
                return
            # random wie früher (du hattest erst candidates[0])
            import random
            targets = [random.choice(candidates)]
        else:
            x = data.get("x")
            y = data.get("y")
            if not isinstance(x, int) or not isinstance(y, int):
                await self.send({"type": "error", "detail": "Invalid coordinates"})
                return
            targets = [c for c in _ability_targets(ability, y, x) if _in_bounds(c)]

        # sonar: scan only
        if ability == "sonar":
            found = []
            for (r, c) in targets:
                if (r, c) in target_board["occupied"] and (r, c) not in target_board["shots"]:
                    found.append([r, c])

            await self.send({
                "type": "sonar_result",
                "by": self.role,
                "cells": [[r, c] for (r, c) in targets],
                "found": found,
            })

            self.room.turn = _other_role(self.role)
            await self.broadcast({"type": "turn_update", "turn": self.room.turn})
            await _tick_all_fires(self.room, self.code, self.broadcast)
            return

        # napalm: singleplayer rules + fire state
        if ability == "napalm":
            if not targets:
                await self.send({"type": "error", "detail": "Invalid napalm target"})
                return
            (nr, nc) = targets[0]

            res0 = _apply_napalm_shot_rules(target_board, (nr, nc))
            if not res0["ok"]:
                await self.send({"type": "error", "detail": res0["error"]})
                return

            # Feuer erzeugen: 3 Ticks
            self.room.fires.append({
                "target_role": target_role,
                "turns_left": 3,
                "burning_cells": {(nr, nc)},
                "expanded_to": {(nr, nc)},
            })  # type: ignore[attr-defined]

            self.room.turn = _other_role(self.role)

            await self.broadcast({
                "type": "ability_result",
                "by": self.role,
                "ability": "napalm",
                "results": [{
                    "row": nr,
                    "col": nc,
                    "hit": bool(res0["hit"]),
                    "destroyed": bool(res0["destroyed"]),
                    "destroyed_cells": res0.get("destroyed_cells", []),
                    "napalm_only": bool(res0.get("napalm_only", False)),
                }],
                "next_turn": self.room.turn,
                "fire_started": True,
                "fire_origin": {"row": nr, "col": nc, "target_role": target_role},
            })

            if _all_ships_destroyed(target_board):
                self.room.phase = "finished"
                await self.broadcast({"type": "game_over", "winner": self.role})
                return

            await _tick_all_fires(self.room, self.code, self.broadcast)
            return

        # airstrike: multiple normal shots
        results: List[Dict[str, Any]] = []
        any_hit = False
        all_destroyed_cells: List[List[int]] = []

        for (r, c) in targets:
            res = _apply_shot_to_board(target_board, (r, c))
            if not res["ok"]:
                continue
            hit = bool(res["hit"])
            destroyed = bool(res["destroyed"])
            destroyed_cells = res.get("destroyed_cells", [])

            any_hit = any_hit or hit
            if destroyed and destroyed_cells:
                all_destroyed_cells.extend(destroyed_cells)

            results.append({
                "row": r,
                "col": c,
                "hit": hit,
                "destroyed": destroyed,
                "destroyed_cells": destroyed_cells,
            })

        if not any_hit:
            self.room.turn = _other_role(self.role)

        await self.broadcast({
            "type": "ability_result",
            "by": self.role,
            "ability": ability,
            "results": results,
            "next_turn": self.room.turn,
        })

        if all_destroyed_cells:
            await self.broadcast({"type": "destroyed_update", "cells": all_destroyed_cells})

        if _all_ships_destroyed(target_board):
            self.room.phase = "finished"
            await self.broadcast({"type": "game_over", "winner": self.role})
            return

        await _tick_all_fires(self.room, self.code, self.broadcast)