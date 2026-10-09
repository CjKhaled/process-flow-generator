"""IO helper tests."""

import json
from pathlib import Path

from ir.models import ProcessGraph
from utils.io import write_json


def test_write_json_round_trips_and_creates_parents(tmp_path: Path, valid_graph: ProcessGraph) -> None:
    """The written file parses back into an equal graph."""
    destination = tmp_path / "outputs" / "graph.json"

    write_json(destination, valid_graph)

    assert json.loads(destination.read_text(encoding="utf-8"))["process_name"] == "enrollment"
    assert ProcessGraph.model_validate_json(destination.read_text(encoding="utf-8")) == valid_graph
