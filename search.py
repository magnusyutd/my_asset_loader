# content     = Functions to search and retrieve project folder structure.
# dependency  = pyyaml
# how_to      = Define project folder structure in '6_config/project.yaml'.
# author      = Magnus Yu <magnusyu.com>

import os
import re
import json
from pathlib import Path

from scripts.external import yaml


def build_tree_node(node: dict) -> dict:
    """Build tree node recursively from the given nested dictionary structure.
       Each node will have its children as a dictionary.

    ARGS:
        node: Nested dict structure created by find_proj_sub_folders

    RETURN: dict representing children for this node
    """
    children = {}
    for name, child in node.items():
        if name == "path":
            continue
        if isinstance(child, dict):
            children[name] = build_tree_node(child)
        else:
            children[name] = {}
    return children

def build_folder_tree(sub_folders: dict) -> dict:
    """Build a hierarchical tree view of sub_folders only (excluding the project folder itself).

    ARGS:
        sub_folders(dict): Nested dict structure created by find_proj_sub_folders
        root_path(Path): The root path (unused, kept for compatibility)
    """
    tree = {}
    for name, child in sub_folders.items():
        if name == "path":
            continue
        if isinstance(child, dict):
            tree[name] = build_tree_node(child)
        else:
            tree[name] = {}
    return tree

def find_proj_folders(root_path: Path) -> dict:
    """
    Find project folder with given root path

    ARGS:
        root_path: The root directory path to search for project folders
    RETURN: dict of folder names and their Path objects
    """
    folders = {}
    for item in root_path.iterdir():
        if item.is_dir():
            folders[item.name] = item
    return folders

def find_proj_sub_folders(root_path: Path) -> dict:
    """ Find all sub_folders of the given path, excluding version folders.

    ARGS:
        root_path: The parent directory path

    RETURN: nested dict of subfolder names with each node storing its Path in "_path"
    """
    sub_folders = {}

    # Folder structure
    for item in root_path.rglob("*"):
        # Skip version folder and filter folders like "textures", "publish", "work"
        if item.is_dir() and not is_version_path(item) and not is_filter_folder(item):
            # Get the folder parts relative to your starting directory
            parts = item.relative_to(root_path).parts
            # Navigate/Create the nested structure
            current_level = sub_folders
            current_path = root_path

            for part in parts:
                current_path = current_path / part
                if part not in current_level:
                    current_level[part] = {"path": current_path}
                elif "path" not in current_level[part]:
                    current_level[part]["path"] = current_path
                current_level = current_level[part]

    return sub_folders

def find_asset_versions(asset_folder_path: Path) -> dict:
    """ Build a mapping of asset file name -> {version_folder: file_path}.
    Skips any files under a "textures" directory.

    ARGS:
        asset_folder_path: Root asset folder to search

    RETURN: dict of asset file name to version mapping
    """
    # dict[str, dict[str, Path]]
    asset_paths = {}

    for item in asset_folder_path.rglob("*"):
        if item.is_file() and "textures" not in item.parts \
            and not item.suffix == ".json":
            versions = asset_paths.setdefault(item.name, {})
            if re.match(r'^v\d+$', item.parent.name):
                # print ("versions:", versions)
                versions[item.parent.name] = item
                # print ("asset_paths:", asset_paths)
            else:
                # For WIP files without json info
                versions["v000"] = item

    return asset_paths

def find_asset_details(asset_paths: dict) -> dict:
    """ For each asset file name, look into its version folders for json metadata.

    ARGS:
        asset_paths(dict): Mapping of asset file name to version folder paths

    RETURN: dict of asset file name to version metadata
    """
    asset_details = {}
    for asset_name, versions in asset_paths.items():
        #latest_version, version_path = list(versions.items())[-1]
        ver_details = {}

        # Look into each version folder for json metadata
        for ver_num, ver_path in versions.items():
            ver_basename = ver_path.stem
            ver_json_path = ver_path.parent / f"{ver_basename}.json"
            if ver_json_path.is_file():
                json_data = open_json(ver_json_path)
                json_data["path"] = ver_path
                ver_details[ver_num] = json_data
            else:
                # For WIP files without json info
                data = {"path": ver_path}
                data = {"status": "UNPUBLISHED", **data}
                ver_details[ver_num] = data

        asset_details[asset_name] = ver_details

    return asset_details

def find_data_by_key(data:dict, target:str):
    """ Recursively search for a key in nested dictionaries and return its value.
    
    ARGS:
        data: The dictionary to search
        target: The key to find

    RETURN: The value associated with the target key, or None if not found
    """
    # Check if the target key is in the current dictionary level
    if target in data:
        return data[target]

    # Otherwise, recurse into nested dictionaries
    for value in data.values():
        if isinstance(value, dict):
            result = find_data_by_key(value, target)
            if result is not None:
                return result
    return None

def get_project_path() -> Path:
    """ Load project path from configuration file.

    RETURN: Path object of the project path
    """
    config_path = Path(__file__).parent / "config/project.yaml"
    print (f"Loading project config from: {config_path}")

    with open(config_path, 'r') as file:
        data = yaml.safe_load(file)
        raw_path = data.get('project_path')
        print (f"Raw project path from config: {raw_path}")
        expanded_path = os.path.expandvars(raw_path) if raw_path else raw_path
        return Path(expanded_path)

def is_version_path(path: Path) -> bool:
    """ Check if the given path is a version folder.    
    """
    is_ver_path = any(re.match(r'^v\d+$', part) for part in path.parts)
    return is_ver_path

def is_filter_folder(path: Path) -> bool:
    """ Check if the given path contains any filter keywords like "textures"
    """
    is_filter = any(part.lower() in ["textures"] for part in path.parts)
    return is_filter

def open_json(json_path: Path) -> dict:
    json_data = {}
    with open(json_path) as json_file:
        json_data = json.load(json_file)
    return json_data


# Sample usage ****************************************************************************
project_path = get_project_path()

project_folders = find_proj_folders(project_path)

folder_name = "my_project"
folder_path = project_folders.get(folder_name)

print(f"Folder: {folder_name}")
project_sub_folders = find_proj_sub_folders(folder_path)
print ("sub_folders: ", project_sub_folders)
# print(f"Flat view: {[p.name for p in project_sub_folders]}\n")
print(f"Flat view: {list(project_sub_folders.keys())}\n")

# Build and display tree view
# folder_tree = build_folder_tree(project_sub_folders, folder_path)
folder_tree = build_folder_tree(project_sub_folders)
print("Folder Tree Structure:")
print (folder_tree)
