"""Subprocess wrapper for CubeLib binary invocations."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pycubetools.exceptions import CubeToolError

if TYPE_CHECKING:
    from pathlib import Path

    from pycubetools.config import CubeConfig

_TIMEOUT = 3600  # seconds — HPC jobs can be slow


@dataclass(frozen=True)
class RunResult:
    """Result of a successful tool invocation.

    Parameters
    ----------
    stdout:
        Captured standard output.
    stderr:
        Captured standard error.
    returncode:
        Process exit code (always 0 for a ``RunResult``).

    """

    stdout: str
    stderr: str
    returncode: int


class ToolRunner:
    """Run CubeLib binaries and return captured output.

    Parameters
    ----------
    config:
        Active :class:`~pycubetools.config.CubeConfig` used to locate
        binaries.

    """

    def __init__(self, config: CubeConfig) -> None:
        """Initialise with a CubeConfig."""
        self._config = config

    def run(
        self,
        tool: str,
        args: list[str],
        cwd: Path | None = None,
    ) -> RunResult:
        """Invoke *tool* with *args* and return the captured output.

        Parameters
        ----------
        tool:
            Binary name, e.g. ``"cube_stat"``.
        args:
            Additional command-line arguments.
        cwd:
            Working directory for the subprocess, or ``None`` to inherit.

        Returns
        -------
        RunResult
            Captured stdout, stderr, and return code.

        Raises
        ------
        CubeToolError
            When the binary exits with a non-zero return code.

        """
        binary = self._config.binary(tool)
        cmd = [str(binary), *args]
        result = subprocess.run(  # noqa: S603 — args are constructed, not shell-expanded
            cmd,
            capture_output=True,
            text=True,
            timeout=_TIMEOUT,
            cwd=cwd,
            check=False,
        )
        if result.returncode != 0:
            raise CubeToolError(
                tool=tool,
                returncode=result.returncode,
                stderr=result.stderr,
                cmd=cmd,
            )
        return RunResult(
            stdout=result.stdout,
            stderr=result.stderr,
            returncode=result.returncode,
        )
