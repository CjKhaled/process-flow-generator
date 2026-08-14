"""The page builder, which is where stage 3's logic lives.

The real template is used -- it is project source, and a test against a stub
shell would not notice a sentinel renamed on one side only. The viewer's files
are stubbed, so none of this needs ``npm ci``.

Nothing here opens a browser. These prove the page *says* the right things; that
it *renders* is checked by loading it in one, which is a manual step and is
recorded as such rather than faked here.
"""

import json

import pytest

from bpmn.semantics import node_element_id
from render import page as builder
from render.assets import ViewerAssets, load_template
from render.page import EMPTY_STATE, build
from validators.report import Finding, FindingCode

DIAGRAM = "<definitions><task id='Node_x' name='Transcribe the PEF' /></definitions>"


@pytest.fixture
def template() -> str:
    """The real page shell."""
    return load_template()


def page(
    template: str,
    assets: ViewerAssets,
    *findings: Finding,
    diagram: str = DIAGRAM,
    display_name: str = "Intake & Enrollment",
) -> str:
    """Build a page, defaulting everything the test under way does not care about."""
    return build(diagram, findings, display_name, assets, template)


def payload(rendered: str) -> dict[str, object]:
    """The embedded JSON block, parsed.

    Slicing to the first ``</script>`` after the block is what proves the
    escaping works: if a payload could close its own element early, this would
    cut the JSON short and fail to parse.
    """
    start = rendered.index('id="pfg-data">') + len('id="pfg-data">')
    end = rendered.index("</script>", start)
    parsed = json.loads(rendered[start:end])
    assert isinstance(parsed, dict)
    return parsed


def clarification(node_id: str, message: str = "who signs this off?") -> Finding:
    """A resolution finding about one node."""
    return Finding.of(FindingCode.NEEDS_CLARIFICATION, message, node_id)


def test_the_template_declares_every_sentinel_the_builder_fills(template: str) -> None:
    """A sentinel renamed on one side only would leave a hole in every page."""
    sentinels = (builder.TITLE, builder.STYLES, builder.VIEWER_JS, builder.QUESTIONS, builder.DATA)

    assert all(sentinel in template for sentinel in sentinels)


def test_the_diagram_reaches_the_page(template: str, viewer_assets: ViewerAssets) -> None:
    assert payload(page(template, viewer_assets))["diagram"] == DIAGRAM


def test_the_viewer_is_inlined(template: str, viewer_assets: ViewerAssets) -> None:
    rendered = page(template, viewer_assets)

    assert viewer_assets.script in rendered
    assert viewer_assets.styles in rendered
    assert "<!--PFG:" not in rendered, "a sentinel was left unsubstituted"


def test_the_display_name_titles_the_page(template: str, viewer_assets: ViewerAssets) -> None:
    rendered = page(template, viewer_assets, display_name="Intake & Enrollment")

    assert "<title>Intake &amp; Enrollment</title>" in rendered
    assert "<h1>Intake &amp; Enrollment</h1>" in rendered


def test_every_finding_is_listed(template: str, viewer_assets: ViewerAssets) -> None:
    rendered = page(
        template,
        viewer_assets,
        clarification("gw_test_result", "the source does not say what happens on the other branch"),
        Finding.of(FindingCode.MISSING_REQUIRED_SUBPROCESS, "the source does not describe 'missing_info'"),
    )

    assert "Open questions (2)" in rendered
    assert "the source does not say what happens on the other branch" in rendered
    assert "the source does not describe &#x27;missing_info&#x27;" in rendered
    assert "needs clarification" in rendered


def test_a_finding_points_at_the_bpmn_id_not_the_ir_id(template: str, viewer_assets: ViewerAssets) -> None:
    """The panel and the highlight both address elements the way the document does."""
    rendered = page(template, viewer_assets, clarification("gw_test_result"))

    assert node_element_id("gw_test_result") == "Node_gw_test_result"
    assert 'data-elements="Node_gw_test_result"' in rendered
    assert payload(rendered)["flagged"] == ["Node_gw_test_result"]


def test_a_finding_about_no_node_is_not_clickable(template: str, viewer_assets: ViewerAssets) -> None:
    """A subprocess the source never described has nothing in the diagram to point at."""
    rendered = page(template, viewer_assets, Finding.of(FindingCode.MISSING_REQUIRED_SUBPROCESS, "no 'missing_info'"))

    assert '<li class="question">' in rendered, "the card should carry no data-elements to be clicked through"
    assert payload(rendered)["flagged"] == []


def test_a_node_named_twice_is_highlighted_once(template: str, viewer_assets: ViewerAssets) -> None:
    rendered = page(template, viewer_assets, clarification("gw_test_result"), clarification("gw_test_result", "and?"))

    assert payload(rendered)["flagged"] == ["Node_gw_test_result"]


def test_findings_are_grouped_by_code(template: str, viewer_assets: ViewerAssets) -> None:
    rendered = page(
        template,
        viewer_assets,
        clarification("a", "first clarification"),
        Finding.of(FindingCode.MISSING_REQUIRED_SUBPROCESS, "a missing subprocess"),
        clarification("b", "second clarification"),
    )
    order = [rendered.index(text) for text in ("a missing subprocess", "first clarification", "second clarification")]

    assert order == sorted(order), "codes should be adjacent, and each code's findings in report order"


def test_no_findings_renders_the_empty_state(template: str, viewer_assets: ViewerAssets) -> None:
    rendered = page(template, viewer_assets)

    assert EMPTY_STATE in rendered
    assert "Open questions (0)" in rendered
    assert '<ul class="questions">' not in rendered


def test_a_closing_script_tag_cannot_break_out_of_the_payload(template: str, viewer_assets: ViewerAssets) -> None:
    """A label is quoted from a source document, so it may contain anything at all."""
    hostile = "<definitions><task name='&lt;/script&gt;<script>alert(1)</script>' /></definitions>"

    rendered = page(template, viewer_assets, diagram=hostile)

    assert payload(rendered)["diagram"] == hostile
    assert "\\u003c/script>" in rendered


def test_a_closing_script_tag_in_a_message_is_escaped(template: str, viewer_assets: ViewerAssets) -> None:
    rendered = page(template, viewer_assets, clarification("x", "</script><script>alert(1)</script>"))

    assert "&lt;/script&gt;&lt;script&gt;alert(1)&lt;/script&gt;" in rendered


def test_the_same_input_builds_the_same_page(template: str, viewer_assets: ViewerAssets) -> None:
    findings = (clarification("gw_test_result"), Finding.of(FindingCode.UNKNOWN_SUBPROCESS, "no such subprocess"))

    assert page(template, viewer_assets, *findings) == page(template, viewer_assets, *findings)
