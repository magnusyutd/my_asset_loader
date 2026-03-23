# content = Loader functions for different asset types.
# author  = Magnus Yu <magnusyu.com>

from pathlib import Path

try:
    from maya import cmds
except ImportError:
    cmds = None

IMPORT_TYPES = {
    ".fbx": "FBX",
    ".obj": "OBJ",
    ".ma": "mayaAscii",
    ".mb": "mayaBinary",
}


def _require_maya() -> None:
    if cmds is None:
        raise RuntimeError("Maya commands are unavailable. This function only works inside Maya.")


def get_similar_prefixes(search_prefix:str) -> list:
    if cmds is None:
        return []

    namespaces = cmds.namespaceInfo(listOnlyNamespaces=True, recurse=True) or []
    similar_prefixes = [namespace for namespace in namespaces if namespace.startswith(search_prefix)]
    return similar_prefixes

def load_config() -> dict:
    from scripts.external import yaml

    config_path = Path(__file__).parent / "config" / "project.yaml"
    with open(config_path, "r") as file_obj:
        return yaml.safe_load(file_obj) or {}

def load_model(asset_path:str) -> None:
    """ Load model asset into the Maya scene.

    ARGS:
        asset_path(str): The file path to the model asset
    """
    _require_maya()

    path_suffix = Path(asset_path).suffix.lower()
    path_type = IMPORT_TYPES.get(path_suffix)

    if not path_type:
        raise ValueError(f"Unsupported file format for model import: {path_suffix}")

    cmds.file(asset_path, i=True, type=path_type, ignoreVersion=True, mergeNamespacesOnClash=True)

def load_rig(asset_path:str, prefix:str) -> None:
    """ Load rig asset into the Maya scene with a specified namespace prefix.

    ARGS:
        asset_path(str): The file path to the rig asset
        prefix(str): The namespace prefix to use when loading the asset
    """
    _require_maya()

    cmds.file(asset_path, reference=True, type='mayaAscii', namespace=str(prefix))

def open_file(file_path:str) -> None:
    _require_maya()

    path_suffix = Path(file_path).suffix.lower()

    # Maya native files
    if path_suffix in [".ma", ".mb"]:
        cmds.file(file_path, o=True, f=True)

    # Other supported formats
    elif path_suffix in [".fbx", ".obj"]:
        cmds.file(
            file_path,
            i=True,
            type=IMPORT_TYPES[path_suffix],
            ignoreVersion=True,
            mergeNamespacesOnClash=True,
            f=True,
        )

    else:
        raise ValueError(f"Unsupported file format: {path_suffix}")
