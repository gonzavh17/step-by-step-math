"""In-memory store for whiteboards (lists of steps), shared by the MCP App and /board/<id>.

Lives in the main server process, never in the sandbox. Ids are random
(192 bits), so a board URL only grants access to that one board.
"""

import secrets
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from typing import Any

DEFAULT_TTL_SECONDS = 3600
DEFAULT_MAX_BOARDS = 200


class BoardStore:
    def __init__(
        self,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
        max_boards: int = DEFAULT_MAX_BOARDS,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._ttl = ttl_seconds
        self._max = max_boards
        self._clock = clock
        self._boards: OrderedDict[str, tuple[float, dict[str, Any]]] = OrderedDict()
        self._lock = threading.Lock()

    def put(self, board: dict[str, Any]) -> str:
        board_id = secrets.token_urlsafe(24)
        with self._lock:
            self._drop_expired()
            self._boards[board_id] = (self._clock() + self._ttl, {**board, "id": board_id})
            while len(self._boards) > self._max:
                self._boards.popitem(last=False)  # least recently used
        return board_id

    def get(self, board_id: str) -> dict[str, Any] | None:
        with self._lock:
            entry = self._boards.get(board_id)
            if entry is None:
                return None
            expires, board = entry
            if expires <= self._clock():
                del self._boards[board_id]
                return None
            self._boards.move_to_end(board_id)
            return board

    def __len__(self) -> int:
        with self._lock:
            self._drop_expired()
            return len(self._boards)

    def _drop_expired(self) -> None:
        now = self._clock()
        for board_id in [k for k, (expires, _) in self._boards.items() if expires <= now]:
            del self._boards[board_id]
