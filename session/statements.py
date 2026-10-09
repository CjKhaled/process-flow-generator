"""Split the first description into statements. Deterministic, no model.

A statement is the unit every node and branch cites, so the split decides how
precisely the graph can point at its source. It is done by code rather than by a
model for one reason: the text of a statement is what quotes are checked against,
and a model asked to split a description is also free to tidy it.

Lines first, then sentences. Each non-empty line is taken on its own -- written
process descriptions put one thought on a line far more reliably than they
punctuate -- and a line holding several sentences is divided at sentence ends. A
heading is simply a line, so it becomes a statement of its own without being
recognised as one. Nothing is rewritten: every statement is a verbatim slice of
the description, less the whitespace around it and any list marker in front.
"""

import re

_LIST_MARKER = re.compile(r"^\s*(?:[-*•]|\d{1,2}[.)])\s+")

_SENTENCE_END = re.compile(r"(?<=[.!?])[\"'”’)\]]*\s+(?=[\"'“‘(\[]?[A-Z0-9])")
"""A full stop, question mark or exclamation mark, then space, then something that starts a sentence."""

_ABBREVIATIONS = frozenset(
    {"e.g.", "i.e.", "etc.", "vs.", "dr.", "mr.", "mrs.", "ms.", "no.", "approx.", "inc.", "st.", "fig.", "ext."}
)
"""Words whose trailing full stop does not end a sentence."""

_INITIAL = re.compile(r"(?:^|\s)[A-Za-z]\.$")
"""A single letter and a full stop -- an initial, or a step label such as 'a.' -- which never ends one either."""


def split(description: str) -> list[str]:
    """Split a written description into statements.

    Args:
        description: The text as the user pasted it.

    Returns:
        The statements in reading order, each a verbatim slice of the input with
        surrounding whitespace and any leading list marker removed. Empty for
        text that holds nothing but whitespace.
    """
    statements = []
    for line in description.splitlines():
        text = _LIST_MARKER.sub("", line).strip()
        if text:
            statements.extend(_sentences(text))
    return statements


def _sentences(text: str) -> list[str]:
    """Divide one line at its sentence ends, leaving abbreviations and initials whole."""
    sentences = []
    start = 0
    for match in _SENTENCE_END.finditer(text):
        candidate = text[start : match.start()]
        last_word = candidate.rsplit(maxsplit=1)[-1].lower() if candidate.split() else ""
        if last_word in _ABBREVIATIONS or _INITIAL.search(candidate):
            continue
        sentences.append(candidate.strip())
        start = match.end()
    sentences.append(text[start:].strip())
    return [sentence for sentence in sentences if sentence]
