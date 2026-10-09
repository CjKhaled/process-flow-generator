"""The checks only a conversation can make: evidence, lanes, scopes, origin."""

from ir.models import NodeOrigin, NodeStatus, NodeType, ProcessGraph
from knowledge.loader import DomainKnowledge
from session.models import SessionLane, Statement, StatementOrigin
from session.patch import GraphPatch, RemoveEdge, RemoveNode
from tests.builders import branch, codes, edge, graph, node, ref
from validators.report import FindingCode, Severity
from validators.session_checks import check_removal_reasons, normalise, quote_found, validate_session

LANES = (SessionLane(name="HCP"), SessionLane(name="Vendor"))


def statement(statement_id: str, text: str, restatement: str | None = None) -> Statement:
    return Statement(id=statement_id, origin=StatementOrigin.ANSWER, turn=2, raw_text=text, restatement=restatement)


CORPUS = (
    statement("s_0001", "The HCP faxes the form to the vendor."),
    statement("s_0002", "If it’s complete, the patient is enrolled."),
    statement("s_0003", "Yeah, a link.", restatement="Consent is captured by sending a link."),
)


def sound() -> ProcessGraph:
    """A graph in which everything is cited, laned and correctly marked."""
    return graph(
        nodes=(
            node("start", NodeType.START, actor="HCP", evidence=(ref("s_0001", "The HCP faxes the form"),)),
            node("gw", NodeType.GATEWAY, actor="Vendor", evidence=(ref("s_0002", "If it's complete"),)),
            node(
                "end_enrolled", NodeType.TERMINAL, actor="Vendor", evidence=(ref("s_0002", "the patient is enrolled"),)
            ),
            node(
                "end_open",
                NodeType.TERMINAL,
                actor="Vendor",
                status=NodeStatus.NEEDS_CLARIFICATION,
                detail="What happens to an incomplete form is not stated.",
                origin=NodeOrigin.RULE,
            ),
        ),
        edges=(
            edge("start", "gw"),
            branch("gw", "end_enrolled", "it is complete", 0, evidence=(ref("s_0002", "If it's complete"),)),
            branch("gw", "end_open", "it is not complete", 1),
        ),
    )


def check(process_graph: ProcessGraph, domain: DomainKnowledge) -> frozenset[FindingCode]:
    return codes(validate_session(process_graph, CORPUS, LANES, domain.process))


def swap(process_graph: ProcessGraph, node_id: str, **update: object) -> ProcessGraph:
    return process_graph.model_copy(
        update={"nodes": tuple(n.model_copy(update=update) if n.id == node_id else n for n in process_graph.nodes)}
    )


def test_a_sound_graph_raises_nothing(domain: DomainKnowledge) -> None:
    assert validate_session(sound(), CORPUS, LANES, domain.process).findings == ()


def test_every_session_finding_is_structural(domain: DomainKnowledge) -> None:
    """Each is a mechanical defect the model can fix from the complaint, so each earns a repair turn."""
    broken = swap(swap(sound(), "start", evidence=(), actor="Nobody"), "gw", subprocess="made_up")

    report = validate_session(broken, CORPUS, LANES, domain.process)

    assert report.findings and all(finding.severity is Severity.STRUCTURAL for finding in report.findings)


def test_a_source_node_with_no_evidence_is_rejected(domain: DomainKnowledge) -> None:
    assert check(swap(sound(), "start", evidence=()), domain) == {FindingCode.MISSING_EVIDENCE}


def test_a_branch_with_no_evidence_is_rejected(domain: DomainKnowledge) -> None:
    stripped = sound().model_copy(update={"edges": tuple(e.model_copy(update={"evidence": ()}) for e in sound().edges)})

    report = validate_session(stripped, CORPUS, LANES, domain.process)

    assert [finding.node_ids for finding in report.findings] == [("gw", "end_enrolled")]


def test_the_branch_to_a_rule_terminal_needs_no_evidence(domain: DomainKnowledge) -> None:
    """Nobody stated that outcome, so there is nothing to quote. That is what the terminal says."""
    assert FindingCode.MISSING_EVIDENCE not in check(sound(), domain)


