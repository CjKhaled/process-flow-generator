# The hosted demo's service. Python and Node in one image, because a run is both
# stages: the extractor is Python and the layouter is a pinned Node CLI that
# stage 2 shells out to. An image without Node would start, answer /health, and
# fail every run at the point it tried to draw something.
FROM python:3.12-slim

# Node from the official image rather than a distro package: the layouter is
# pinned to an exact pre-release and is the one thing here that must not drift.
COPY --from=node:22-slim /usr/local/bin/node /usr/local/bin/node
COPY --from=node:22-slim /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Dependencies first, so a code change does not reinstall the world.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --group api

COPY js/package.json js/package-lock.json ./js/
RUN npm ci --prefix js

COPY . .

ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1

# A same-origin copy of the page, served at /. GitHub Pages hosts the copy that
# people are given the link to; this one costs nothing to build, needs no CORS,
# and is the answer when Pages is unavailable or misconfigured.
RUN python -m pipelines.site --api-base ""

# Render supplies the port. The default matches its own so `docker run` locally
# behaves the same way.
ENV PORT=10000
EXPOSE 10000
CMD ["sh", "-c", "uvicorn api.app:app --host 0.0.0.0 --port ${PORT}"]
