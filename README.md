# step-by-step-math

MCP server that solves math step by step with a symbolic engine and renders each step on a visual whiteboard.

> **Status:** work in progress. Right now it exposes three tools backed by SymPy: `differentiate`, `integrate` and `verify_antiderivative`. Step-by-step solutions and the whiteboard are coming next.

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
| `integrate` | `expression`, `variable`, optional `lower` / `upper` (`0`, `pi/2`, `oo`, ...) | antiderivative `+ C` or value, LaTeX, method used, verification; improper integrals and divergence are detected |
| `verify_antiderivative` | `integrand`, `antiderivative`, `variable` | `verified`, `inconclusive` or `incorrect` (with the difference) |

Expressions use SymPy syntax (`x**2`, `exp(x)`, `sin(x)`, `log(x)`); `sen`, `tg` and `ln` are accepted too.

## Configuration

Each computation runs in a separate process that is killed if it exceeds its limits.

| Variable | Default | Meaning |
|---|---|---|
| `STEP_BY_STEP_MATH_TIMEOUT` | `10` | seconds per computation |
| `STEP_BY_STEP_MATH_MEMORY_MB` | `512` | memory limit per computation (`0` = no limit) |

## License

MIT
