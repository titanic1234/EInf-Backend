# app/ws_routing/protocol.py

from __future__ import annotations

import random
from typing import Any

from app.ws_routing.state import _other_role, _in_bounds
from app.ws_routing.ability_logic import _ability_targets
from app.ws_routing.board_logic import (
    _apply_shot_to_board,
    _apply_napalm_shot_rules,
    _all_ships_destroyed,
    _parse_ships,
    _board_from_ships,
)
from app.ws_routing.fire_logic import _tick_all_fires


class Protocol:
    """
    Enthält die gesamte WS-Game-Logik. WS-Handler ruft nur handle_message().
    """

    def __init__(self, room, code: str, role: str, send, broadcast):
        self.room = room
        self.code = code
        self.role = role
        self.send = send
        self.broadcast = broadcast

    # ------------------------------
    # public API
    # ------------------------------
    async def send_presence(self, connections_for_code: dict[str, Any]) -> None:
        await self.broadcast({
            "type": "presence",
            "host_connected": "host" in connections_for_code,
            "guest_connected": "guest" in connections_for_code,
            "host_name": (self.room.host.name or "") if self.room.host else "",
            "guest_name": (self.room.guest.name or "") if self.room.guest else "",
            "host_board_set": bool(getattr(self.room, "boards", {}).get("host")),
            "guest_board_set": bool(getattr(self.room, "boards", {}).get("guest")),
        })

    async def handle_message(self, data: dict[str, Any]) -> None:
        msg_type = data.get("type")

        if msg_type == "host_name":
            if self.room.host:
                self.room.host.name = data.get("name")
            return

        if msg_type == "set_board":
            await self._handle_set_board(data)
            return

        if msg_type == "ready":
            await self._handle_ready()
            return

        if msg_type == "shot":
            await self._handle_shot(data)
            return

        if msg_type == "ability":
            await self._handle_ability(data)
            return

        await self.send({"type": "error", "detail": f"Unknown message type: {msg_type}"})

    # ------------------------------
    # helpers
    # ------------------------------
    def _require_playing_and_turn(self) -> bool:
        return self.room.phase == "playing" and self.room.turn == self.role

    def _target_role(self) -> str:
        return _other_role(self.role)

    def _target_board(self):
        return getattr(self.room, "boards", {}).get(self._target_role())

    async def _tick_fires(self) -> None:
        await _tick_all_fires(self.room, self.code, self.broadcast)

    async def _maybe_game_over(self, target_board) -> bool:
        if _all_ships_destroyed(target_board):
            self.room.phase = "finished"
            await self.broadcast({"type": "game_over", "winner": self.role})
            return True
        return False

    # ------------------------------
    # set_board / ready
    # ------------------------------
    async def _handle_set_board(self, data: dict[str, Any]) -> None:
        try:
            ships, meta = _parse_ships(data)
            self.room.boards[self.role] = _board_from_ships(ships, meta)
        except Exception as e:
            await self.send({"type": "error", "detail": f"Invalid set_board payload: {e}"})
            return

        await self.broadcast({
            "type": "board_set",
            "role": self.role,
            "host_board_set": bool(self.room.boards.get("host")),
            "guest_board_set": bool(self.room.boards.get("guest")),
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

    # ------------------------------
    # shot
    # ------------------------------
    async def _handle_shot(self, data: dict[str, Any]) -> None:
        if self.room.phase != "playing":
            await self.send({"type": "error", "detail": "Game not running"})
            return

        if self.room.turn != self.role:
            await self.send({"type": "error", "detail": "Not your turn"})
            return

        x = data.get("x")
        y = data.get("y")
        if not isinstance(x, int) or not isinstance(y, int):
            await self.send({"type": "error", "detail": "Invalid coordinates"})
            return

        target_board = self._target_board()
        if not target_board:
            await self.send({"type": "error", "detail": "Opponent board not set yet"})
            return

        res = _apply_shot_to_board(target_board, (y, x))
        if not res["ok"]:
            await self.send({"type": "error", "detail": res["error"]})
            return

        hit = bool(res["hit"])
        destroyed = bool(res["destroyed"])

        # Turn nur bei MISS wechseln
        if not hit:
            self.room.turn = self._target_role()

        await self.broadcast({
            "type": "shot_result",
            "by": self.role,
            "x": x,
            "y": y,
            "hit": hit,
            "destroyed": destroyed,
            "destroyed_cells": res.get("destroyed_cells", []),
            "next_turn": self.room.turn,
        })

        if await self._maybe_game_over(target_board):
            return

        await self._tick_fires()

    # ------------------------------
    # ability
    # ------------------------------
    async def _handle_ability(self, data: dict[str, Any]) -> None:
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

        target_board = self._target_board()
        if not target_board:
            await self.send({"type": "error", "detail": "Opponent board not set yet"})
            return

        targets = await self._resolve_targets(ability, data, target_board)
        if targets is None:
            return  # error already sent

        # Sonar ist Scan-only und "kein Schuss" => Turn bleibt gleich
        if ability == "sonar":
            await self._handle_sonar(targets, target_board)
            await self._tick_fires()
            return

        if ability == "napalm":
            await self._handle_napalm(targets[0], target_board)
            return

        await self._handle_multi_shot_ability(ability, targets, target_board)

    async def _resolve_targets(self, ability: str, data: dict[str, Any], target_board):
        if ability == "guided":
            candidates = list(target_board["occupied"] - target_board["shots"])
            if not candidates:
                await self.send({"type": "error", "detail": "No valid guided target"})
                return None
            return [random.choice(candidates)]

        x = data.get("x")
        y = data.get("y")
        if not isinstance(x, int) or not isinstance(y, int):
            await self.send({"type": "error", "detail": "Invalid coordinates"})
            return None

        return [c for c in _ability_targets(ability, y, x) if _in_bounds(c)]

    async def _handle_sonar(self, targets, target_board):
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

        # Sonar ist kein Schuss: Turn bleibt gleich (deine Regel)
        self.room.turn = self.role
        await self.broadcast({"type": "turn_update", "turn": self.room.turn})

    async def _handle_napalm(self, target_cell, target_board):
        (nr, nc) = target_cell

        res0 = _apply_napalm_shot_rules(target_board, (nr, nc))
        if not res0["ok"]:
            await self.send({"type": "error", "detail": res0["error"]})
            return

        # Feuer erzeugen: 3 Ticks
        self.room.fires.append({
            "target_role": self._target_role(),
            "turns_left": 3,
            "burning_cells": {(nr, nc)},
            "expanded_to": {(nr, nc)},
        })

        # Napalm kostet Zug (wie bei dir)
        self.room.turn = self._target_role()

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
            "fire_origin": {"row": nr, "col": nc, "target_role": self._target_role()},
        })

        if await self._maybe_game_over(target_board):
            return

        await self._tick_fires()

    async def _handle_multi_shot_ability(self, ability: str, targets, target_board):
        results = []
        any_hit = False
        all_destroyed_cells = []

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

        # Turn nur bei "kein Hit" wechseln
        if not any_hit:
            self.room.turn = self._target_role()

        await self.broadcast({
            "type": "ability_result",
            "by": self.role,
            "ability": ability,
            "results": results,
            "next_turn": self.room.turn,
        })

        if all_destroyed_cells:
            await self.broadcast({"type": "destroyed_update", "cells": all_destroyed_cells})

        if await self._maybe_game_over(target_board):
            return

        await self._tick_fires()