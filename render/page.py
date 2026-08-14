"""Assemble the page: a laid-out diagram and its open questions become one HTML file.

Pure string assembly -- every byte it needs is passed in, so the same arguments
always produce the same page and nothing here touches the filesystem. Reading is
:mod:`render.assets`' job.

Two decisions are load-bearing:

* **The question list is built here, not in the browser.** The panel is ordinary
  HTML with the flagged BPMN ids on ``data-elements`` attributes, so what the
  page says can be asserted by reading it. The page's JavaScript only wires the
  clicking up; it decides nothing.
* **A finding's ``node_ids`` are IR ids and the page needs BPMN ids**, so they go
  through :func:`bpmn.semantics.node_element_id`. That function is imported
  rather than reimplemented: an NCName slug rule that exists in two places will
  eventually disagree with itself, and the failure would be a highlight silently
  landing on nothing.

Everything interpolated is escaped for the context it lands in: text and
attributes through :func:`html.escape`, and the payload through ``json.dumps``
with ``<`` escaped besides, so that no label or finding message can contain a
closing script tag and break out of the block it is embedded in.
"""

import json
from collections.abc import Mapping, Sequence
from html import escape

from bpmn.semantics import node_element_id
from render.assets import ViewerAssets
from validators.report import Finding

TITLE = "<!--PFG:TITLE-->"
STYLES = "<!--PFG:STYLES-->"
VIEWER_JS = "<!--PFG:VIEWER_JS-->"
QUESTIONS = "<!--PFG:QUESTIONS-->"
DATA = "<!--PFG:DATA-->"

EMPTY_STATE = "Nothing outstanding. Every box in this diagram is stated by the source text."

LEDE = "Raised by stage 1. Select one to find it in the diagram."


def build(
    diagram: str,
    findings: Sequence[Finding],
    display_name: str,
    assets: ViewerAssets,
    template: str,
) -> str:
    """Render the page.

    Args:
        diagram: The laid-out BPMN document, DI included.
        findings: The open questions to list, usually a report's resolution tier.
            Order is preserved within a code; the codes themselves are grouped.
        display_name: The process's human-readable name, for the title and header.
        assets: The viewer's script and stylesheets, to inline.
        template: The page shell, sentinels unsubstituted.

    Returns:
        A self-contained HTML document.
    """
    grouped = sorted(findings, key=lambda finding: finding.code)
    payload = {
        "diagram": diagram,
        "flagged": list(dict.fromkeys(node_element_id(node_id) for finding in grouped for node_id in finding.node_ids)),
    }

    page = template
    page = page.replace(TITLE, escape(display_name))
    page = page.replace(QUESTIONS, _questions(grouped))
    page = page.replace(STYLES, assets.styles)
    page = page.replace(VIEWER_JS, assets.script)
    return page.replace(DATA, _payload(payload))


def _questions(findings: Sequence[Finding]) -> str:
    """The panel: a heading, and one card per finding or an empty state."""
    heading = f"<h2>Open questions ({len(findings)})</h2>"
    if not findings:
        return f'{heading}<p class="empty">{EMPTY_STATE}</p>'

    cards = "".join(_card(finding) for finding in findings)
    return f'{heading}<p class="lede">{LEDE}</p><ul class="questions">{cards}</ul>'


def _card(finding: Finding) -> str:
    """One finding.

    A finding with no ``node_ids`` -- a subprocess the source never described --
    has nothing to point at, so it gets no ``data-elements`` and is not clickable.
    """
    elements = " ".join(node_element_id(node_id) for node_id in finding.node_ids)
    attribute = f' data-elements="{escape(elements)}"' if elements else ""
    label = escape(finding.code.replace("_", " "))
    return (
        f'<li class="question"{attribute}>'
        f'<span class="code">{label}</span>'
        f'<span class="message">{escape(finding.message)}</span>'
        f"</li>"
    )


def _payload(payload: Mapping[str, object]) -> str:
    """JSON for the embedded script block.

    ``<`` is escaped as well as the JSON minimum. Inside a ``<script>`` element
    the HTML parser is looking for one thing only -- a closing tag -- so a diagram
    label reading ``</script>`` would otherwise end the block early and spill the
    rest of the document into the page as text.
    """
    return json.dumps(payload, ensure_ascii=False).replace("<", "\\u003c")
