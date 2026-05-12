"""Unit tests for pycubetools._internal.parsers using fixture strings."""

from __future__ import annotations

from pathlib import Path

import pytest

from pycubetools._internal.parsers import (
    parse_calltree,
    parse_dump,
    parse_info_basic,
    parse_info_tree,
    parse_stat,
)
from pycubetools.exceptions import CubeParseError

FIXTURES = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# parse_stat
# ---------------------------------------------------------------------------


class TestParseStat:
    """Tests for parse_stat."""

    @pytest.fixture
    def raw(self) -> str:
        """Return fixture text for cube_stat -%."""
        return (FIXTURES / "stat_percent.txt").read_text()

    def test_columns(self, raw: str) -> None:
        df = parse_stat(raw)
        assert df.columns == [
            "metric",
            "routine",
            "count",
            "sum",
            "mean",
            "variance",
            "minimum",
            "maximum",
        ]

    def test_has_rows(self, raw: str) -> None:
        df = parse_stat(raw)
        assert len(df) > 0

    def test_metric_column_not_null(self, raw: str) -> None:
        df = parse_stat(raw)
        assert df["metric"].null_count() == 0

    def test_count_column_dtype(self, raw: str) -> None:
        import polars as pl

        df = parse_stat(raw)
        assert df["count"].dtype == pl.Int64

    def test_sum_column_positive(self, raw: str) -> None:
        df = parse_stat(raw)
        assert (df["sum"] >= 0).all()

    def test_empty_raises(self) -> None:
        with pytest.raises(CubeParseError, match="cube_stat"):
            parse_stat("")

    def test_missing_columns_raises(self) -> None:
        with pytest.raises(CubeParseError, match="missing columns"):
            parse_stat("just,two,cols\n1,2,3\n")


# ---------------------------------------------------------------------------
# parse_info_basic
# ---------------------------------------------------------------------------


class TestParseInfoBasic:
    """Tests for parse_info_basic."""

    @pytest.fixture
    def raw(self) -> str:
        """Return fixture text for cube_info -b."""
        return (FIXTURES / "info_basic.txt").read_text()

    def test_keys(self, raw: str) -> None:
        d = parse_info_basic(raw)
        assert set(d.keys()) == {"nodes", "processes", "wallclock_time"}

    def test_nodes_is_int(self, raw: str) -> None:
        d = parse_info_basic(raw)
        assert isinstance(d["nodes"], int)

    def test_processes_is_int(self, raw: str) -> None:
        d = parse_info_basic(raw)
        assert isinstance(d["processes"], int)

    def test_wallclock_is_float(self, raw: str) -> None:
        d = parse_info_basic(raw)
        assert isinstance(d["wallclock_time"], float)

    def test_known_values(self, raw: str) -> None:
        d = parse_info_basic(raw)
        assert d["processes"] == 16
        assert d["wallclock_time"] == pytest.approx(49.6184, rel=1e-4)

    def test_missing_field_raises(self) -> None:
        with pytest.raises(CubeParseError, match="missing fields"):
            parse_info_basic("Wallclock time     : 1.0\n")

    def test_empty_raises(self) -> None:
        with pytest.raises(CubeParseError):
            parse_info_basic("")


# ---------------------------------------------------------------------------
# parse_info_tree
# ---------------------------------------------------------------------------


class TestParseInfoTree:
    """Tests for parse_info_tree."""

    @pytest.fixture
    def raw(self) -> str:
        """Return fixture text for cube_info -t."""
        return (FIXTURES / "info_tree.txt").read_text()

    def test_columns(self, raw: str) -> None:
        df = parse_info_tree(raw)
        assert df.columns == ["metric", "value", "cnode_id", "name", "depth"]

    def test_has_rows(self, raw: str) -> None:
        df = parse_info_tree(raw)
        assert len(df) > 0

    def test_cnode_ids_sequential(self, raw: str) -> None:
        df = parse_info_tree(raw)
        assert list(df["cnode_id"]) == list(range(len(df)))

    def test_root_at_depth_zero(self, raw: str) -> None:
        df = parse_info_tree(raw)
        assert df["depth"][0] == 0

    def test_depth_increases(self, raw: str) -> None:
        df = parse_info_tree(raw)
        # Second row (first child) is deeper than root
        assert df["depth"][1] >= 1

    def test_metric_consistent(self, raw: str) -> None:
        df = parse_info_tree(raw)
        assert df["metric"].n_unique() == 1

    def test_empty_raises(self) -> None:
        with pytest.raises(CubeParseError):
            parse_info_tree("")

    def test_bad_header_raises(self) -> None:
        with pytest.raises(CubeParseError, match="unexpected header"):
            parse_info_tree("no pipe separators here\n")


