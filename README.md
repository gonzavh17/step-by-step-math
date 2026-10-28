# step-by-step-math

MCP server that solves math step by step with a symbolic engine and renders each step on a visual whiteboard.

> **Status:** work in progress. Right now it exposes a single tool, `differentiate`, backed by SymPy. Step-by-step integrals and the whiteboard are coming next.

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
| `differentiate` | `expression` (SymPy syntax: `x**2`, `exp(x)`, `sin(x)`; also `sen`, `tg`, `ln`), `variable` (default `x`) | result as text and LaTeX |

## License

MIT
