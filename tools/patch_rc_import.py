from pathlib import Path


def patch_qtcore_import(rc_file: Path) -> int:
    if not rc_file.exists():
        print(f"ERROR: File not found: {rc_file}")
        return 1

    content = rc_file.read_text(encoding="utf-8")

    target = "from PySide2 import QtCore"
    replacement = (
        "try:\n"
        "    from PySide2 import QtCore\n"
        "except ImportError:\n"
        "    from PySide6 import QtCore"
    )

    if replacement in content:
        print("QtCore import block already patched.")
        return 0

    if target not in content:
        print("WARNING: Expected PySide2 import line was not found; no patch applied.")
        return 0

    content = content.replace(target, replacement, 1)
    rc_file.write_text(content, encoding="utf-8")
    print(f"Patched QtCore import in: {rc_file}")
    return 0


if __name__ == "__main__":
    repo_root = Path(__file__).resolve().parents[2]
    rc_path = repo_root / "my_asset_loader_rc.py"
    raise SystemExit(patch_qtcore_import(rc_path))