# ---------------------------------------------------------------------------
# parse_calltree
# ---------------------------------------------------------------------------


class TestParseCalltree:
    """Tests for parse_calltree."""

    @pytest.fixture
    def raw(self) -> str:
        """Return fixture text for cube_calltree -a -c -p."""
        return (FIXTURES / "calltree.txt").read_text()

    def test_columns(self, raw: str) -> None:
        df = parse_calltree(raw)
        assert df.columns == [
            "cnode_id",
            "name",
            "callpath",
            "value",
            "pct",
            "depth",
        ]

    def test_has_rows(self, raw: str) -> None:
        df = parse_calltree(raw)
        assert len(df) > 0

    def test_cnode_ids_sequential(self, raw: str) -> None:
        df = parse_calltree(raw)
        assert list(df["cnode_id"]) == list(range(len(df)))

    def test_root_depth_zero(self, raw: str) -> None:
        df = parse_calltree(raw)
        assert df["depth"][0] == 0

    def test_callpath_starts_with_prefix(self, raw: str) -> None:
        df = parse_calltree(raw)
        first = df["callpath"][0]
        assert first.startswith(("USR:", "MPI:"))

    def test_values_positive(self, raw: str) -> None:
        df = parse_calltree(raw)
        assert (df["value"] >= 0).all()

    def test_pcts_in_range(self, raw: str) -> None:
        df = parse_calltree(raw)
        assert (df["pct"] >= 0).all()

    def test_empty_raises(self) -> None:
        with pytest.raises(CubeParseError):
            parse_calltree("")

    def test_reading_line_skipped(self, raw: str) -> None:
        """The 'Reading ...' header line must not appear as a data row."""
        df = parse_calltree(raw)
        assert not any("Reading" in name for name in df["name"].to_list())


# ---------------------------------------------------------------------------
# parse_dump
# ---------------------------------------------------------------------------


class TestParseDump:
    """Tests for parse_dump."""

    @pytest.fixture
    def raw(self) -> str:
        """Return fixture text for cube_dump -s csv2 (per-thread mode)."""
        return (FIXTURES / "dump_csv2.txt").read_text()

    @pytest.fixture
    def raw_aggr(self) -> str:
        """Return aggregated-mode fixture (no Thread ID column)."""
        return "Cnode ID,time\n0,1.23\n1,4.56\n"

    def test_columns(self, raw: str) -> None:
        df = parse_dump(raw)
        assert df.columns == ["cnode_id", "thread_id", "metric", "value"]

    def test_has_rows(self, raw: str) -> None:
        df = parse_dump(raw)
        assert len(df) > 0

    def test_metric_column_not_null(self, raw: str) -> None:
        df = parse_dump(raw)
        assert df["metric"].null_count() == 0

    def test_aggr_mode_sentinel(self, raw_aggr: str) -> None:
        df = parse_dump(raw_aggr)
        assert (df["thread_id"] == -1).all()

    def test_aggr_mode_columns(self, raw_aggr: str) -> None:
        df = parse_dump(raw_aggr)
        assert df.columns == ["cnode_id", "thread_id", "metric", "value"]

    def test_aggr_mode_row_count(self, raw_aggr: str) -> None:
        df = parse_dump(raw_aggr)
        assert len(df) == 2

    def test_multi_metric_melts(self) -> None:
        raw = "Cnode ID, Thread ID,time,visits\n0,0,1.0,5\n"
        df = parse_dump(raw)
        assert len(df) == 2
        assert set(df["metric"].to_list()) == {"time", "visits"}

    def test_empty_raises(self) -> None:
        with pytest.raises(CubeParseError):
            parse_dump("")

    def test_missing_cnode_id_raises(self) -> None:
        with pytest.raises(CubeParseError, match="Cnode ID"):
            parse_dump("foo,bar\n1,2\n")
