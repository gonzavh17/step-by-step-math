# step-by-step-math

MCP server that solves math step by step with a symbolic engine and renders each step on a visual whiteboard.

> **Status:** work in progress. Integrals are solved step by step (automatic, by parts, by substitution or by partial fractions, with the method the user picks) and shown on a whiteboard. Every step is checked by SymPy.

The model never does the math: it calls the tools, gets back a short summary (result, method, number of steps) and the user sees the steps on the whiteboard:

- **Inline** in hosts that support [MCP Apps](https://modelcontextprotocol.io/extensions/apps) (claude.ai, ChatGPT).
- **As a link** (`board_url`) over HTTP, or **as a local HTML file** (`board_path`) over stdio, for other hosts.

## Requirements

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)

## Run locally

```bash
uv sync
uv run pytest                 # run the tests
uv run step-by-step-math      # start the MCP server over stdio
```

### Try it with MCP Inspector

```bash
npx @modelcontextprotocol/inspector uv --directory /path/to/step-by-step-math run step-by-step-math
```

### Use it from Claude Code

```bash
claude mcp add step-by-step-math -- uv --directory /path/to/step-by-step-math run step-by-step-math
```

## Tools

| Tool | Input | Output |
|---|---|---|
| `differentiate` | `expression`, `variable` (default `x`) | result as text and LaTeX |
| `integrate` | `expression`, `variable`, optional `lower` / `upper` (`0`, `pi/2`, `oo`, ...), `method` (`auto`, `parts`, `substitution`, `partial_fractions`), `u`, `dv` | antiderivative `+ C` or value, LaTeX, method, verification, number of steps and the whiteboard (`board_id` plus `board_url` or `board_path`); improper integrals and divergence are detected |
| `verify_antiderivative` | `integrand`, `antiderivative`, `variable` | `verified`, `inconclusive` or `incorrect` (with the difference) |
| `get_board` | `board_id` | internal: only the whiteboard app can call it (hidden from the model) |

Expressions use SymPy syntax (`x**2`, `exp(x)`, `sin(x)`, `log(x)`); `sen`, `tg` and `ln` are accepted too.

## Configuration

Each computation runs in a separate process that is killed if it exceeds its limits.

| Variable | Default | Meaning |
|---|---|---|
| `STEP_BY_STEP_MATH_TIMEOUT` | `10` | seconds per computation |
| `STEP_BY_STEP_MATH_MEMORY_MB` | `512` | memory limit per computation (`0` = no limit) |
| `STEP_BY_STEP_MATH_MAX_CONCURRENT` | `2` | computations running at the same time |
| `STEP_BY_STEP_MATH_TRANSPORT` | `stdio` | `stdio` or `http` |
| `STEP_BY_STEP_MATH_PATH_TOKEN` | — | required with `http`: secret path segment, at least 32 URL-safe characters |
| `STEP_BY_STEP_MATH_PUBLIC_URL` | `https://$RAILWAY_PUBLIC_DOMAIN` | public base URL used in whiteboard links |
| `PORT` | `8000` | HTTP port (set by Railway) |

## Deploy

The repo includes a `Dockerfile` (uv, `python:3.14-slim`) that starts the server over streamable HTTP:

- MCP endpoint: `https://<your-domain>/mcp/<STEP_BY_STEP_MATH_PATH_TOKEN>`
- Health check: `GET /health`
- Whiteboards: `GET /board/<id>` (random 192-bit id, expires after 1 hour, kept in memory)

**The full MCP URL is the secret.** Custom connectors in claude.ai and ChatGPT cannot reliably send a fixed auth header, so the server is protected by an unguessable path segment instead. Anyone with the URL can use the server: don't share it, and rotate the token (redeploy with a new value) if it leaks. Any other path under `/mcp` returns 404, and request paths are not logged. Whiteboard links do not contain the token, so sharing one does not give access to the server.

Run the image locally:

```bash
podman build -t step-by-step-math .   # or docker
TOKEN=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
podman run --rm -p 8000:8000 -e STEP_BY_STEP_MATH_PATH_TOKEN="$TOKEN" step-by-step-math
npx @modelcontextprotocol/inspector --cli "http://127.0.0.1:8000/mcp/$TOKEN" --transport http --method tools/list
```

On Railway: deploy the repo (the Dockerfile is detected automatically), set `STEP_BY_STEP_MATH_PATH_TOKEN`, generate a public domain and set the health check path to `/health`. Railway sets `PORT`.

## License

MIT
