# syntax=docker/dockerfile:1
FROM python:3.14-slim

COPY --from=ghcr.io/astral-sh/uv:0.12.17 /uv /bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_NO_CACHE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Dependencies first: this layer is reused while pyproject.toml / uv.lock don't change.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

# Then the project itself.
COPY README.md LICENSE ./
COPY src ./src
RUN uv sync --locked --no-dev --no-editable

RUN useradd --system --no-create-home app
USER app

ENV PATH="/app/.venv/bin:$PATH" \
    STEP_BY_STEP_MATH_TRANSPORT=http \
    PORT=8000
EXPOSE 8000

# The forkserver preloads __main__ (this entry point), sympy and the tasks
# module, same as locally. STEP_BY_STEP_MATH_PATH_TOKEN must be set at runtime.
CMD ["step-by-step-math"]
