"""
Fusion 360 MCP Bridge Add-in

This add-in runs inside Fusion 360 and monitors the mcp_comm/ directory
for command files written by the standalone MCP server. It executes
commands using the Fusion 360 API and writes response files back.

No external pip packages are required -- only stdlib and adsk.* modules.
"""

import adsk.core
import adsk.fusion
import os
import traceback
import threading
import time
import json
from pathlib import Path

app = adsk.core.Application.get()
ui = app.userInterface

server_thread = None
server_running = False
server_started_at_unix = None
handlers = []
message_command_handlers = []

# Resolve paths: MCPserve/commands/ -> MCPserve/ -> fusion-mcp-server/
ADDON_DIR = Path(__file__).resolve().parent.parent
WORKSPACE_DIR = ADDON_DIR.parent
COMM_DIR = WORKSPACE_DIR / "mcp_comm"
HEARTBEAT_INTERVAL_SECONDS = 1.0


def _ensure_comm_dir():
    COMM_DIR.mkdir(parents=True, exist_ok=True)


def _write_json_atomic(file_path, data):
    """Write JSON atomically to avoid partially-written response/status files."""
    tmp_path = Path(str(file_path) + ".tmp")
    tmp_path.write_text(json.dumps(data, indent=2))
    os.replace(str(tmp_path), str(file_path))


def _log(filename, message):
    """Append a timestamped log line to a file in mcp_comm/."""
    try:
        _ensure_comm_dir()
        with open(COMM_DIR / filename, "a") as f:
            f.write(f"[{time.ctime()}] {message}\n")
    except Exception:
        pass


def _write_status(status="running"):
    """Write the server_status.json file so the MCP server can detect us."""
    _ensure_comm_dir()
    now_unix = time.time()
    started_unix = server_started_at_unix if server_started_at_unix else now_unix
    status_data = {
        "status": status,
        "started_at_unix": started_unix,
        "started_at": time.ctime(started_unix),
        "heartbeat_unix": now_unix,
        "updated_at": time.ctime(now_unix),
        "fusion_version": app.version,
        "available_resources": [
            "fusion://active-document-info",
            "fusion://design-structure",
            "fusion://parameters",
        ],
        "available_tools": [
            "check_connection",
            "message_box",
            "create_new_sketch",
            "create_parameter",
            "create_box",
            "execute_script",
        ],
        "available_prompts": [
            "create_sketch_prompt",
            "parameter_setup_prompt",
        ],
    }
    _write_json_atomic(COMM_DIR / "server_status.json", status_data)


# ── Command Handlers ─────────────────────────────────────────────────

def handle_command(command, params):
    """Dispatch a command and return its result."""
    if command == "list_resources":
        return [
            "fusion://active-document-info",
            "fusion://design-structure",
            "fusion://parameters",
        ]
    elif command == "list_tools":
        return [
            {"name": "message_box", "description": "Display a message box in Fusion 360"},
            {"name": "create_new_sketch", "description": "Create a new sketch on the specified plane"},
            {"name": "create_parameter", "description": "Create a new parameter in the active design"},
            {"name": "create_box", "description": "Create a 3D box from dimensions"},
            {"name": "execute_script", "description": "Execute Python script using Fusion 360 API"},
        ]
    elif command == "list_prompts":
        return [
            {"name": "create_sketch_prompt", "description": "Expert guidance for creating sketches"},
            {"name": "parameter_setup_prompt", "description": "Expert guidance for setting up parameters"},
        ]
    elif command == "message_box":
        return _cmd_message_box(params.get("message", ""))
    elif command == "create_new_sketch":
        return _cmd_create_sketch(params.get("plane_name", "XY"))
    elif command == "create_parameter":
        return _cmd_create_parameter(
            params.get("name", f"Param_{int(time.time()) % 10000}"),
            params.get("expression", "10"),
            params.get("unit", "mm"),
            params.get("comment", ""),
        )
    elif command == "create_box":
        return _cmd_create_box(
            params.get("length", 10),
            params.get("width", 10),
            params.get("height", 10),
            params.get("name", "Box"),
        )
    elif command == "execute_script":
        return _cmd_execute_script(params.get("script", ""))
    elif command == "read_resource":
        return _cmd_read_resource(params.get("uri", ""))
    elif command == "get_prompt":
        return _cmd_get_prompt(params.get("name", ""), params.get("args", {}))
    else:
        return {"error": f"Unknown command: {command}"}


