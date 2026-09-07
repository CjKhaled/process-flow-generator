"""The page builder, which is where stage 3's logic lives.

The real template is used -- it is project source, and a test against a stub
shell would not notice a sentinel renamed on one side only. The viewer's files
are stubbed, so none of this needs ``npm ci``.

One shell serves two pages, so both are exercised here: the offline
``diagram.html`` stage 3 writes, and the hosted page that starts on a form. The
offline assertions are the older ones and are deliberately unchanged -- if the
shell grew a landing view at the cost of the page stage 3 produces, they are
what would say so.

Nothing here opens a browser. These prove the page *says* the right things; that
it *renders* is checked by loading it in one, which is a manual step and is
recorded as such rather than faked here.
"""

import json

import pytest

from bpmn.semantics import node_element_id
from render import page as builder
from render.assets import ViewerAssets, load_template
from render.page import APP_TITLE, EMPTY_STATE, build, build_app
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
        builder.VIEW,
        builder.PROCESSES,
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


def test_the_offline_page_opens_on_the_diagram(template: str, viewer_assets: ViewerAssets) -> None:
    """Stage 3's page has its result in it already; it must never flash the form."""
    assert 'data-view="diagram"' in page(template, viewer_assets)


# ---- edit mode ---------------------------------------------------------------
#
# Session-only, so there is nothing on disk for a test to inspect afterwards.
# What can be asserted from here is that the page *offers* editing and *starts*
# with it off; whether a box can actually be dragged is settled by opening the
# page, like everything else interactive.


def test_the_page_offers_edit_and_reset(template: str, viewer_assets: ViewerAssets) -> None:
    rendered = page(template, viewer_assets)

    assert 'data-action="edit"' in rendered
    assert 'data-action="reset"' in rendered


def test_the_page_starts_with_editing_off(template: str, viewer_assets: ViewerAssets) -> None:
    """A page that opened mid-edit would let a reader rearrange the result by accident."""
    rendered = page(template, viewer_assets)

    assert 'data-editing="off"' in rendered
    assert 'class="edit" data-action="edit" aria-pressed="false"' in rendered


def test_the_page_says_edits_are_not_saved(template: str, viewer_assets: ViewerAssets) -> None:
    """The one thing a reader must not have to discover by losing work."""
    rendered = page(template, viewer_assets)

    assert "Nothing is saved" in rendered
    assert "reloading restores the generated diagram" in rendered


def test_the_page_warns_that_the_questions_describe_the_original(
    template: str, viewer_assets: ViewerAssets
) -> None:
    """Findings are never recomputed, so an edited diagram outruns its own panel."""
    assert "The open questions still describe the original." in page(template, viewer_assets)


def test_the_hosted_page_offers_editing_too(template: str, viewer_assets: ViewerAssets) -> None:
    """One shell serves both deliveries, so this is a property of the shell, not of stage 3."""
    rendered = build_app(viewer_assets, template, [("enrollment", "Intake & Enrollment")], "")

    assert 'data-action="edit"' in rendered
    assert 'data-editing="off"' in rendered


# ---- the payload, which the API returns and the offline page inlines ----------


def test_the_payload_carries_what_a_page_needs() -> None:
    data = run_payload(DIAGRAM, [clarification("gw_test_result")], "Intake & Enrollment")

    assert data["title"] == "Intake & Enrollment"
    assert data["diagram"] == DIAGRAM
    assert data["count"] == 1
    assert data["flagged"] == ["Node_gw_test_result"]


def test_the_payload_carries_the_panel_as_finished_html() -> None:
    """The hosted page inserts this verbatim, so the escaping has to happen here."""
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


# ---- the hosted page ---------------------------------------------------------


def app(template: str, assets: ViewerAssets, *, api_base: str = "https://pfg.example.com") -> str:
    """Build the hosted page, defaulting what the test under way does not care about."""
    return build_app(assets, template, [("enrollment", "Intake & Enrollment")], api_base)


def test_the_hosted_page_opens_on_the_form(template: str, viewer_assets: ViewerAssets) -> None:
    rendered = app(template, viewer_assets)

    assert 'data-view="landing"' in rendered
    assert "<!--PFG:" not in rendered, "a sentinel was left unsubstituted"


def test_the_hosted_page_carries_no_diagram(template: str, viewer_assets: ViewerAssets) -> None:
    """It has nothing to draw until the API has run something."""
    data = payload(app(template, viewer_assets))

    assert "diagram" not in data
    assert data["api"] == "https://pfg.example.com"


def test_the_hosted_page_offers_every_process(template: str, viewer_assets: ViewerAssets) -> None:
    rendered = build_app(
        viewer_assets,
        template,
        [("enrollment", "Intake & Enrollment"), ("copay", "Copay Support")],
        "",
    )

    assert '<option value="enrollment">Intake &amp; Enrollment</option>' in rendered
    assert '<option value="copay">Copay Support</option>' in rendered


def test_the_hosted_page_is_titled_before_a_run(template: str, viewer_assets: ViewerAssets) -> None:
    """No process has been picked yet, so the header cannot name one."""
    rendered = app(template, viewer_assets)

    assert f"<title>{APP_TITLE}</title>" in rendered
    assert f"<h1>{APP_TITLE}</h1>" in rendered


def test_a_same_origin_deployment_needs_no_host(template: str, viewer_assets: ViewerAssets) -> None:
    """Served by the API itself, the page's requests are relative."""
    assert payload(app(template, viewer_assets, api_base=""))["api"] == ""


def test_a_trailing_slash_would_double_up(template: str, viewer_assets: ViewerAssets) -> None:
    """The page appends '/runs', so the base must not end in one."""
    assert (
        payload(app(template, viewer_assets, api_base="https://pfg.example.com/"))["api"] == "https://pfg.example.com"
    )


def test_a_hostile_process_name_cannot_break_the_picker(template: str, viewer_assets: ViewerAssets) -> None:
    rendered = build_app(viewer_assets, template, [('" onmouseover="alert(1)', "<b>bold</b>")], "")

    assert 'onmouseover="alert(1)' not in rendered
    assert "<b>bold</b>" not in rendered
