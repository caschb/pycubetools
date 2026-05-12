"""Public exception hierarchy for pycubetools."""

from __future__ import annotations


class CubeToolsError(Exception):
    """Base class for all pycubetools exceptions."""


class CubeConfigError(CubeToolsError):
    """Raised when a CubeLib binary cannot be located."""


class CubeToolError(CubeToolsError):
    """Raised when a CubeLib binary exits with a non-zero return code.

    Parameters
    ----------
    tool:
        Name of the binary that failed (e.g. ``"cube_stat"``).
    returncode:
        The process exit code.
    stderr:
        Captured standard error output.
    cmd:
        The full command that was executed.

    """

    def __init__(
        self,
        tool: str,
        returncode: int,
        stderr: str,
        cmd: list[str],
    ) -> None:
        """Store failure details and build the exception message."""
        self.tool = tool
        self.returncode = returncode
        self.stderr = stderr
        self.cmd = cmd
        super().__init__(str(self))

    def __str__(self) -> str:
        """Return a human-readable description of the failure."""
        cmd_str = " ".join(self.cmd)
        return (
            f"{self.tool} exited with code {self.returncode}\n"
            f"Command: {cmd_str}\n"
            f"Stderr:\n{self.stderr}"
        )


class CubeParseError(CubeToolsError):
    """Raised when tool stdout cannot be parsed into a DataFrame.

    Parameters
    ----------
    tool:
        Name of the tool whose output could not be parsed.
    raw:
        The unparsed output string.
    reason:
        A short description of why parsing failed.

    """

    def __init__(self, tool: str, raw: str, reason: str = "") -> None:
        """Store the unparsed output and build the exception message."""
        self.tool = tool
        self.raw = raw
        self.reason = reason
        msg = f"Failed to parse output of {tool}"
        if reason:
            msg += f": {reason}"
        super().__init__(msg)
