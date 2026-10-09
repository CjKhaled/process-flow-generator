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
from render.page import payload as run_payload
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
    element_of: dict[str, str] | None = None,
) -> str:
    """Build a page, defaulting everything the test under way does not care about."""
    return build(diagram, findings, display_name, assets, template, element_of)


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
    sentinels = (
        builder.TITLE,
        builder.STYLES,
        builder.VIEWER_JS,
        builder.QUESTIONS,
        builder.DATA,
    )

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


def test_a_finding_inside_a_collapsed_subprocess_points_at_the_box(template: str, viewer_assets: ViewerAssets) -> None:
    """Stage 2 drew one box in place of the step, so the highlight has to follow it."""
    rendered = page(
        template,
        viewer_assets,
        clarification("gw_test_result"),
        element_of={"gw_test_result": "Node_sub_off_label"},
    )

    assert 'data-elements="Node_sub_off_label"' in rendered
    assert payload(rendered)["flagged"] == ["Node_sub_off_label"]


def test_a_map_that_does_not_mention_a_node_leaves_it_alone(template: str, viewer_assets: ViewerAssets) -> None:
    """The map is stage 2's answer where it has one, not a replacement for the slug rule."""
    rendered = page(template, viewer_assets, clarification("gw_test_result"), element_of={"other": "Node_sub_x"})

    assert payload(rendered)["flagged"] == ["Node_gw_test_result"]


def test_two_findings_inside_one_collapse_mark_the_box_once(template: str, viewer_assets: ViewerAssets) -> None:
    """data-elements is a selector; naming the same box twice would mark it twice."""
    both = {"gw_test_result": "Node_sub_off_label", "term_off_label": "Node_sub_off_label"}
    rendered = page(
        template,
        viewer_assets,
        Finding.of(FindingCode.NEEDS_CLARIFICATION, "two at once", "gw_test_result", "term_off_label"),
        element_of=both,
    )

    assert 'data-elements="Node_sub_off_label"' in rendered
    assert payload(rendered)["flagged"] == ["Node_sub_off_label"]


def test_a_page_built_without_a_map_is_unchanged(template: str, viewer_assets: ViewerAssets) -> None:
    """The argument is optional, and adding it must not have moved anything else."""
    findings = (clarification("gw_test_result"), Finding.of(FindingCode.MISSING_REQUIRED_SUBPROCESS, "no 'x'"))

    assert build(DIAGRAM, findings, "Intake & Enrollment", viewer_assets, template) == build(
        DIAGRAM, findings, "Intake & Enrollment", viewer_assets, template, None
    )


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


def test_the_page_fetches_nothing(template: str, viewer_assets: ViewerAssets) -> None:
    """One self-contained file, opened from wherever the reader keeps it: no server to ask."""
    rendered = page(template, viewer_assets)

    assert "fetch(" not in rendered
    assert "<form" not in rendered


def test_the_page_offers_edit_and_reset(template: str, viewer_assets: ViewerAssets) -> None:
    rendered = page(template, viewer_assets)

    assert 'data-action="edit"' in rendered
    assert 'data-action="reset"' in rendered


def test_the_page_starts_with_editing_off(template: str, viewer_assets: ViewerAssets) -> None:
    """A page that opened mid-edit would let a reader rearrange the result by accident.

    The attribute is also the state itself, not a description of it: the flag lives
    in the bundle where the page cannot see it, so the Edit button reads this back to
    know what to flip to. Ship the page without it and the first click has nothing to
    invert.
    """
    rendered = page(template, viewer_assets)

    assert 'data-editing="off"' in rendered
    assert 'class="edit" data-action="edit" aria-pressed="false"' in rendered


def test_the_page_says_edits_are_not_saved(template: str, viewer_assets: ViewerAssets) -> None:
    """The one thing a reader must not have to discover by losing work."""
    rendered = page(template, viewer_assets)

    assert "Nothing is saved" in rendered
    assert "reloading restores the generated diagram" in rendered


def test_the_page_warns_that_the_questions_describe_the_original(template: str, viewer_assets: ViewerAssets) -> None:
    """Findings are never recomputed, so an edited diagram outruns its own panel."""
    assert "The open questions still describe the original." in page(template, viewer_assets)


def test_a_floating_label_is_given_a_halo(template: str, viewer_assets: ViewerAssets) -> None:
    """Yes and No sit on their arrow, and are unreadable where the two cross without one.

    The one piece of appearance still decided in CSS. Colour moved into the
    diagram file, where bpmn-js's own API puts it, but there is no API for this.
    """
    rendered = page(template, viewer_assets)

    assert '[data-element-id$="_label"] .djs-label' in rendered
    assert "paint-order: stroke" in rendered


def test_the_page_does_not_colour_elements_itself(template: str) -> None:
    """Colour belongs to the diagram now, so the stylesheet must not compete for it.

    ``bpmn/colors.py`` writes the attributes bpmn-js reads, which is what lets
    Camunda draw the same diagram. A rule here would override that for our page
    only, and the two would drift apart without anything failing.
    """
    assert "--event-fill" not in template
    assert "--sub-fill" not in template
    assert "\n  .djs-visual > circle {" not in template


def test_the_open_question_highlight_beats_a_colour_from_the_diagram(template: str) -> None:
    """A flagged box stays amber even though the file now says what colour it is.

    bpmn-js renders a diagram colour as an SVG ``fill`` attribute, and a
    presentation attribute loses to any stylesheet rule -- but the highlight is
    forced anyway, because being unable to see which boxes carry open questions
    is the one failure this page cannot afford.
    """
    assert "fill: var(--flag-tint) !important" in template


# ---- the payload, which the API returns and the offline page inlines ----------


def test_the_payload_carries_what_a_page_needs() -> None:
    data = run_payload(DIAGRAM, [clarification("gw_test_result")], "Intake & Enrollment")

    assert data["title"] == "Intake & Enrollment"
    assert data["diagram"] == DIAGRAM
    assert data["count"] == 1
    assert data["flagged"] == ["Node_gw_test_result"]


def test_the_payload_carries_the_panel_as_finished_html() -> None:
    """The panel is inlined verbatim, so the escaping has to happen here."""
    data = run_payload(DIAGRAM, [clarification("x", "who signs <this> off?")], "Enrollment")

    assert "&lt;this&gt;" in str(data["questions"])
    assert "<this>" not in str(data["questions"])


def test_the_offline_page_and_the_payload_agree(template: str, viewer_assets: ViewerAssets) -> None:
    """The two deliveries must not drift: same findings, same panel, same marks."""
    findings = (clarification("gw_test_result"), Finding.of(FindingCode.MISSING_REQUIRED_SUBPROCESS, "no info"))
    rendered = page(template, viewer_assets, *findings)
    data = run_payload(DIAGRAM, findings, "Intake & Enrollment")

    assert str(data["questions"]) in rendered
    assert payload(rendered)["flagged"] == data["flagged"]
