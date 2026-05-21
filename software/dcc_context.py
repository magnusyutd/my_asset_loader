# content = Detect which DCC application (or standalone Python) is hosting the tool.
# author  = Magnus Yu <magnusyu.com>

import os
import json
import socket
import subprocess
import sys
from pathlib import Path
from typing import Optional

import load

# from scripts.external import yaml


# def _loadCONFIG() -> dict:
#     config_path = Path(__file__).parent / "config" / "project.yaml"
#     with open(config_path, "r") as file_obj:
#         return yaml.safe_load(file_obj) or {}


def _expand_path(value: Optional[str]) -> Optional[Path]:
    if not value:
        return None
    return Path(os.path.expandvars(value))


CONFIG = load.load_config()
MAYA_BAT = _expand_path(CONFIG.get("maya_batch_path"))
MAYA_NATIVE_EXTS = set(CONFIG.get("maya_native_extensions") or [".ma", ".mb"])
MAYA_PORT = int(CONFIG.get("maya_command_port", 7001))
MAYA_HOST = CONFIG.get("maya_command_host", "localhost")
PENDING_MAYA_COMMAND_FILE = Path(__file__).parent / "scripts" / "_pending_maya_command.json"


def module_exists(module_name: str) -> bool:
    try:
        __import__(module_name)
        return True
    except Exception:
        return False


def get_host() -> str:
    """Return a lowercase string identifying the current host process.

    Returns
    -------
    "maya"       – running inside Autodesk Maya
    "houdini"    – running inside SideFX Houdini
    "nuke"       – running inside Foundry Nuke
    "blender"    – running inside Blender
    "unreal"     – running inside Unreal Engine (via unreal Python plugin)
    "3dsmax"     – running inside Autodesk 3ds Max
    "standalone" – plain Python / no DCC detected
    """
    exe = sys.executable.lower()

    # Maya – most reliable signal is its OpenMayaUI API
    if module_exists("maya.cmds"):
        return "maya"

    # Houdini
    if module_exists("hou"):
        return "houdini"

    # Nuke
    if module_exists("nuke"):
        return "nuke"

    # Blender injects `bpy` into its embedded Python
    if module_exists("bpy"):
        return "blender"

    # Unreal Engine Python plugin
    if module_exists("unreal"):
        return "unreal"

    # 3ds Max (MaxPlus / pymxs)
    if module_exists("pymxs") or module_exists("MaxPlus"):
        return "3dsmax"

    # Fallback – check the executable name as a last resort
    for dcc, patterns in {
        "maya":     ["maya"],
        "houdini":  ["houdini", "hython"],
        "nuke":     ["nuke"],
        "blender":  ["blender"],
        "unreal":   ["unrealEditor", "ue4editor"],
        "3dsmax":   ["3dsmax"],
    }.items():
        if any(p.lower() in exe for p in patterns):
            return dcc

    return "standalone"


def is_maya() -> bool:
    return get_host() == "maya"


def is_standalone() -> bool:
    return get_host() == "standalone"


def is_dcc() -> bool:
    """True when running inside any DCC (not plain standalone Python)."""
    return get_host() != "standalone"


def is_maya_running() -> bool:
    """Return True if a Maya instance has its commandPort open on MAYA_PORT."""
    try:
        with socket.create_connection((MAYA_HOST, MAYA_PORT), timeout=0.5):
            return True
    except OSError:
        return False


def send_toMAYA_PORT(python_code: str) -> str:
    """Send a block of Python code to Maya's commandPort and return the response.

    Maya must have opened the port via:
        cmds.commandPort(name=':7001', sourceType='python')

    Args:
        python_code: Valid Python source to execute inside Maya.

    Returns:
        Maya's response string (may be empty).

    Raises:
        ConnectionRefusedError: If Maya's commandPort is not reachable.
    """
    with socket.create_connection((MAYA_HOST, MAYA_PORT), timeout=5) as sock:
        sock.sendall(python_code.encode("utf-8"))
        response = b""
        sock.settimeout(2)
        try:
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                response += chunk
        except socket.timeout:
            pass
    return response.decode("utf-8", errors="replace")


def _build_load_command(asset_type: str, asset_path: str, asset_prefix: str) -> str:
    """Build a Python snippet that loads an asset inside a running Maya session."""
    p = asset_path.replace("\\", "/")  # Maya prefers forward slashes
    ext = Path(asset_path).suffix.lower()

    IMPORT_TYPES = {
        ".fbx": "FBX",
        ".obj": "OBJ",
        ".ma": "mayaAscii",
        ".mb": "mayaBinary",
    }

    if asset_type == "rig":
        return (
            f"import maya.cmds as cmds; "
            f"cmds.file(r'{p}', reference=True, type='mayaAscii', "
            f"namespace='{asset_prefix}')"
        )
    if asset_type == "geo":
        fmt = IMPORT_TYPES.get(ext, "")
        return (
            f"import maya.cmds as cmds; "
            f"cmds.file(r'{p}', i=True, type='{fmt}', "
            f"ignoreVersion=True, mergeNamespacesOnClash=True)"
        )
    # Generic open
    if ext in (".ma", ".mb"):
        return f"import maya.cmds as cmds; cmds.file(r'{p}', o=True, f=True)"
    fmt = IMPORT_TYPES.get(ext, "")
    return (
        f"import maya.cmds as cmds; "
        f"cmds.file(r'{p}', i=True, type='{fmt}', "
        f"ignoreVersion=True, mergeNamespacesOnClash=True, f=True)"
    )


def _write_pending_maya_command(asset_path: str, asset_type: str, asset_prefix: str) -> None:
    """Persist pending asset load info for Maya startup to execute once."""
    payload = {
        "asset_path": asset_path,
        "asset_type": asset_type,
        "asset_prefix": asset_prefix,
    }
    PENDING_MAYA_COMMAND_FILE.write_text(json.dumps(payload), encoding="utf-8")


def launch_in_maya(asset_path: str = "", asset_type: str = "", asset_prefix: str = "") -> str:
    """Send an asset to Maya, reusing an existing instance when possible.

    Strategy
    --------
    1. If Maya has its commandPort open, send the load command over the socket
       and return ``"port"``.
    2. Otherwise start a new Maya instance via maya.bat and return ``"launched"``.

    Args:
        asset_path:   Absolute path to the asset file.
        asset_type:   "geo", "rig", or "" (generic open).
        asset_prefix: Namespace prefix used for rig references.

    Returns:
        ``"port"`` if sent to a running Maya, ``"launched"`` if a new instance was started.
    """
    if is_maya_running():
        try:
            cmd = _build_load_command(asset_type, asset_path, asset_prefix)
            send_toMAYA_PORT(cmd)
            return "port"
        except OSError as exc:
            # Connection failed (e.g., WinError 10054: forcibly closed by remote host).
            # Treat as "Maya no longer running" and launch a new instance.
            print(f"[launch_in_maya] Send to port failed: {exc}. Launching new Maya.")

    # No running Maya — start one.
    if not MAYA_BAT.exists():
        raise FileNotFoundError(
            f"Maya launcher not found: {MAYA_BAT}\n"
            "Check exe/windows/maya.bat exists and MAYA_PATH is configured."
        )

    if asset_path:
        _write_pending_maya_command(asset_path, asset_type, asset_prefix)

    cmd = [str(MAYA_BAT)]
    subprocess.Popen(cmd, shell=True)
    return "launched"