def _cmd_message_box(message):
    try:
        _show_message_box(message)
        return "Message displayed successfully"
    except Exception as e:
        return f"Error displaying message: {e}"


def _cmd_create_sketch(plane_name):
    try:
        doc = app.activeDocument
        if not doc:
            return "No active document"
        design = adsk.fusion.Design.cast(
            doc.products.itemByProductType("DesignProductType")
        )
        if not design:
            return "Active document is not a design document"
        root = design.rootComponent

        plane_map = {
            "XY": root.xYConstructionPlane,
            "YZ": root.yZConstructionPlane,
            "XZ": root.xZConstructionPlane,
        }
        sketch_plane = plane_map.get(plane_name.upper())

        if not sketch_plane:
            for i in range(root.constructionPlanes.count):
                p = root.constructionPlanes.item(i)
                if p.name == plane_name:
                    sketch_plane = p
                    break

        if not sketch_plane:
            return f"Could not find plane: {plane_name}"

        sketch = root.sketches.add(sketch_plane)
        sketch.name = f"Sketch_MCP_{int(time.time()) % 10000}"
        return f"Sketch created successfully: {sketch.name}"
    except Exception as e:
        return f"Error creating sketch: {e}"


def _cmd_create_parameter(name, expression, unit, comment):
    try:
        doc = app.activeDocument
        if not doc:
            return "No active document"
        design = adsk.fusion.Design.cast(
            doc.products.itemByProductType("DesignProductType")
        )
        if not design:
            return "Active document is not a design document"

        try:
            param = design.userParameters.add(
                name, adsk.core.ValueInput.createByString(expression), unit, comment
            )
            return f"Parameter created successfully: {param.name} = {param.expression}"
        except Exception:
            existing = design.userParameters.itemByName(name)
            if existing:
                existing.expression = expression
                existing.unit = unit
                if comment:
                    existing.comment = comment
                return f"Parameter updated: {existing.name} = {existing.expression}"
            raise
    except Exception as e:
        return f"Error creating parameter: {e}"


def _cmd_create_box(length, width, height, name):
    try:
        doc = app.activeDocument
        if not doc:
            return "No active document"
        design = adsk.fusion.Design.cast(
            doc.products.itemByProductType("DesignProductType")
        )
        if not design:
            return "Active document is not a design document"
        root = design.rootComponent

        sketches = root.sketches
        xy_plane = root.xYConstructionPlane
        sketch = sketches.add(xy_plane)

        lines = sketch.sketchCurves.sketchLines
        p0 = adsk.core.Point3D.create(0, 0, 0)
        p1 = adsk.core.Point3D.create(length / 10.0, 0, 0)
        p2 = adsk.core.Point3D.create(length / 10.0, width / 10.0, 0)
        p3 = adsk.core.Point3D.create(0, width / 10.0, 0)
        lines.addByTwoPoints(p0, p1)
        lines.addByTwoPoints(p1, p2)
        lines.addByTwoPoints(p2, p3)
        lines.addByTwoPoints(p3, p0)

        profile = sketch.profiles.item(0)
        extrudes = root.features.extrudeFeatures
        extent = adsk.fusion.DistanceExtentDefinition.create(
            adsk.core.ValueInput.createByReal(height / 10.0)
        )
        extrude_input = extrudes.createInput(
            profile, adsk.fusion.FeatureOperations.NewBodyFeatureOperation
        )
        extrude_input.setOneSideExtent(extent, adsk.fusion.ExtentDirections.PositiveExtentDirection)
        extrude = extrudes.add(extrude_input)

        body = extrude.bodies.item(0)
        if body and name:
            body.name = name

        return f"Box created: {name} ({length} x {width} x {height} mm)"
    except Exception as e:
        return f"Error creating box: {e}\n{traceback.format_exc()}"


