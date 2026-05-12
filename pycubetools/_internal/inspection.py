"""CubeLib inspection operations: calltree, stat, dump, info_tree, info_basic."""

from __future__ import annotations

import io
from typing import TYPE_CHECKING

import polars as pl

from pycubetools._internal.parsers import (
    parse_calltree,
    parse_dump,
    parse_info_basic,
    parse_info_tree,
    parse_stat,
)
from pycubetools.exceptions import CubeParseError

if TYPE_CHECKING:
    from pathlib import Path

    from pycubetools._internal.runner import ToolRunner


def calltree(
    path: Path,
    metric: str,
    threshold: float,
    inclusive: bool,
    runner: ToolRunner,
) -> pl.DataFrame:
    """Invoke ``cube_calltree`` and return its output as a DataFrame.

    Parameters
    ----------
    path:
        Path to the ``.cubex`` file.
    metric:
        Metric name passed to ``-m``.
    threshold:
        Minimum percentage threshold (``-t``); 0.0 means no filtering.
    inclusive:
        When ``True`` compute inclusive values (``-i`` flag).
    runner:
        The :class:`~pycubetools._internal.runner.ToolRunner` to use.

    Returns
    -------
    pl.DataFrame
        Columns: ``cnode_id``, ``name``, ``callpath``, ``value``,
        ``pct``, ``depth``.

    """
    args: list[str] = ["-a", "-c", "-p", "-m", metric, "-t", str(threshold)]
    if inclusive:
        args.append("-i")
    args.append(str(path))
    result = runner.run("cube_calltree", args)
    return parse_calltree(result.stdout)


def stat(
    path: Path,
    metrics: tuple[str, ...],
    routines: tuple[str, ...] | None,
    top_n: int | None,
    per_thread: bool,  # noqa: ARG001 — reserved for future flag selection
    runner: ToolRunner,
) -> pl.DataFrame:
    """Invoke ``cube_stat`` and return per-routine statistics as a DataFrame.

    Parameters
    ----------
    path:
        Path to the ``.cubex`` file.
    metrics:
        Metric names to request (mapped to ``-m m1,m2,...``).
    routines:
        Routine names to filter (mapped to ``-r r1,r2,...``); ``None``
        means all routines.
    top_n:
        When set, return only the top *N* routines by exclusive time
        (``-t N`` flag); overrides *routines*.
    per_thread:
        Ignored — ``cube_stat -%`` is always used so that the full
        statistical breakdown is returned.
    runner:
        The :class:`~pycubetools._internal.runner.ToolRunner` to use.

    Returns
    -------
    pl.DataFrame
        Columns: ``metric``, ``routine``, ``count``, ``sum``, ``mean``,
        ``variance``, ``minimum``, ``maximum``.

    """
    if top_n is not None:
        args: list[str] = ["-t", str(top_n), str(path)]
        result = runner.run("cube_stat", args)
        return _parse_topn(result.stdout)

    args = ["-%", "-m", ",".join(metrics)]
    if routines:
        args.extend(["-r", ",".join(routines)])
    args.append(str(path))
    result = runner.run("cube_stat", args)
    return parse_stat(result.stdout)


def dump(
    path: Path,
    metrics: tuple[str, ...],
    cnodes: str,
    threads: str,
    z: str,
    runner: ToolRunner,
) -> pl.DataFrame:
    """Invoke ``cube_dump -s csv2`` and return a long-format DataFrame.

    Parameters
    ----------
    path:
        Path to the ``.cubex`` file.
    metrics:
        Metric names (``-m m1,m2,...``).
    cnodes:
        Cnode selection string (``-c``), e.g. ``"all"`` or ``"0,1,5-10"``.
    threads:
        Thread selection string (``-t``), e.g. ``"aggr"`` or ``"0"``.
    z:
        Calltree value mode (``-z``): ``"incl"`` or ``"excl"``.
    runner:
        The :class:`~pycubetools._internal.runner.ToolRunner` to use.

    Returns
    -------
    pl.DataFrame
        Columns: ``cnode_id``, ``thread_id``, ``metric``, ``value``.

    """
    args = [
        "-s", "csv2",
        "-m", ",".join(metrics),
        "-c", cnodes,
        "-t", threads,
        "-z", z,
        str(path),
    ]
    result = runner.run("cube_dump", args)
    return parse_dump(result.stdout)


def info_tree(
    path: Path,
    metric: str,
    runner: ToolRunner,
) -> pl.DataFrame:
    """Invoke ``cube_info -m <metric>`` and return the calltree as a DataFrame.

    Parameters
    ----------
    path:
        Path to the ``.cubex`` file.
    metric:
        Metric name to display (``-m``).
    runner:
        The :class:`~pycubetools._internal.runner.ToolRunner` to use.

    Returns
    -------
    pl.DataFrame
        Columns: ``metric``, ``value``, ``cnode_id``, ``name``, ``depth``.

    """
    result = runner.run("cube_info", ["-m", metric, str(path)])
    return parse_info_tree(result.stdout)


def info_basic(
    path: Path,
    runner: ToolRunner,
) -> dict[str, int | float]:
    """Invoke ``cube_info -b`` and return basic experiment metadata.

    Parameters
    ----------
    path:
        Path to the ``.cubex`` file.
    runner:
        The :class:`~pycubetools._internal.runner.ToolRunner` to use.

    Returns
    -------
    dict
        Keys: ``nodes`` (int), ``processes`` (int),
        ``wallclock_time`` (float).

    """
    result = runner.run("cube_info", ["-b", str(path)])
    return parse_info_basic(result.stdout)


def _parse_topn(raw: str) -> pl.DataFrame:
    """Parse ``cube_stat -t N`` flat-profile CSV into the standard schema.

    The flat-profile format differs from ``-%``: columns are
    ``cube::Region``, ``Number of Calls``, ``Exclusive Time``,
    ``Inclusive Time``.  We return a DataFrame with the same columns as
    :func:`~pycubetools._internal.parsers.parse_stat`, filling missing
    statistical columns with ``null``.

    Parameters
    ----------
    raw:
        Raw stdout from ``cube_stat -t N``.

    Returns
    -------
    pl.DataFrame
        Columns: ``metric``, ``routine``, ``count``, ``sum``, ``mean``,
        ``variance``, ``minimum``, ``maximum``.

    """
    try:
        df = pl.read_csv(io.StringIO(raw), has_header=True)
    except Exception as exc:
        raise CubeParseError(tool="cube_stat", raw=raw, reason=str(exc)) from exc

    required = {"cube::Region", "Number of Calls", "Exclusive Time"}
    missing = required - set(df.columns)
    if missing:
        raise CubeParseError(
            tool="cube_stat",
            raw=raw,
            reason=f"unexpected flat-profile columns: missing {missing}",
        )

    return df.select(
        [
            pl.lit("time").alias("metric"),
            pl.col("cube::Region").alias("routine"),
            pl.col("Number of Calls").cast(pl.Int64).alias("count"),
            pl.col("Exclusive Time").cast(pl.Float64).alias("sum"),
            pl.lit(None).cast(pl.Float64).alias("mean"),
            pl.lit(None).cast(pl.Float64).alias("variance"),
            pl.lit(None).cast(pl.Float64).alias("minimum"),
            pl.lit(None).cast(pl.Float64).alias("maximum"),
        ],
    )
