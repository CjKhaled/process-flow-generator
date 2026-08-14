"""Assemble the page: a laid-out diagram and its open questions become one HTML file.

Pure string assembly -- every byte it needs is passed in, so the same arguments
always produce the same page and nothing here touches the filesystem. Reading is
:mod:`render.assets`' job.

The same template serves two deliveries, and :func:`payload` is what they share:

* :func:`build` inlines a payload into the page, which is stage 3's offline
  ``diagram.html`` -- self-contained, opened with Live Server or over ``file://``.
* :func:`build_app` builds the hosted page instead, which starts on a form and
  fetches the *same payload object* from the API once a run finishes.

Two decisions are load-bearing:

* **The question list is built here, not in the browser.** The panel is ordinary
  HTML with the flagged BPMN ids on ``data-elements`` attributes, so what the
  page says can be asserted by reading it -- and the hosted page receives that
  finished HTML rather than rendering findings itself. Escaping therefore has
  one home, whichever way the payload arrives.
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
VIEW = "<!--PFG:VIEW-->"
PROCESSES = "<!--PFG:PROCESSES-->"

EMPTY_STATE = "Nothing outstanding. Every box in this diagram is stated by the source text."

LEDE = "Raised by stage 1. Select one to find it in the diagram."

APP_TITLE = "Process Flow Generator"
"""What the hosted page is called before a run has named a process."""


def payload(diagram: str, findings: Sequence[Finding], display_name: str) -> dict[str, object]:
    """One finished run, as the page consumes it.

    The single shape: :func:`build` inlines it, and the API returns it as JSON.
    A change here reaches both, which is the point -- the hosted page and the
    offline one render identical results because they are handed identical data.

    Args:
        diagram: The laid-out BPMN document, DI included.
        findings: The open questions to list, usually a report's resolution tier.
            Order is preserved within a code; the codes themselves are grouped.
        display_name: The process's human-readable name.

    Returns:
        ``title``, ``questions`` (finished HTML), ``count`` (how many, for the
        panel's toggle), ``diagram``, and ``flagged`` -- the BPMN ids to mark,
        each once, in the order the panel names them.
    """
    grouped = sorted(findings, key=lambda finding: finding.code)
    flagged = dict.fromkeys(node_element_id(node_id) for finding in grouped for node_id in finding.node_ids)
    return {
        "title": display_name,
        "questions": _questions(grouped),
        "count": len(grouped),
        "diagram": diagram,
        "flagged": list(flagged),
    }


def build(
    diagram: str,
    findings: Sequence[Finding],
    display_name: str,
    assets: ViewerAssets,
    template: str,
) -> str:
    """Render the offline page: one file, everything inlined, nothing fetched.

    Args:
        diagram: The laid-out BPMN document, DI included.
        findings: The open questions to list.
        display_name: The process's human-readable name, for the title and header.
        assets: The viewer's script and stylesheets, to inline.
        template: The page shell, sentinels unsubstituted.

    Returns:
        A self-contained HTML document showing the diagram.
    """
    data = payload(diagram, findings, display_name)
    return _fill(
        template,
        assets,
        title=display_name,
        view="diagram",
        # The panel is written into the markup, so this page reads correctly with
        # no script run at all -- and for the same reason the payload inlined
        # below leaves ``questions`` and ``title`` out rather than shipping them
        # a second time. Only what the viewer cannot read off the page travels
        # as data.
        questions=str(data["questions"]),
        processes="",
        data={"diagram": data["diagram"], "flagged": data["flagged"], "count": data["count"]},
    )


def build_app(
    assets: ViewerAssets,
    template: str,
    processes: Sequence[tuple[str, str]],
    api_base: str,
) -> str:
    """Render the hosted page: a form first, a diagram once the API has run one.

    The same shell as :func:`build`, with no diagram in it. The page asks the API
    for a run and is handed a :func:`payload` when one finishes, so from the
    moment it has data the two pages are the same page.

    Args:
        assets: The viewer's script and stylesheets, to inline.
        template: The page shell, sentinels unsubstituted.
        processes: ``(name, display_name)`` for each selectable process, in the
            order they should be offered.
        api_base: Where the API lives, without a trailing slash. Empty means the
            page is served by the API itself, and requests are same-origin.

    Returns:
        A self-contained HTML document showing the landing form.
    """
    return _fill(
        template,
        assets,
        title=APP_TITLE,
        view="landing",
        questions="",
        processes="".join(_option(name, display_name) for name, display_name in processes),
        data={"api": api_base.rstrip("/")},
    )


def _fill(
    template: str,
    assets: ViewerAssets,
    *,
    title: str,
    view: str,
    questions: str,
    processes: str,
    data: Mapping[str, object],
) -> str:
    """Substitute every sentinel. The one place the template's contract is spelled out."""
    page = template
    page = page.replace(TITLE, escape(title))
    page = page.replace(VIEW, escape(view, quote=True))
    page = page.replace(QUESTIONS, questions)
    page = page.replace(PROCESSES, processes)
    page = page.replace(STYLES, assets.styles)
    page = page.replace(VIEWER_JS, assets.script)
    return page.replace(DATA, _payload(data))


def _option(name: str, display_name: str) -> str:
    """One entry of the process picker."""
    return f'<option value="{escape(name, quote=True)}">{escape(display_name)}</option>'


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


def _payload(data: Mapping[str, object]) -> str:
    """JSON for the embedded script block.

    ``<`` is escaped as well as the JSON minimum. Inside a ``<script>`` element
    the HTML parser is looking for one thing only -- a closing tag -- so a diagram
    label reading ``</script>`` would otherwise end the block early and spill the
    rest of the document into the page as text. The panel's HTML travels through
    here too, so the escaping is what keeps *it* inert as well.
    """
    return json.dumps(data, ensure_ascii=False).replace("<", "\\u003c")
