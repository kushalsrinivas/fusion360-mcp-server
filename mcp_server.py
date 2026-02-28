#!/usr/bin/env python3
"""
Standalone MCP Server for Fusion 360

Runs as a separate process (outside Fusion 360) and bridges MCP protocol
requests to Fusion 360 via file-based communication in the mcp_comm/ directory.

The Fusion 360 add-in monitors mcp_comm/ for command files, executes them
using the Fusion 360 API, and writes response files. This server translates
MCP tool/resource/prompt calls into those file-based commands and waits
for responses.

Usage:
    python mcp_server.py              # Run with SSE transport (default)
    python mcp_server.py --stdio      # Run with stdio transport (for CLI integration)
    python mcp_server.py --port 3000  # Custom port for SSE
"""

import json
import time
import argparse
import asyncio
from pathlib import Path
from typing import Any
from uuid import uuid4

from mcp.server.fastmcp import FastMCP

WORKSPACE_DIR = Path(__file__).resolve().parent
COMM_DIR = WORKSPACE_DIR / "mcp_comm"
COMM_DIR.mkdir(parents=True, exist_ok=True)

COMMAND_TIMEOUT = 15.0
POLL_INTERVAL = 0.1
STATUS_STALE_SECONDS = 5.0

_parser = argparse.ArgumentParser(description="Fusion 360 MCP Server")
_parser.add_argument("--stdio", action="store_true", help="Use stdio transport instead of SSE")
_parser.add_argument("--host", default="127.0.0.1", help="Host for SSE server (default: 127.0.0.1)")
_parser.add_argument("--port", type=int, default=3000, help="Port for SSE server (default: 3000)")
_args = _parser.parse_args()


async def send_command(command: str, params: dict | None = None, timeout: float = COMMAND_TIMEOUT) -> Any:
    """Send a command to Fusion 360 via file-based communication and wait for a response."""
    if params is None:
        params = {}

    command_id = f"{time.time_ns()}_{uuid4().hex[:8]}"
    command_file = COMM_DIR / f"command_{command_id}.json"
    response_file = COMM_DIR / f"response_{command_id}.json"

    _atomic_write_json(command_file, {
        "command": command,
        "params": params,
        "created_at_unix": time.time(),
    })

    start = time.monotonic()
    while time.monotonic() - start < timeout:
        if response_file.exists():
            try:
                response = json.loads(response_file.read_text())
                if "error" in response:
                    _safe_unlink(response_file)
                    _safe_unlink(command_file)
                    raise RuntimeError(response["error"])
                result = response.get("result")
                _safe_unlink(response_file)
                _safe_unlink(command_file)
                return result
            except json.JSONDecodeError:
                await asyncio.sleep(POLL_INTERVAL)
                continue
        await asyncio.sleep(POLL_INTERVAL)

    # Remove timed-out command file so old actions don't run on restart.
    _safe_unlink(command_file)
    _safe_unlink(response_file)
    raise TimeoutError(
        f"Fusion 360 did not respond to '{command}' within {timeout}s. "
        "Make sure the Fusion 360 add-in is running."
    )


def check_fusion_addin_running() -> bool:
    """Check if the Fusion 360 add-in appears to be running."""
    status_file = COMM_DIR / "server_status.json"
    if status_file.exists():
        try:
            status = json.loads(status_file.read_text())
            if status.get("status") != "running":
                return False
            heartbeat = status.get("heartbeat_unix")
            if heartbeat is not None:
                return (time.time() - float(heartbeat)) <= STATUS_STALE_SECONDS
            # Fallback for older add-in versions without heartbeat.
            return (time.time() - status_file.stat().st_mtime) <= STATUS_STALE_SECONDS
        except Exception:
            pass
    return (COMM_DIR / "client_ready.txt").exists()


def _atomic_write_json(path: Path, payload: dict) -> None:
    """Write JSON atomically to avoid partially-written command files."""
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, indent=2))
    tmp_path.replace(path)


def _safe_unlink(path: Path) -> None:
    """Best-effort unlink that ignores missing files."""
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    except Exception:
        pass


# --- MCP Server ---

fusion_mcp = FastMCP(
    "Fusion 360 MCP Server",
    instructions=(
        "This server connects to Autodesk Fusion 360 via a bridge add-in. "
        "Make sure Fusion 360 is running with the MCPserve add-in active."
    ),
    host=_args.host,
    port=_args.port,
)


# --- Resources ---

@fusion_mcp.resource("fusion://active-document-info")
async def get_active_document_info() -> dict:
    """Get information about the active document in Fusion 360."""
    return await send_command("read_resource", {"uri": "fusion://active-document-info"})


@fusion_mcp.resource("fusion://design-structure")
async def get_design_structure() -> dict:
    """Get the structure of the active design (components, bodies, sketches)."""
    return await send_command("read_resource", {"uri": "fusion://design-structure"})


@fusion_mcp.resource("fusion://parameters")
async def get_parameters() -> dict:
    """Get all parameters defined in the active design."""
    return await send_command("read_resource", {"uri": "fusion://parameters"})


