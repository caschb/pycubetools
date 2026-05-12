"""Output file lifecycle management for CubeLib operations."""

from __future__ import annotations

import tempfile
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Self

if TYPE_CHECKING:
    from types import TracebackType


class TempfileManager:
    """Manages a directory for intermediate ``.cubex`` output files.

    If *output_dir* is given the directory is used as-is (created if it does
    not yet exist) and is never deleted on cleanup.  When *output_dir* is
    ``None`` a temporary directory is created and removed on :meth:`cleanup`.

    Parameters
    ----------
    output_dir:
        Persistent directory to use, or ``None`` to use a temporary one.

    """

    def __init__(self, output_dir: Path | None) -> None:
        self._user_dir: Path | None = output_dir
        self._tmpdir: tempfile.TemporaryDirectory[str] | None = None

        if output_dir is not None:
            output_dir.mkdir(parents=True, exist_ok=True)
            self._dir = output_dir
        else:
            self._tmpdir = tempfile.TemporaryDirectory()
            self._dir = Path(self._tmpdir.name)

    @property
    def directory(self) -> Path:
        """Return the managed directory path."""
        return self._dir

    def next_path(self, suffix: str = ".cubex") -> Path:
        """Return a unique file path inside the managed directory.

        Parameters
        ----------
        suffix:
            File extension to use (default ``".cubex"``).

        Returns
        -------
        Path
            A path that does not yet exist inside the managed directory.

        """
        return self._dir / (uuid.uuid4().hex + suffix)

    def cleanup(self) -> None:
        """Remove the temporary directory, if one was created.

        No-op when *output_dir* was supplied by the caller.
        """
        if self._tmpdir is not None:
            self._tmpdir.cleanup()
            self._tmpdir = None

    def __enter__(self) -> Self:
        """Enter the context manager."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Exit the context manager and clean up."""
        self.cleanup()
