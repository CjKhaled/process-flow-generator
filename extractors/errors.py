"""How a model call can fail.

Kept free of any Strands import so the agents and their loops can be exercised
without the SDK. The Strands adapter in :mod:`extractors.model` translates SDK
exceptions into these two, and the difference between them is the whole retry
policy: one is worth asking again about, the other is not.
"""


class SchemaCallError(Exception):
    """The model produced something that does not fit the schema.

    A mechanical defect: the model can see the complaint and fix it, so the loop
    retries. Distinct from ambiguity in the source, which is never retried.
    """


class ModelUnavailableError(Exception):
    """The API rejected the request outright -- bad model id, bad key, quota.

    Deliberately not a :class:`SchemaCallError`: the retry loop must not re-prompt
    its way through an authentication failure or a typo in a model id.
    """
