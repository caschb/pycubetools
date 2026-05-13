"""Parsers converting CubeLib tool stdout into polars DataFrames."""

from __future__ import annotations

import io
import re

import polars as pl

from pycubetools.exceptions import CubeParseError

# Header prefixes that appear in cube_calltree stdout — skip these lines.
_CALLTREE_SKIP_PREFIXES = ("Reading ",)

# Callpath prefix patterns that terminate the name field in calltree output.
# Use \S.*? (at least one non-space after /, then any chars) so that callpaths
# containing spaces (e.g. OMP regions like "!$omp parallel @file:45") are
# captured correctly; \s*$ strips trailing whitespace.
_CALLPATH_RE = re.compile(r"\s+((?:USR|MPI|OMP|COM|EPK|SYS|REC):/\S.*?)\s*$")


def parse_stat(raw: str) -> pl.DataFrame:
    """Parse ``cube_stat -%`` CSV output into a DataFrame.

    Parameters
    ----------
    raw:
        Raw stdout from ``cube_stat -%``.

    Returns
    -------
    pl.DataFrame
        Columns: ``metric``, ``routine``, ``count``, ``sum``, ``mean``,
        ``variance``, ``minimum``, ``maximum``.

    Raises
    ------
    CubeParseError
        If the input cannot be parsed.

    """
    lines = [ln for ln in raw.splitlines() if ln.strip()]
    if not lines:
        raise CubeParseError(tool="cube_stat", raw=raw, reason="empty output")

    try:
        df = pl.read_csv(
            io.StringIO(raw),
            has_header=True,
            skip_rows_after_header=0,
            ignore_errors=True,
        )
    except Exception as exc:
        raise CubeParseError(tool="cube_stat", raw=raw, reason=str(exc)) from exc

    expected_cols = {
        "cube::Metric",
        "Routine",
        "Count",
        "Sum",
        "Mean",
        "Variance",
        "Minimum",
        "Maximum",
    }
    missing = expected_cols - set(df.columns)
    if missing:
        raise CubeParseError(
            tool="cube_stat",
            raw=raw,
            reason=f"missing columns: {missing}",
        )

    try:
        return df.select(
            [
                pl.col("cube::Metric").alias("metric"),
                pl.col("Routine").alias("routine"),
                pl.col("Count").cast(pl.Int64).alias("count"),
                pl.col("Sum").cast(pl.Float64).alias("sum"),
                pl.col("Mean").cast(pl.Float64).alias("mean"),
                pl.col("Variance").cast(pl.Float64).alias("variance"),
                pl.col("Minimum").cast(pl.Float64).alias("minimum"),
                pl.col("Maximum").cast(pl.Float64).alias("maximum"),
            ],
        ).filter(pl.col("metric").is_not_null())
    except Exception as exc:
        raise CubeParseError(tool="cube_stat", raw=raw, reason=str(exc)) from exc


def parse_info_basic(raw: str) -> dict[str, int | float]:
    """Parse ``cube_info -b`` output into a plain dict.

    Parameters
    ----------
    raw:
        Raw stdout from ``cube_info -b``.

    Returns
    -------
    dict
        Keys: ``nodes`` (int), ``processes`` (int), ``wallclock_time`` (float).

    Raises
    ------
    CubeParseError
        If the expected fields are not present.

    """
    result: dict[str, int | float] = {}
    for line in raw.splitlines():
        try:
            if "Number of nodes" in line:
                result["nodes"] = int(line.split(":")[-1].strip())
            elif "Number of processes" in line:
                result["processes"] = int(line.split(":")[-1].strip())
            elif "Wallclock time" in line:
                result["wallclock_time"] = float(line.split(":")[-1].strip())
        except ValueError as exc:
            raise CubeParseError(
                tool="cube_info", raw=raw, reason=f"malformed field: {exc}",
            ) from exc

    missing = {"nodes", "processes", "wallclock_time"} - result.keys()
    if missing:
        raise CubeParseError(
            tool="cube_info",
            raw=raw,
            reason=f"missing fields: {missing}",
        )
    return result


def parse_info_tree(raw: str) -> pl.DataFrame:
    """Parse ``cube_info -t`` (or ``-m metric``) output.

    Parameters
    ----------
    raw:
        Raw stdout from ``cube_info -t`` or ``cube_info -m <metric>``.

    Returns
    -------
    pl.DataFrame
        Columns: ``metric``, ``value``, ``cnode_id``, ``name``, ``depth``.

    Raises
    ------
    CubeParseError
        If the output cannot be parsed.

    """
    lines = raw.splitlines()
    if not lines:
        raise CubeParseError(tool="cube_info", raw=raw, reason="empty output")

    # First line is the header: "|    <MetricName> | Diff-Calltree"
    header = lines[0]
    parts = header.split("|")
    if len(parts) < 3:  # noqa: PLR2004
        raise CubeParseError(
            tool="cube_info", raw=raw, reason=f"unexpected header: {header!r}",
        )
    metric_name = parts[1].strip()

    cnode_ids: list[int] = []
    names: list[str] = []
    values: list[float] = []
    depths: list[int] = []
    cnode_id = 0

    for line in lines[1:]:
        if not line.strip():
            continue
        # Split on the first two `|` separators: "| value | tree_part"
        seg = line.split("|", 2)
        if len(seg) < 3:  # noqa: PLR2004
            continue
        raw_value = seg[1].strip()
        tree_part = seg[2]

        try:
            value = float(raw_value)
        except ValueError:
            continue

        # Count depth from number of `|` characters in the tree part before `*`
        star_pos = tree_part.find("*")
        if star_pos == -1:
            continue
        prefix = tree_part[:star_pos]
        depth = prefix.count("|")
        name = tree_part[star_pos + 1:].strip()

        cnode_ids.append(cnode_id)
        values.append(value)
        names.append(name)
        depths.append(depth)
        cnode_id += 1

    if not cnode_ids:
        raise CubeParseError(tool="cube_info", raw=raw, reason="no data rows parsed")

    return pl.DataFrame(
        {
            "metric": [metric_name] * len(cnode_ids),
            "value": values,
            "cnode_id": cnode_ids,
            "name": names,
            "depth": depths,
        },
    )