def test_a_reference_to_a_statement_that_does_not_exist_is_rejected(domain: DomainKnowledge) -> None:
    assert check(swap(sound(), "start", evidence=(ref("s_0099", "The HCP faxes"),)), domain) == {
        FindingCode.EVIDENCE_NOT_FOUND
    }


def test_a_quote_that_is_not_in_its_statement_is_rejected(domain: DomainKnowledge) -> None:
    """The check that makes extraction literal: a paraphrase is not a quote."""
    paraphrased = swap(sound(), "start", evidence=(ref("s_0001", "The prescriber sends the form by fax"),))

    report = validate_session(paraphrased, CORPUS, LANES, domain.process)

    assert codes(report) == {FindingCode.EVIDENCE_NOT_FOUND}
    assert "s_0001" in report.findings[0].message


def test_a_quote_from_another_statement_is_rejected(domain: DomainKnowledge) -> None:
    assert check(swap(sound(), "start", evidence=(ref("s_0001", "the patient is enrolled"),)), domain) == {
        FindingCode.EVIDENCE_NOT_FOUND
    }


def test_an_edge_quote_is_checked_too(domain: DomainKnowledge) -> None:
    wrong = sound().model_copy(
        update={
            "edges": (
                sound().edges[0],
                sound().edges[1].model_copy(update={"evidence": (ref("s_0002", "when it is finished"),)}),
                sound().edges[2],
            )
        }
    )

    assert check(wrong, domain) == {FindingCode.EVIDENCE_NOT_FOUND}


def test_quotes_are_compared_without_regard_to_case_spacing_or_typography() -> None:
    """Straightening a curly apostrophe is not inventing anything."""
    assert quote_found("if it's   COMPLETE", CORPUS[1])
    assert normalise("  A  “quoted”\n word — here ") == 'a "quoted" word - here'


def test_a_quote_may_come_from_the_restatement() -> None:
    assert quote_found("Consent is captured by sending a link", CORPUS[2])
    assert quote_found("a link", CORPUS[2])
    assert not quote_found("an e-sign link", CORPUS[2])


def test_a_node_in_a_lane_the_session_has_not_learned_is_rejected(domain: DomainKnowledge) -> None:
    report = validate_session(swap(sound(), "gw", actor="CM360"), CORPUS, LANES, domain.process)

    assert codes(report) == {FindingCode.UNKNOWN_LANE}
    assert "HCP, Vendor" in report.findings[0].message


def test_a_subprocess_the_process_does_not_declare_is_rejected(domain: DomainKnowledge) -> None:
    assert check(swap(sound(), "gw", subprocess="onboarding"), domain) == {FindingCode.UNKNOWN_SCOPE}
    assert check(swap(sound(), "gw", subprocess="off_label_review"), domain) == set()


def test_a_rule_node_that_is_not_an_open_terminal_is_rejected(domain: DomainKnowledge) -> None:
    as_task = swap(sound(), "gw", origin=NodeOrigin.RULE, evidence=())
    as_stated_terminal = swap(sound(), "end_open", status=NodeStatus.STATED)

    assert FindingCode.RULE_ORIGIN_MISUSE in check(as_task, domain)
    assert FindingCode.RULE_ORIGIN_MISUSE in check(as_stated_terminal, domain)


def test_slice_origin_is_reserved_for_code(domain: DomainKnowledge) -> None:
    assert check(swap(sound(), "end_enrolled", origin=NodeOrigin.SLICE), domain) == {FindingCode.RULE_ORIGIN_MISUSE}


def test_a_removal_must_cite_a_statement_that_exists() -> None:
    patch = GraphPatch(
        operations=(
            RemoveNode(op="remove_node", id="gw", reason_statement_ids=("s_0002",)),
            RemoveNode(op="remove_node", id="start", reason_statement_ids=("s_0404",)),
            RemoveEdge(op="remove_edge", from_id="a", to_id="b", order=0, reason_statement_ids=("s_0405",)),
        )
    )

    findings = list(check_removal_reasons(patch, CORPUS))

    assert [finding.code for finding in findings] == [FindingCode.EVIDENCE_NOT_FOUND] * 2
    assert "s_0404" in findings[0].message and "s_0405" in findings[1].message
