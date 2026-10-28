"""Run a computation in a separate process with a time and memory limit.

SymPy can hang or eat all the RAM on ugly inputs. A thread cannot be killed and
`signal.alarm` only works on the main thread (the SDK runs sync tools in a worker
thread), so each computation runs in a child process that we can kill.

Children are created with `forkserver` with SymPy preloaded: starting one takes
~6 ms, and it is safe to use from a multi-threaded server (plain `fork` is not).

Config (environment variables):
    STEP_BY_STEP_MATH_TIMEOUT         seconds per computation (default 10)
    STEP_BY_STEP_MATH_MEMORY_MB       address-space limit for the child in MB (default 512, 0 = no limit)
    STEP_BY_STEP_MATH_MAX_CONCURRENT  computations running at the same time (default 2)
"""

import multiprocessing as mp
import os
import resource
import threading
from collections.abc import Callable
from multiprocessing.connection import Connection
from typing import Any

from step_by_step_math.errors import UserFacingError

DEFAULT_TIMEOUT_SECONDS = 10.0
DEFAULT_MEMORY_MB = 512
DEFAULT_MAX_CONCURRENT = 2

# Modules loaded once in the fork server, so each child starts warm.
# "__main__" matters: without it every child re-imports the entry point
# (and with it the whole MCP SDK), which costs ~0.5 s per call.
_PRELOAD = ["__main__", "sympy", "step_by_step_math.tasks"]

_context: Any = None
_slots: threading.BoundedSemaphore | None = None
_slots_lock = threading.Lock()


class ComputationError(UserFacingError):
    """The computation could not finish inside its limits."""


class ComputationTimeout(ComputationError):
    pass


class ComputationOutOfMemory(ComputationError):
    pass


class ComputationCrashed(ComputationError):
    pass


class ComputationBusy(ComputationError):
    pass


def default_timeout() -> float:
    return _env_number("STEP_BY_STEP_MATH_TIMEOUT", DEFAULT_TIMEOUT_SECONDS)


def default_memory_mb() -> float:
    return _env_number("STEP_BY_STEP_MATH_MEMORY_MB", DEFAULT_MEMORY_MB)


def max_concurrent() -> int:
    value = int(_env_number("STEP_BY_STEP_MATH_MAX_CONCURRENT", DEFAULT_MAX_CONCURRENT))
    if value < 1:
        raise ValueError("STEP_BY_STEP_MATH_MAX_CONCURRENT must be >= 1")
    return value


def _get_slots() -> threading.BoundedSemaphore:
    # Caps how many children (each up to the memory limit) exist at once.
    global _slots
    with _slots_lock:
        if _slots is None:
            _slots = threading.BoundedSemaphore(max_concurrent())
        return _slots


def _env_number(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = float(raw)
    except ValueError:
        raise ValueError(f"{name} must be a number, got {raw!r}") from None
    if value < 0:
        raise ValueError(f"{name} must be >= 0, got {raw!r}")
    return value


def _get_context() -> Any:
    global _context
    if _context is None:
        ctx = mp.get_context("forkserver")
        ctx.set_forkserver_preload(_PRELOAD)
        _context = ctx
    return _context


def _child(conn: Connection, fn: Callable[..., Any], args: tuple, memory_bytes: int) -> None:
    try:
        if memory_bytes > 0:
            resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))
        result = fn(*args)
        conn.send(("ok", result))
    except MemoryError:
        conn.send(("oom", None))
    except BaseException as e:  # noqa: BLE001 - every error must reach the parent
        try:
            conn.send(("error", e))
        except Exception:  # the exception itself may not be picklable
            conn.send(("error", RuntimeError(repr(e))))
    finally:
        conn.close()


def warm_up() -> None:
    """Start the fork server now, so the first real call does not pay ~1 s for it."""
    run_isolated(int, timeout=30)


def run_isolated(
    fn: Callable[..., Any],
    *args: Any,
    timeout: float | None = None,
    memory_mb: float | None = None,
) -> Any:
    """Run `fn(*args)` in a child process and return its result.

    `fn`, `args` and the result must be picklable (`fn` must be importable at
    module level). Exceptions raised by `fn` are re-raised here as they are.

    Raises ComputationTimeout, ComputationOutOfMemory, ComputationCrashed or
    ComputationBusy (all computation slots stayed taken for `timeout` seconds).
    """
    timeout = default_timeout() if timeout is None else timeout
    memory_mb = default_memory_mb() if memory_mb is None else memory_mb

    slots = _get_slots()
    if not slots.acquire(timeout=timeout):
        raise ComputationBusy("The server is busy with other computations. Try again in a few seconds.")
    try:
        return _run_in_child(fn, args, timeout, memory_mb)
    finally:
        slots.release()


def _run_in_child(fn: Callable[..., Any], args: tuple, timeout: float, memory_mb: float) -> Any:
    memory_bytes = int(memory_mb * 2**20)
    ctx = _get_context()
    receiver, sender = ctx.Pipe(duplex=False)
    process = ctx.Process(target=_child, args=(sender, fn, args, memory_bytes), daemon=True)
    process.start()
    sender.close()  # the child owns the write end now; EOF if it dies
    try:
        # Read before join: a large result would otherwise block the child on send.
        if not receiver.poll(timeout):
            raise ComputationTimeout(
                f"The computation took more than {timeout:g} s and was stopped. "
                "Try a simpler expression or split the problem."
            )
        try:
            status, payload = receiver.recv()
        except EOFError:
            raise ComputationCrashed(
                "The computation process died unexpectedly (probably out of memory)."
            ) from None
    finally:
        if process.is_alive():
            process.kill()
        process.join()
        receiver.close()

    if status == "ok":
        return payload
    if status == "oom":
        raise ComputationOutOfMemory(
            f"The computation ran out of memory (limit {memory_mb:g} MB) and was stopped. "
            "Try a simpler expression."
        )
    raise payload
