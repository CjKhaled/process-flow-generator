"""Where sessions are kept.

A session is one JSON file, and that file is the single source of truth: no agent
holds state of its own, so loading the file is all it takes to carry a
conversation on in a process that has never seen it. This is the "stateless
service plus persisted session" shape, with the persistence written here rather
than borrowed from an agent framework's session manager -- there is no paused
agent to restore, only a record of what was said and what was made of it.

:class:`SessionStore` is a protocol, and small on purpose: an object store
implementation comes later and should have five methods to write, not fifteen.

Writes are atomic. A turn's result goes to a temporary file in the same folder,
which is then renamed over the old one, so a reader -- the page polls while a
turn runs -- sees the session before the turn or after it and never half of one.
"""

import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Protocol

from session.models import Session

SESSION_FILENAME = "session.json"
FLOWS_DIRNAME = "flows"

_SAFE_NAME = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
"""What a session id or a flow name may look like.

Both become folder names, and both arrive from a URL. Anything else is refused
before a path is ever built from it.
"""


class SessionNotFound(KeyError):
    """There is no session with that id."""


class SessionStore(Protocol):
    """Keeps sessions, and says where a session's finished flows go."""

    def create(self, session: Session) -> None:
        """Store a new session.

        Raises:
            FileExistsError: If one with that id is already stored.
        """
        ...

    def load(self, session_id: str) -> Session:
        """Read a session.

        Raises:
            SessionNotFound: If there is none with that id.
        """
        ...

    def save(self, session: Session) -> None:
        """Replace a stored session with this one, atomically."""
        ...

    def list(self) -> tuple[str, ...]:
        """The ids of every stored session, in sorted order."""
        ...

    def path_for_outputs(self, session_id: str, flow: str) -> Path:
        """The folder one of a session's finished flows is written to.

        Raises:
            ValueError: If either name is not safe to use as a folder name.
        """
        ...


class FileSessionStore:
    """Sessions as folders on disk: ``<root>/<id>/session.json``.

    Close-out writes beside it, under ``<root>/<id>/flows/<flow>/``, in the
    layout stages 2 and 3 already read.
    """

    def __init__(self, root: Path) -> None:
        """
        Args:
            root: The directory holding one folder per session. Created on first
                write, so pointing at a directory that does not exist yet is fine.
        """
        self._root = root

    def create(self, session: Session) -> None:
        """Store a new session.

        Raises:
            FileExistsError: If one with that id is already stored.
            ValueError: If the id is not safe to use as a folder name.
        """
        path = self._path(session.id)
        if path.exists():
            raise FileExistsError(f"session '{session.id}' already exists")
        self.save(session)

    def load(self, session_id: str) -> Session:
        """Read a session.

        Raises:
            SessionNotFound: If there is none with that id, including an id that
                could not be a session's.
            pydantic.ValidationError: If the file does not match the schema.
        """
        try:
            path = self._path(session_id)
        except ValueError:
            raise SessionNotFound(session_id) from None
        if not path.is_file():
            raise SessionNotFound(session_id)
        return Session.model_validate_json(path.read_text(encoding="utf-8"))

    def save(self, session: Session) -> None:
        """Write the session to a temporary file, then rename it into place.

        Raises:
            ValueError: If the id is not safe to use as a folder name.
        """
        path = self._path(session.id)
        path.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary = tempfile.mkstemp(dir=path.parent, prefix=".session-", suffix=".tmp")
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as file:
                file.write(session.model_dump_json(indent=2))
                file.write("\n")
            # Same directory, so this is a rename and not a copy: atomic on POSIX and Windows.
            os.replace(temporary, path)
        except BaseException:
            Path(temporary).unlink(missing_ok=True)
            raise

    def list(self) -> tuple[str, ...]:
        """The ids of every stored session, in sorted order."""
        if not self._root.is_dir():
            return ()
        return tuple(sorted(path.parent.name for path in self._root.glob(f"*/{SESSION_FILENAME}")))

    def path_for_outputs(self, session_id: str, flow: str) -> Path:
        """The folder one of a session's finished flows is written to.

        Raises:
            ValueError: If either name is not safe to use as a folder name.
        """
        return self._folder(session_id) / FLOWS_DIRNAME / _safe(flow, "flow name")

    def restore_seeds(self, seeds_dir: Path) -> tuple[str, ...]:
        """Copy in every seed session this store does not already hold.

        A host whose disk does not outlive a restart starts every boot with no
        sessions at all. Seeds are sessions committed beside the code -- a
        session file and its finished flows -- and this puts each one back.

        Only where it is missing. A session already in the store is never
        overwritten, so on a machine that keeps its disk a seed is restored once
        and then belongs to whoever carries it on. The other side of that: on a
        host that does lose its disk, whatever was done to a seeded session
        there is gone at the next restart, and the committed copy returns.

        Args:
            seeds_dir: A folder laid out like the store itself. Missing is fine.

        Returns:
            The ids restored, in sorted order.
        """
        if not seeds_dir.is_dir():
            return ()
        restored = []
        for seed in sorted(path.parent for path in seeds_dir.glob(f"*/{SESSION_FILENAME}")):
            if not _SAFE_NAME.fullmatch(seed.name) or (self._root / seed.name).exists():
                continue
            self._root.mkdir(parents=True, exist_ok=True)
            shutil.copytree(seed, self._root / seed.name)
            restored.append(seed.name)
        return tuple(restored)

    def _folder(self, session_id: str) -> Path:
        return self._root / _safe(session_id, "session id")

    def _path(self, session_id: str) -> Path:
        return self._folder(session_id) / SESSION_FILENAME


def _safe(name: str, what: str) -> str:
    if not _SAFE_NAME.fullmatch(name):
        raise ValueError(f"'{name}' is not a valid {what}")
    return name
