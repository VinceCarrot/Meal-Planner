"""Low-level YAML reading and safe writing."""

import os
import shutil
from pathlib import Path
from typing import Any

import yaml


class YamlReadError(Exception):
    pass


def read_yaml(path: Path) -> Any:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise YamlReadError(f"file not found: {path}") from None
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError as e:
        backup = _backup_path(path)
        hint = f" (a backup exists: {backup.name})" if backup.exists() else ""
        raise YamlReadError(f"invalid YAML in {path}: {e}{hint}") from None


def dump_yaml(data: Any) -> str:
    return yaml.safe_dump(data, allow_unicode=True, sort_keys=False)


def write_yaml_atomic(path: Path, data: Any) -> None:
    """Replace `path` atomically, keeping the previous content as `<name>.bak`.

    The data is serialized before anything on disk is touched, so a
    serialization error leaves the existing file unchanged.
    """
    text = dump_yaml(data)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    try:
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        if path.exists():
            shutil.copy2(path, _backup_path(path))
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def create_yaml(path: Path, data: Any) -> None:
    """Write a new file; fail if it already exists (used for immutable records)."""
    text = dump_yaml(data)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "x", encoding="utf-8", newline="\n") as f:
        f.write(text)


def _backup_path(path: Path) -> Path:
    return path.with_name(path.name + ".bak")
