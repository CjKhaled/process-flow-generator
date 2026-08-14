"""The hosted demo's backend: the pipeline behind an HTTP endpoint.

Stages 1 and 2 cannot run in a browser -- one needs an API key, the other shells
out to Node -- so the static page on GitHub Pages asks this service to run them.
Nothing here re-implements a stage: it composes the same functions the CLI
orchestrators in :mod:`pipelines` do, and writes nothing to disk.
"""
