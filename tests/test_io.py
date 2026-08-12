"""IO helper tests."""

import json
from pathlib import Path

import pytest

from ir.models import ProcessGraph
from utils.io import read_source, write_json


def test_read_source_returns_a_single_document_unheaded(tmp_path: Path) -> None:
    """One input file goes to the model as-is, with no wrapper to distract from it."""
    (tmp_path / "enrollment.md").write_text("HCP completes the PEF.\n", encoding="utf-8")

    assert read_source(tmp_path) == "HCP completes the PEF."


def test_read_source_heads_and_orders_multiple_documents(tmp_path: Path) -> None:
    """Several inputs are concatenated in filename order, each named."""
    (tmp_path / "b_offlabel.md").write_text("Off-label steps.", encoding="utf-8")
    (tmp_path / "a_intake.txt").write_text("Intake steps.", encoding="utf-8")

    combined = read_source(tmp_path)

    assert combined.index("a_intake.txt") < combined.index("b_offlabel.md")
    assert "Intake steps." in combined and "Off-label steps." in combined


def test_read_source_ignores_other_file_types(tmp_path: Path) -> None:
    """Only prose documents are treated as source."""
    (tmp_path / "notes.md").write_text("Real source.", encoding="utf-8")
    (tmp_path / "diagram.png").write_bytes(b"\x89PNG")

    assert read_source(tmp_path) == "Real source."


def test_read_source_requires_an_existing_directory(tmp_path: Path) -> None:
    """A missing inputs directory fails immediately, not mid-run."""
    with pytest.raises(FileNotFoundError, match="no inputs directory"):
        read_source(tmp_path / "nope")


def test_read_source_requires_at_least_one_document(tmp_path: Path) -> None:
    """An empty inputs directory is a setup error worth naming."""
    with pytest.raises(FileNotFoundError, match="no source documents"):
        read_source(tmp_path)


def test_write_json_round_trips_and_creates_parents(tmp_path: Path, valid_graph: ProcessGraph) -> None:
    """The written file parses back into an equal graph."""
    destination = tmp_path / "outputs" / "graph.json"

    write_json(destination, valid_graph)

    assert json.loads(destination.read_text(encoding="utf-8"))["process_name"] == "enrollment"
    assert ProcessGraph.model_validate_json(destination.read_text(encoding="utf-8")) == valid_graph