def _cmd_execute_script(script):
    if not script.strip():
        return "No script provided"
    try:
        doc = app.activeDocument
        design = None
        if doc:
            design = adsk.fusion.Design.cast(
                doc.products.itemByProductType("DesignProductType")
            )
        local_vars = {
            "app": app,
            "ui": ui,
            "adsk": adsk,
            "doc": doc,
            "design": design,
            "result": "Script executed successfully",
        }
        exec(script, {"__builtins__": __builtins__}, local_vars)
        return str(local_vars.get("result", "Script executed successfully"))
    except Exception as e:
        return f"Script error: {e}\n{traceback.format_exc()}"


def _cmd_read_resource(uri):
    if uri == "fusion://active-document-info":
        try:
            doc = app.activeDocument
            if not doc:
                return {"error": "No active document"}
            file_name = "Unsaved"
            try:
                if hasattr(doc, "dataFile") and doc.dataFile:
                    file_name = doc.dataFile.name
            except Exception:
                pass
            return {
                "name": doc.name,
                "path": file_name,
                "type": str(doc.documentType),
            }
        except Exception as e:
            return {"error": str(e)}

    elif uri == "fusion://design-structure":
        try:
            doc = app.activeDocument
            if not doc:
                return {"error": "No active document"}
            design = adsk.fusion.Design.cast(
                doc.products.itemByProductType("DesignProductType")
            )
            if not design:
                return {"error": "No design in document"}
            root = design.rootComponent
            return {
                "design_name": design.name,
                "root_component": {
                    "name": root.name,
                    "bodies": [b.name for b in root.bodies],
                    "sketches": [s.name for s in root.sketches],
                    "occurrences": [
                        {"name": o.name, "component": o.component.name}
                        for o in root.occurrences
                    ],
                },
            }
        except Exception as e:
            return {"error": str(e)}

    elif uri == "fusion://parameters":
        try:
            doc = app.activeDocument
            if not doc:
                return {"error": "No active document"}
            design = adsk.fusion.Design.cast(
                doc.products.itemByProductType("DesignProductType")
            )
            if not design:
                return {"error": "No design in document"}
            params = []
            for p in design.allParameters:
                params.append({
                    "name": p.name,
                    "value": p.value,
                    "expression": p.expression,
                    "unit": p.unit,
                    "comment": p.comment,
                })
            return {"parameters": params}
        except Exception as e:
            return {"error": str(e)}

    else:
        return {"error": f"Unknown resource URI: {uri}"}


def _cmd_get_prompt(name, prompt_args):
    desc = prompt_args.get("description", "Default")
    if name == "create_sketch_prompt":
        return {
            "messages": [
                {"role": "system", "content": (
                    "You are an expert in Fusion 360 CAD modeling. "
                    "Help the user create sketches. Be specific about planes, "
                    "sketch entities, dimensions, and constraints."
                )},
                {"role": "user", "content": (
                    f"I want to create a sketch: {desc}\n\n"
                    "Provide step-by-step Fusion 360 instructions."
                )},
            ]
        }
    elif name == "parameter_setup_prompt":
        return {
            "messages": [
                {"role": "system", "content": (
                    "You are an expert in Fusion 360 parametric design. "
                    "Suggest appropriate parameters, values, units, and purposes."
                )},
                {"role": "user", "content": (
                    f"I want to set up parameters for: {desc}\n\n"
                    "What parameters should I create?"
                )},
            ]
        }
    else:
        return {"error": f"Unknown prompt: {name}"}


# ── Message Box via Fusion Command API ────────────────────────────────

def _show_message_box(message):
    """Display a message in Fusion 360 using the Command API (thread-safe)."""
    try:
        cmd_id = f"MCPMsg_{int(time.time() * 1000)}"
        cmd_defs = ui.commandDefinitions
        existing = cmd_defs.itemById(cmd_id)
        if existing:
            existing.deleteMe()

        cmd_def = cmd_defs.addButtonDefinition(cmd_id, "MCP Message", message, "")

        handler = _MsgCreatedHandler(message)
        cmd_def.commandCreated.add(handler)
        message_command_handlers.append(handler)

        cmd_def.execute()
    except Exception as e:
        _log("message_debug.txt", f"Error showing message box: {e}")


