# This script is executed when Maya starts up.
# opens a command port for external tools to communicate with Maya.
# author  = Magnus Yu <magnusyu.com>

import json
import sys
from pathlib import Path


def add_sys_path(sys_path):
    # Add path
    if sys_path not in sys.path:
        sys.path.append(sys_path)


root_path = Path(__file__).parent.parent
add_sys_path(str(root_path))


PENDING_COMMAND_PATH = Path(__file__).with_name("_pending_maya_command.json")
IMPORT_TYPES = {
    ".fbx": "FBX",
    ".obj": "OBJ",
    ".ma": "mayaAscii",
    ".mb": "mayaBinary",
}


def open_command_port(port: int = 7001) -> None:
    """Open Maya's commandPort so external tools can send Python commands to this session."""
    try:
        from maya import cmds

        port_name = f":{port}"
        if not cmds.commandPort(port_name, query=True):
            cmds.commandPort(name=port_name, sourceType="python", noreturn=False)
            print(f"[startup] Maya commandPort opened on port {port}")
        else:
            print(f"[startup] Maya commandPort already open on port {port}")
    except Exception as exc:
        print(f"[startup] Could not open commandPort: {exc}")

def _run_pending_asset(payload: dict) -> None:
    """Execute a pending asset load command from the given payload."""
    from maya import cmds

    asset_path = str(payload.get("asset_path") or "").strip()
    asset_type = str(payload.get("asset_type") or "").strip().lower()
    asset_prefix = str(payload.get("asset_prefix") or "").strip()
    if not asset_path:
        return

    ext = Path(asset_path).suffix.lower()

    if asset_type == "rig":
        namespace = asset_prefix or Path(asset_path).stem
        cmds.file(asset_path, reference=True, type="mayaAscii", namespace=namespace)
        return

    if asset_type == "geo":
        fmt = IMPORT_TYPES.get(ext)
        if not fmt:
            raise ValueError(f"Unsupported file format for model import: {ext}")
        cmds.file(asset_path, i=True, type=fmt, ignoreVersion=True, mergeNamespacesOnClash=True)
        return

    if ext in (".ma", ".mb"):
        cmds.file(asset_path, o=True, f=True)
        return

    fmt = IMPORT_TYPES.get(ext)
    if not fmt:
        raise ValueError(f"Unsupported file format: {ext}")
    cmds.file(asset_path, i=True, type=fmt, ignoreVersion=True, mergeNamespacesOnClash=True, f=True)

def _deferred_pending_command() -> None:
    """Wrapper to execute pending command via deferred queue."""
    if not PENDING_COMMAND_PATH.exists():
        return

    try:
        raw = PENDING_COMMAND_PATH.read_text(encoding="utf-8").strip()
        if not raw:
            return

        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("Pending command payload must be a JSON object.")

        _run_pending_asset(payload)
        print("[startup] Executed pending asset command via executeDeferred.")
    except Exception as exc:
        print(f"[startup] Failed to run pending command: {exc}")
    finally:
        try:
            PENDING_COMMAND_PATH.unlink(missing_ok=True)
        except Exception:
            pass

def run_pending_command() -> None:
    """Schedule pending command to run after Maya UI is ready."""
    if not PENDING_COMMAND_PATH.exists():
        return

    try:
        from maya import utils
        utils.executeDeferred(_deferred_pending_command)
        print("[startup] Scheduled pending asset command via executeDeferred.")
    except Exception as exc:
        print(f"[startup] Could not schedule deferred command: {exc}")


open_command_port()
run_pending_command()
