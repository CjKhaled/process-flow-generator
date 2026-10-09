"""Thin IO helper: write a model to disk as JSON."""

import json
from pathlib import Path

from pydantic import BaseModel


def write_json(path: Path, model: BaseModel) -> None:
    """Write a Pydantic model to disk as indented JSON.

    Args:
        path: Destination file. Parent directories are created as needed.
        model: The model to serialise.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = model.model_dump(mode="json")
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
