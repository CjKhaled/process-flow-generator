"""BPMN 2.0 rendering: a graph and a layout in, a ``.bpmn`` document out.

Split in two because the questions are independent. :mod:`bpmn.semantics`
answers *what each thing is* -- which IR node becomes a start event, which lane
owns it, which way an association points -- and needs no coordinates at all.
:mod:`bpmn.document` answers *how it is written down*, and is the only place
that knows what XML looks like.
"""
