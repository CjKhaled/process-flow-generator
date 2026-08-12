"""Thin IO helpers: read the input text, write the output JSON."""

import json
from pathlib import Path

from pydantic import BaseModel

SOURCE_SUFFIXES = (".md", ".txt")


def read_source(directory: Path) -> str:
    """Concatenate every source document in a process's ``inputs/`` directory.

    Files are read in filename order so a run is reproducible. When there is more
    than one, each is preceded by a heading naming it, so the model can tell where
    one document ends and the next begins.

    Args:
        directory: The ``inputs/`` directory.

    Returns:
        The combined source text.

    Raises:
        FileNotFoundError: If the directory is missing or holds no source files.
    """
    if not directory.is_dir():
        raise FileNotFoundError(f"no inputs directory at {directory}")

    paths = sorted(p for p in directory.iterdir() if p.is_file() and p.suffix.lower() in SOURCE_SUFFIXES)
    if not paths:
        suffixes = ", ".join(SOURCE_SUFFIXES)
        raise FileNotFoundError(f"no source documents ({suffixes}) in {directory}")

    if len(paths) == 1:
        return paths[0].read_text(encoding="utf-8").strip()
    return "\n\n".join(f"# {p.name}\n\n{p.read_text(encoding='utf-8').strip()}" for p in paths)


def write_json(path: Path, model: BaseModel) -> None:
    """Write a Pydantic model to disk as indented JSON.

    Args:
        path: Destination file. Parent directories are created as needed.
        model: The model to serialise.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = model.model_dump(mode="json")
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
