"""CubeLib algebra operations: diff, merge, mean, cmp."""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from pycubetools._internal.runner import ToolRunner


class SystemDimension(enum.Enum):
    """How to handle mismatched system dimensions in algebra operations.

    Attributes
    ----------
    KEEP:
        Raise an error on mismatch (default, no extra flag).
    REDUCE:
        Aggregate threads within processes (``-c`` flag).
    COLLAPSE:
        Collapse the entire system tree (``-C`` flag).

    """

    KEEP = "keep"
    REDUCE = "reduce"
    COLLAPSE = "collapse"


@dataclass(frozen=True)
class CompareResult:
    """Result of a ``cube_cmp`` comparison.

    Attributes
    ----------
    equal:
        ``True`` if the two experiments are considered equal.
    details:
        Full stdout from ``cube_cmp``.

    """

    equal: bool
    details: str


def _system_dim_flag(dim: SystemDimension) -> list[str]:
    """Return the command-line flag list for *dim* (empty for KEEP)."""
    if dim is SystemDimension.REDUCE:
        return ["-c"]
    if dim is SystemDimension.COLLAPSE:
        return ["-C"]
    return []


def diff(
    minuend: Path,
    subtrahend: Path,
    output_path: Path,
    system_dim: SystemDimension,
    runner: ToolRunner,
) -> Path:
    """Compute the difference of two ``.cubex`` files.

    Parameters
    ----------
    minuend:
        Path to the file to subtract from.
    subtrahend:
        Path to the file to subtract.
    output_path:
        Destination for the result ``.cubex`` file.
    system_dim:
        How to handle system-dimension mismatches.
    runner:
        The :class:`~pycubetools._internal.runner.ToolRunner` to use.

    Returns
    -------
    Path
        *output_path* on success.

    """
    args = [
        *_system_dim_flag(system_dim),
        "-o",
        str(output_path),
        str(minuend),
        str(subtrahend),
    ]
    runner.run("cube_diff", args)
    return output_path


def merge(
    inputs: list[Path],
    output_path: Path,
    system_dim: SystemDimension,
    runner: ToolRunner,
) -> Path:
    """Merge two or more ``.cubex`` files into one.

    Parameters
    ----------
    inputs:
        Paths to the files to merge (at least two).
    output_path:
        Destination for the result ``.cubex`` file.
    system_dim:
        How to handle system-dimension mismatches.
    runner:
        The :class:`~pycubetools._internal.runner.ToolRunner` to use.

    Returns
    -------
    Path
        *output_path* on success.

    """
    args = [
        *_system_dim_flag(system_dim),
        "-o",
        str(output_path),
        *[str(p) for p in inputs],
    ]
    runner.run("cube_merge", args)
    return output_path


def mean(
    inputs: list[Path],
    output_path: Path,
    system_dim: SystemDimension,
    runner: ToolRunner,
) -> Path:
    """Compute the mean of two or more ``.cubex`` files.

    Parameters
    ----------
    inputs:
        Paths to the files to average (at least two).
    output_path:
        Destination for the result ``.cubex`` file.
    system_dim:
        How to handle system-dimension mismatches.
    runner:
        The :class:`~pycubetools._internal.runner.ToolRunner` to use.

    Returns
    -------
    Path
        *output_path* on success.

    """
    args = [
        *_system_dim_flag(system_dim),
        "-o",
        str(output_path),
        *[str(p) for p in inputs],
    ]
    runner.run("cube_mean", args)
    return output_path


def cmp(
    a: Path,
    b: Path,
    runner: ToolRunner,
) -> CompareResult:
    """Compare two ``.cubex`` files and return whether they are equal.

    Parameters
    ----------
    a:
        Path to the first experiment.
    b:
        Path to the second experiment.
    runner:
        The :class:`~pycubetools._internal.runner.ToolRunner` to use.

    Returns
    -------
    CompareResult
        ``equal=True`` when ``cube_cmp`` exits zero and its stdout
        contains no difference indicators.

    """
    result = runner.run("cube_cmp", [str(a), str(b)])
    # cube_cmp exits 0 whether equal or not; check stdout for "differ"
    equal = "differ" not in result.stdout.lower()
    return CompareResult(equal=equal, details=result.stdout)
