# content = Test script for project folder scanning and tree building.
# author  = Magnus Yu <magnusyu.com>

from os import path
import yaml
import re
from pathlib import Path


def get_project_path():
    config_path = Path(__file__).parent.parent / "config/project.yaml"
    print (f"Loading project config from: {config_path}")

    with open(config_path, 'r') as file:
        data = yaml.safe_load(file)
        return Path(data.get('project_path'))


def get_latest_version_folder(parent_path):
    """Find the latest version folder if it exists (e.g., v001, v002, etc.)"""
    try:
        version_folders = [
            item for item in parent_path.iterdir()
            if item.is_dir() and re.match(r'^v\d+$', item.name)
        ]
        if version_folders:
            return max(version_folders, key=lambda x: int(x.name[1:]))
    except (OSError, ValueError):
        pass
    return None


def is_version_folder_path(file_path):
    """Check if file is within a version folder"""
    return any(re.match(r'^v\d+$', part) for part in file_path.parts)

def find_proj_folders(path):
    folders = {}
    for item in path.iterdir():
        if item.is_dir():
            folders[item.name] = item
    return folders

def find_proj_sub_folders(path):
    project_sub_folders = {}
    # Folder structure
    for item in path.rglob("*"):
        # Skip version folder
        if item.is_dir() and not any(re.match(r'^v\d+$', part) for part in item.parts):
            project_sub_folders[item.name] = item

    return project_sub_folders

def build_folder_tree(project_sub_folders:dict, root_path:str):
    """
    Build a hierarchical tree view of sub_folders only (excluding the project folder itself).
    Returns a nested dictionary representation of the folder structure.
    """
    tree = {}

    for _, sub_path in project_sub_folders.items():
        rel_path = sub_path.relative_to(root_path)
        parts = rel_path.parts

        if parts:  # Only add if there are parts (not the root itself)
            # Navigate/create the tree structure
            current = tree
            for part in parts[:-1]:
                if part not in current:
                    current[part] = {}
                current = current[part]
            # Add the final folder
            if parts[-1] not in current:
                current[parts[-1]] = {}

    return tree

project_path = get_project_path()

skip_folder = ["textures"]
version_cache = {}  # Cache to avoid re-scanning same parent directories

# # Check all the given assets in the given folder
# for item in project_path.rglob("*"):
#     if item.is_file() and item.parent.name not in skip_folder:
#         grandparent = item.parent.parent

#         # Check cache first
#         if grandparent not in version_cache:
#             version_cache[grandparent] = get_latest_version_folder(grandparent)

#         latest_version = version_cache[grandparent]

#         if latest_version:
#             # Only include files from the latest version folder
#             if item.parent == latest_version:
#                 print(f"{item.parent.name}/{item.name}")
#         elif not is_version_folder_path(item):
#             # Only include files that are not within any version folder
#             print(item.name)

project_folders = find_proj_folders(project_path)

folder_name = "my_project"
folder_path = project_folders.get(folder_name)

print(f"Folder: {folder_name}")
project_sub_folders = find_proj_sub_folders(folder_path)
print(f"Flat view: {list(project_sub_folders.keys())}\n")

# Build and display tree view
folder_tree = build_folder_tree(project_sub_folders, folder_path)
print("Folder Tree Structure:")
print (folder_tree)
