import os
import time

import pytest

from step_by_step_math import tasks
from step_by_step_math.parsing import InputError
from step_by_step_math.sandbox import (
    ComputationCrashed,
    ComputationOutOfMemory,
    ComputationTimeout,
    default_memory_mb,
    default_timeout,
    run_isolated,
)

# Takes well over 20 s in SymPy 1.14.
SLOW_INTEGRAL = "(x**7 + 3)/(x**13 + x + 1)"


def test_returns_result():
    assert run_isolated(sum, [1, 2, 3]) == 6


def test_timeout_kills_hung_call():
    start = time.monotonic()
    with pytest.raises(ComputationTimeout, match="more than 0.5 s"):
        run_isolated(time.sleep, 30, timeout=0.5)
    assert time.monotonic() - start < 5


def test_timeout_on_real_sympy_integral():
    start = time.monotonic()
    with pytest.raises(ComputationTimeout):
        run_isolated(tasks.integrate_task, SLOW_INTEGRAL, "x", None, None, timeout=1)
    assert time.monotonic() - start < 5


def test_works_again_after_timeout():
    with pytest.raises(ComputationTimeout):
        run_isolated(time.sleep, 30, timeout=0.3)
    result = run_isolated(tasks.integrate_task, "x*exp(x)", "x", None, None)
    assert result["result"] == "x*exp(x) - exp(x) + C"


def test_memory_limit():
    with pytest.raises(ComputationOutOfMemory, match="out of memory"):
        run_isolated(bytearray, 2 * 2**30, memory_mb=512)


def test_child_exception_is_reraised():
    with pytest.raises(ValueError):
        run_isolated(int, "not a number")


def test_user_facing_error_crosses_process():
    with pytest.raises(InputError, match="Could not parse"):
        run_isolated(tasks.differentiate_task, "sin(x", "x")


def test_child_crash():
    with pytest.raises(ComputationCrashed):
        run_isolated(os._exit, 3)


def test_config_from_env(monkeypatch):
    monkeypatch.setenv("STEP_BY_STEP_MATH_TIMEOUT", "2.5")
    monkeypatch.setenv("STEP_BY_STEP_MATH_MEMORY_MB", "256")
    assert default_timeout() == 2.5
    assert default_memory_mb() == 256


def test_config_defaults(monkeypatch):
    monkeypatch.delenv("STEP_BY_STEP_MATH_TIMEOUT", raising=False)
    monkeypatch.delenv("STEP_BY_STEP_MATH_MEMORY_MB", raising=False)
    assert default_timeout() == 10
    assert default_memory_mb() == 512


@pytest.mark.parametrize("value", ["abc", "-1"])
def test_config_invalid(monkeypatch, value):
    monkeypatch.setenv("STEP_BY_STEP_MATH_TIMEOUT", value)
    with pytest.raises(ValueError, match="STEP_BY_STEP_MATH_TIMEOUT"):
        default_timeout()