class _MsgExecuteHandler(adsk.core.CommandEventHandler):
    def __init__(self, message):
        super().__init__()
        self.message = message

    def notify(self, args):
        try:
            ui.messageBox(self.message, "Fusion MCP Message")
        except Exception as e:
            _log("message_debug.txt", f"Execute handler error: {e}")


class _MsgCreatedHandler(adsk.core.CommandCreatedEventHandler):
    def __init__(self, message):
        super().__init__()
        self.message = message

    def notify(self, args):
        try:
            cmd = args.command
            exe_handler = _MsgExecuteHandler(self.message)
            cmd.execute.add(exe_handler)
            message_command_handlers.append(exe_handler)
            cmd.isEnabled = True
            cmd.isVisible = False
        except Exception as e:
            _log("message_debug.txt", f"Created handler error: {e}")


# ── File Monitor Thread ───────────────────────────────────────────────

def _file_monitor():
    """Poll mcp_comm/ for command files and process them."""
    _log("monitor.txt", "File monitor started")
    comm_dir = str(COMM_DIR)
    last_heartbeat = 0.0

    while server_running:
        try:
            _ensure_comm_dir()
            now = time.time()
            if now - last_heartbeat >= HEARTBEAT_INTERVAL_SECONDS:
                _write_status("running")
                last_heartbeat = now

            # Process message_box.txt shortcut
            msg_file = os.path.join(comm_dir, "message_box.txt")
            if os.path.exists(msg_file):
                try:
                    with open(msg_file, "r") as f:
                        msg = f.read().strip()
                    if msg:
                        _show_message_box(msg)
                    processed = os.path.join(comm_dir, f"processed_message_{int(time.time())}.txt")
                    os.rename(msg_file, processed)
                except Exception as e:
                    _log("monitor.txt", f"Error processing message_box.txt: {e}")

            # Process command_*.json files
            for fname in sorted(os.listdir(comm_dir)):
                if not (fname.startswith("command_") and fname.endswith(".json")):
                    continue

                command_file = os.path.join(comm_dir, fname)
                cmd_id = fname[len("command_"):-len(".json")]
                processed_file = os.path.join(comm_dir, f"processed_command_{cmd_id}.json")
                response_file = os.path.join(comm_dir, f"response_{cmd_id}.json")

                if os.path.exists(processed_file) or os.path.exists(response_file):
                    continue

                try:
                    with open(command_file, "r") as f:
                        data = json.load(f)

                    command = data.get("command")
                    params = data.get("params", {})
                    _log("monitor.txt", f"Processing: {command} (id={cmd_id})")

                    result = handle_command(command, params)

                    _write_json_atomic(response_file, {"result": result})

                    os.rename(command_file, processed_file)

                except json.JSONDecodeError as e:
                    _write_json_atomic(response_file, {"error": f"Invalid JSON: {e}"})
                    bad_file = os.path.join(comm_dir, f"bad_command_{cmd_id}.json")
                    if os.path.exists(command_file):
                        os.rename(command_file, bad_file)
                except Exception as e:
                    _log("monitor.txt", f"Error processing {fname}: {e}\n{traceback.format_exc()}")
                    try:
                        _write_json_atomic(response_file, {"error": str(e)})
                    except Exception:
                        pass

        except Exception as e:
            _log("monitor.txt", f"Monitor loop error: {e}")

        time.sleep(0.5)

    _log("monitor.txt", "File monitor stopped")


# ── Server Lifecycle ──────────────────────────────────────────────────

