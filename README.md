# Fusion 360 MCP Server

A [Model Context Protocol (MCP)](https://github.com/modelcontextprotocol/python-sdk) server that lets AI assistants (Claude, Cursor, etc.) interact directly with Autodesk Fusion 360.

## Architecture

The system uses a **two-process design** to avoid macOS code-signing restrictions on Fusion 360's embedded Python:

```
AI Assistant  ←→  MCP Server (mcp_server.py)  ←→  Fusion 360 Add-in (MCPserve/)
                  runs in your venv               runs inside Fusion 360
                  handles MCP protocol             executes Fusion 360 API calls
                  communicates via mcp_comm/        monitors mcp_comm/ for commands
```

- **`mcp_server.py`** — Standalone MCP server. Runs in a normal Python environment with all MCP dependencies. Translates MCP tool/resource calls into file-based commands.
- **`MCPserve/`** — Fusion 360 add-in. Uses only stdlib + `adsk.*` modules (no pip packages needed). Monitors `mcp_comm/` for commands, executes them via the Fusion 360 API, and writes responses.

## What AI Assistants Can Do

### Resources

- `fusion://active-document-info` — Name, path, and type of the active document
- `fusion://design-structure` — Components, bodies, sketches, and occurrences
- `fusion://parameters` — All user and model parameters

### Tools

- `check_connection` — Verify the Fusion 360 add-in is running
- `message_box` — Display a message in Fusion 360
- `create_new_sketch` — Create a sketch on XY, YZ, XZ, or a custom plane
- `create_parameter` — Create or update a user parameter
- `create_box` — Create a box (rectangular prism) with given dimensions
- `execute_script` — Run arbitrary Python code inside Fusion 360

### Prompts

- `create_sketch_prompt` — Expert guidance for creating sketches
- `parameter_setup_prompt` — Expert guidance for parametric design

## Requirements

- Autodesk Fusion 360 (macOS or Windows)
- Python 3.10+ (for the standalone MCP server)

## Quick Start

### 1. Set up the MCP server environment

```bash
python install_mcp_for_fusion.py
```

Or manually:

```bash
python -m venv venv
source venv/bin/activate   # macOS/Linux
# venv\Scripts\activate    # Windows
pip install -r requirements.txt
```

### 2. Install the Fusion 360 add-in

1. Open Fusion 360
2. Go to **Tools** → **Add-Ins** → **Scripts and Add-Ins**
3. Click the green **+** in the **My Add-Ins** tab
4. Browse to the `MCPserve` folder and click **Open**
5. Select it and click **Run**

### 3. Start both processes

**In Fusion 360:** Click the **MCP Bridge** button — this starts the file monitor.

**In a terminal:**

```bash
source venv/bin/activate
python mcp_server.py
```

The MCP server starts at `http://127.0.0.1:3000/sse`.

### 4. Connect your AI assistant

Point your MCP client to `http://127.0.0.1:3000/sse`. For stdio transport:

```bash
python mcp_server.py --stdio
```

## Configuration

```bash
python mcp_server.py --help
```

| Flag      | Default   | Description                        |
| --------- | --------- | ---------------------------------- |
| `--stdio` | off       | Use stdio transport instead of SSE |
| `--host`  | 127.0.0.1 | SSE server host                    |
| `--port`  | 3000      | SSE server port                    |

## Project Structure

```
fusion-mcp-server/
├── mcp_server.py              # Standalone MCP server (run this)
├── install_mcp_for_fusion.py  # Setup script (creates venv + installs deps)
├── requirements.txt           # Python dependencies (mcp, uvicorn)
├── MCPserve/                  # Fusion 360 add-in
│   ├── MCPserve.py            # Add-in entry point
│   ├── MCPserve.manifest      # Fusion 360 add-in manifest
│   ├── commands/
│   │   ├── __init__.py
│   │   └── MCPServerCommand.py  # File monitor + Fusion API bridge
│   ├── lib/
│   │   ├── __init__.py
│   │   └── fusionAddInUtils.py  # Add-in utility helpers
│   └── resources/             # Add-in icons
├── mcp_comm/                  # Runtime communication directory (gitignored)
└── venv/                      # Python virtual environment (gitignored)
```

## License

MIT — see [LICENSE](LICENSE).
# fusion360-mcp-server
