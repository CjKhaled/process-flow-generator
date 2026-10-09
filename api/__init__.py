"""The service: the conversation behind HTTP, and the page that holds it.

Nothing here re-implements a step. Every turn is :func:`session.orchestrator.run_turn`
and every close-out is :func:`session.closeout.finalise`, the same calls the
terminal chat makes.
"""