# --- Tools ---

@fusion_mcp.tool()
async def check_connection() -> str:
    """Check if the Fusion 360 add-in is running and responsive."""
    if check_fusion_addin_running():
        try:
            result = await send_command("list_tools", timeout=5.0)
            tool_count = len(result) if isinstance(result, list) else 0
            return f"Fusion 360 add-in is running. {tool_count} tools available."
        except TimeoutError:
            return "Fusion 360 add-in status file exists but it is not responding to commands."
        except Exception as e:
            return f"Fusion 360 add-in status file exists but got error: {e}"
    return (
        "Fusion 360 add-in does not appear to be running. "
        "Please start Fusion 360 and run the MCPserve add-in."
    )


@fusion_mcp.tool()
async def message_box(message: str) -> str:
    """Display a message box in Fusion 360.

    Args:
        message: The message text to display.
    """
    return await send_command("message_box", {"message": message})


@fusion_mcp.tool()
async def create_new_sketch(plane_name: str) -> str:
    """Create a new sketch on the specified plane in Fusion 360.

    Args:
        plane_name: The plane to create the sketch on. Standard planes: "XY", "YZ", "XZ".
                    Can also be the name of a custom construction plane.
    """
    return await send_command("create_new_sketch", {"plane_name": plane_name})


@fusion_mcp.tool()
async def create_parameter(name: str, expression: str, unit: str, comment: str = "") -> str:
    """Create or update a user parameter in the active Fusion 360 design.

    Args:
        name: Parameter name (e.g. "Width", "Height").
        expression: Value expression (e.g. "10", "Width * 2").
        unit: Unit of measurement (e.g. "mm", "in", "deg").
        comment: Optional description of the parameter.
    """
    return await send_command("create_parameter", {
        "name": name,
        "expression": expression,
        "unit": unit,
        "comment": comment,
    })


@fusion_mcp.tool()
async def create_box(length: float, width: float, height: float, name: str = "Box") -> str:
    """Create a box (rectangular prism) in the active Fusion 360 design.

    Args:
        length: Length of the box in mm (X direction).
        width: Width of the box in mm (Y direction).
        height: Height of the box in mm (Z direction).
        name: Optional name for the body (default: "Box").
    """
    return await send_command("create_box", {
        "length": length,
        "width": width,
        "height": height,
        "name": name,
    })


@fusion_mcp.tool()
async def execute_script(script: str) -> str:
    """Execute a Python script using the Fusion 360 API.

    The script runs inside Fusion 360 with access to adsk.core, adsk.fusion,
    and the current app/design objects. Use this for operations not covered
    by other tools.

    The script should set a variable called `result` (string) to return output.

    Args:
        script: Python code to execute in Fusion 360. Has access to: app, ui,
                adsk.core, adsk.fusion, and the active design.
    """
    return await send_command("execute_script", {"script": script})


# --- Prompts ---

@fusion_mcp.prompt()
async def create_sketch_prompt(description: str) -> list[dict]:
    """Get expert guidance for creating a sketch in Fusion 360.

    Args:
        description: What you want to sketch (e.g. "a rectangular bracket with mounting holes").
    """
    return [
        {
            "role": "system",
            "content": (
                "You are an expert in Fusion 360 CAD modeling. "
                "Help the user create sketches based on their descriptions. "
                "Be specific about planes, sketch entities, dimensions, and constraints."
            ),
        },
        {
            "role": "user",
            "content": (
                f"I want to create a sketch with these requirements: {description}\n\n"
                "Please provide step-by-step instructions for creating this sketch in Fusion 360."
            ),
        },
    ]


@fusion_mcp.prompt()
async def parameter_setup_prompt(description: str) -> list[dict]:
    """Get expert guidance for setting up parametric dimensions in Fusion 360.

    Args:
        description: What you're designing (e.g. "an enclosure box 100x60x40mm").
    """
    return [
        {
            "role": "system",
            "content": (
                "You are an expert in Fusion 360 parametric design. "
                "Help the user set up parameters for their design. "
                "Suggest appropriate parameter names, values, units, and descriptions."
            ),
        },
        {
            "role": "user",
            "content": (
                f"I want to set up parameters for: {description}\n\n"
                "What parameters should I create, and what values, units, and comments should they have?"
            ),
        },
    ]


def main():
    if not check_fusion_addin_running():
        print(
            "WARNING: Fusion 360 add-in does not appear to be running.\n"
            "The MCP server will start, but tool calls will fail until\n"
            "you start Fusion 360 and run the MCPserve add-in.\n"
        )

    if _args.stdio:
        print("Starting Fusion 360 MCP server (stdio transport)...")
        fusion_mcp.run(transport="stdio")
    else:
        print(f"Starting Fusion 360 MCP server at http://{_args.host}:{_args.port}/sse ...")
        fusion_mcp.run(transport="sse")


if __name__ == "__main__":
    main()