def start_server():
    global server_thread, server_running, server_started_at_unix

    if server_running and server_thread and server_thread.is_alive():
        return True

    _ensure_comm_dir()
    _log("server.txt", "Starting file monitor bridge")
    server_started_at_unix = time.time()
    _write_status("running")

    server_running = True
    server_thread = threading.Thread(target=_file_monitor, daemon=True)
    server_thread.start()

    time.sleep(0.5)
    if not server_thread.is_alive():
        server_running = False
        return False

    _log("server.txt", "File monitor bridge started")
    return True


def stop_server():
    global server_running, server_started_at_unix
    if not server_running:
        return
    server_running = False
    _write_status("stopped")
    server_started_at_unix = None
    if server_thread and server_thread.is_alive():
        server_thread.join(timeout=2.0)
    _log("server.txt", "Server stopped")


# ── Fusion 360 Add-in UI ─────────────────────────────────────────────

class _CmdCreatedHandler(adsk.core.CommandCreatedEventHandler):
    def __init__(self):
        super().__init__()

    def notify(self, args):
        try:
            cmd = args.command
            inputs = cmd.commandInputs
            status = "Running" if server_running else "Not Running"
            inputs.addTextBoxCommandInput(
                "infoInput", "",
                f"Click OK to start the MCP Bridge.\n\n"
                f"This enables communication between the standalone MCP server and Fusion 360.\n\n"
                f"Current status: {status}",
                4, True,
            )
            exe = _CmdExecuteHandler()
            cmd.execute.add(exe)
            handlers.append(exe)

            destroy = _CmdDestroyHandler()
            cmd.destroy.add(destroy)
            handlers.append(destroy)
        except Exception:
            if ui:
                ui.messageBox(f"Failed:\n{traceback.format_exc()}")


class _CmdExecuteHandler(adsk.core.CommandEventHandler):
    def __init__(self):
        super().__init__()

    def notify(self, args):
        try:
            success = start_server()
            if success:
                ui.messageBox(
                    "MCP Bridge started!\n\n"
                    "The Fusion 360 side is ready. Now run the standalone MCP server:\n\n"
                    "  python mcp_server.py\n\n"
                    "Then connect your AI assistant to http://127.0.0.1:3000/sse"
                )
            else:
                ui.messageBox("Failed to start MCP Bridge. Check the error log in mcp_comm/.")
        except Exception:
            if ui:
                ui.messageBox(f"Failed:\n{traceback.format_exc()}")


class _CmdDestroyHandler(adsk.core.CommandEventHandler):
    def __init__(self):
        super().__init__()

    def notify(self, args):
        pass


def create_ui():
    try:
        cmd_defs = ui.commandDefinitions
        cmd_def = cmd_defs.itemById("MCPServerCommand")
        if not cmd_def:
            cmd_def = cmd_defs.addButtonDefinition(
                "MCPServerCommand", "MCP Bridge", "Start the MCP Bridge for Fusion 360"
            )
        handler = _CmdCreatedHandler()
        cmd_def.commandCreated.add(handler)
        handlers.append(handler)

        panel = ui.allToolbarPanels.itemById("SolidScriptsAddinsPanel")
        if not panel.controls.itemById("MCPServerCommand"):
            panel.controls.addCommand(cmd_def)
    except Exception:
        if ui:
            ui.messageBox(f"Failed to create UI:\n{traceback.format_exc()}")


def start():
    """Called when the add-in starts."""
    try:
        create_ui()
    except Exception:
        if ui:
            ui.messageBox(f"Failed to initialize:\n{traceback.format_exc()}")


def stop():
    """Called when the add-in stops."""
    try:
        stop_server()
        cmd_defs = ui.commandDefinitions
        cmd_def = cmd_defs.itemById("MCPServerCommand")
        if cmd_def:
            cmd_def.deleteMe()
        panel = ui.allToolbarPanels.itemById("SolidScriptsAddinsPanel")
        ctrl = panel.controls.itemById("MCPServerCommand")
        if ctrl:
            ctrl.deleteMe()
    except Exception:
        if ui:
            ui.messageBox(f"Failed to clean up:\n{traceback.format_exc()}")


def run(context):
    try:
        create_ui()
    except Exception:
        if ui:
            ui.messageBox(f"Failed to run:\n{traceback.format_exc()}")