def parse_calltree(raw: str) -> pl.DataFrame:
    """Parse ``cube_calltree -a -c -p -m <metric>`` output.

    Parameters
    ----------
    raw:
        Raw stdout from ``cube_calltree``.

    Returns
    -------
    pl.DataFrame
        Columns: ``cnode_id``, ``name``, ``callpath``, ``value``,
        ``pct``, ``depth``.

    Raises
    ------
    CubeParseError
        If the output cannot be parsed.

    """
    # Pattern: <value> (<pct>%) ... <name> ... <callpath>
    row_re = re.compile(
        r"^(\S+)\s+\(([^)]+)%\)\s+(.+)$",
    )

    cnode_ids: list[int] = []
    names: list[str] = []
    callpaths: list[str] = []
    values: list[float] = []
    pcts: list[float] = []
    depths: list[int] = []
    cnode_id = 0

    for line in raw.splitlines():
        if any(line.startswith(p) for p in _CALLTREE_SKIP_PREFIXES):
            continue
        if not line.strip():
            continue
        m = row_re.match(line)
        if not m:
            continue

        raw_val, raw_pct, rest = m.group(1), m.group(2), m.group(3)
        try:
            value = float(raw_val)
            pct = float(raw_pct)
        except ValueError:
            continue

        # Extract callpath: it ends the line and starts with a known prefix
        cp_match = _CALLPATH_RE.search(rest)
        if cp_match:
            callpath = cp_match.group(1)
            middle = rest[: cp_match.start()]
        else:
            callpath = ""
            middle = rest

        # Depth from callpath: "USR:/a/b/c" → 2
        depth = max(0, callpath.count("/") - 1) if callpath else 0

        # Name: strip tree-drawing characters (|, +, spaces) from the middle
        name = re.sub(r"^[\s|+]*", "", middle).strip()

        cnode_ids.append(cnode_id)
        names.append(name)
        callpaths.append(callpath)
        values.append(value)
        pcts.append(pct)
        depths.append(depth)
        cnode_id += 1

    if not cnode_ids:
        raise CubeParseError(
            tool="cube_calltree", raw=raw, reason="no data rows parsed",
        )

    return pl.DataFrame(
        {
            "cnode_id": cnode_ids,
            "name": names,
            "callpath": callpaths,
            "value": values,
            "pct": pcts,
            "depth": depths,
        },
    )


def parse_dump(raw: str, fmt: str = "csv2") -> pl.DataFrame:  # noqa: ARG001
    """Parse ``cube_dump -s csv2`` output (wide) into long-format rows.

    Parameters
    ----------
    raw:
        Raw stdout from ``cube_dump -s csv2``.
    fmt:
        Format string (currently only ``"csv2"`` is supported).

    Returns
    -------
    pl.DataFrame
        Columns: ``cnode_id``, ``thread_id``, ``metric``, ``value``.

    Raises
    ------
    CubeParseError
        If the output cannot be parsed.

    """
    if not raw.strip():
        raise CubeParseError(tool="cube_dump", raw=raw, reason="empty output")

    try:
        # The csv2 format header is: "Cnode ID, Thread ID,metric1,metric2,..."
        # Note the space after the comma in "Cnode ID, Thread ID"
        df_wide = pl.read_csv(
            io.StringIO(raw),
            has_header=True,
        )
    except Exception as exc:
        raise CubeParseError(tool="cube_dump", raw=raw, reason=str(exc)) from exc

    # Normalise header names (strip spaces)
    df_wide = df_wide.rename({c: c.strip() for c in df_wide.columns})

    if "Cnode ID" not in df_wide.columns:
        raise CubeParseError(
            tool="cube_dump",
            raw=raw,
            reason="missing required 'Cnode ID' column",
        )

    has_thread_col = "Thread ID" in df_wide.columns
    id_cols = ["Cnode ID", "Thread ID"] if has_thread_col else ["Cnode ID"]
    metric_cols = [c for c in df_wide.columns if c not in id_cols]
    if not metric_cols:
        raise CubeParseError(
            tool="cube_dump", raw=raw, reason="no metric columns found",
        )

    # Melt wide → long
    df_long = df_wide.unpivot(
        on=metric_cols,
        index=id_cols,
        variable_name="metric",
        value_name="value",
    )

    df_long = df_long.rename({"Cnode ID": "cnode_id"})
    if has_thread_col:
        df_long = df_long.rename({"Thread ID": "thread_id"})
    else:
        # Aggregated mode: no per-thread breakdown; use -1 as sentinel
        df_long = df_long.with_columns(pl.lit(-1).alias("thread_id"))

    return df_long.select(["cnode_id", "thread_id", "metric", "value"])
