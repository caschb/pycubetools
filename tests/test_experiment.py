"""Unit tests for CubeExperiment using a mock ToolRunner."""

from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import pycubetools
from pycubetools._internal.runner import RunResult
from pycubetools.exceptions import CubeParseError
from pycubetools.experiment import CubeExperiment, SystemDimension

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def cubex_path(tmp_path: Path) -> Path:
    """Return a path to a dummy .cubex file."""
    p = tmp_path / "test.cubex"
    p.touch()
    return p


@pytest.fixture
def other_cubex(tmp_path: Path) -> Path:
    """Return a path to a second dummy .cubex file."""
    p = tmp_path / "other.cubex"
    p.touch()
    return p


def _make_exp(cubex_path: Path) -> CubeExperiment:
    """Construct a CubeExperiment bypassing path validation."""
    exp = CubeExperiment.__new__(CubeExperiment)
    exp._path = cubex_path
    exp._output_dir = None
    exp._owned = False
    exp._owned_path = None
    return exp


def _run_result(stdout: str = "", stderr: str = "", rc: int = 0) -> RunResult:
    return RunResult(stdout=stdout, stderr=stderr, returncode=rc)


# ---------------------------------------------------------------------------
# __init__ validation
# ---------------------------------------------------------------------------


class TestInit:
    """Tests for CubeExperiment.__init__."""

    def test_valid_cubex(self, cubex_path: Path) -> None:
        exp = CubeExperiment(cubex_path)
        assert exp.path == cubex_path

    def test_accepts_string_path(self, cubex_path: Path) -> None:
        exp = CubeExperiment(str(cubex_path))
        assert exp.path == cubex_path

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            CubeExperiment(tmp_path / "missing.cubex")

    def test_wrong_suffix_raises(self, tmp_path: Path) -> None:
        f = tmp_path / "profile.nc"
        f.touch()
        with pytest.raises(ValueError, match=r"Expected a \.cubex"):
            CubeExperiment(f)

    def test_cube_suffix_accepted(self, tmp_path: Path) -> None:
        f = tmp_path / "profile.cube"
        f.touch()
        CubeExperiment(f)

    def test_cube_gz_suffix_accepted(self, tmp_path: Path) -> None:
        f = tmp_path / "profile.cube.gz"
        f.touch()
        CubeExperiment(f)


# ---------------------------------------------------------------------------
# __repr__ and context manager
# ---------------------------------------------------------------------------


class TestRepresentation:
    """Tests for __repr__."""

    def test_repr_contains_path(self, cubex_path: Path) -> None:
        exp = _make_exp(cubex_path)
        assert str(cubex_path) in repr(exp)

    def test_context_manager(self, cubex_path: Path) -> None:
        with _make_exp(cubex_path) as exp:
            assert exp.path == cubex_path


# ---------------------------------------------------------------------------
# Inspection methods (mocked ToolRunner)
# ---------------------------------------------------------------------------

_STAT_OUTPUT = textwrap.dedent("""\
    cube::Metric,Routine,Count,Sum,Mean,Variance,Minimum,Quartile 25,Median,Quartile 75,Maximum
    time,foo,10,100.0,10.0,0.5,8.0,9.0,10.0,11.0,12.0
    """)

_INFO_BASIC_OUTPUT = textwrap.dedent("""\
    Number of nodes    : 1
    Number of processes: 4
    Wallclock time     : 42.0
    """)

_INFO_TREE_OUTPUT = textwrap.dedent("""\
    |            Time | Diff-Calltree
    |       100.0 |  * root
    |        50.0 |  |  * child
    """)

_CALLTREE_OUTPUT = textwrap.dedent("""\
    Reading /dev/null... done.
    0.1 (10%)          root                                   USR:/root
    0.05 (5%)            + child                              USR:/root/child
    """)

_DUMP_OUTPUT = textwrap.dedent("""\
    Cnode ID,time
    0,1.0
    1,2.0
    """)


def _patch_runner(runner_mock: MagicMock, stdout: str) -> None:
    runner_mock.run.return_value = _run_result(stdout)


@pytest.fixture
def mock_runner() -> MagicMock:
    """Return a MagicMock that behaves like a ToolRunner."""
    return MagicMock()


class TestStatMethod:
    """Tests for CubeExperiment.stat."""

    def test_returns_dataframe(self, cubex_path: Path, mock_runner: MagicMock) -> None:
        _patch_runner(mock_runner, _STAT_OUTPUT)
        exp = _make_exp(cubex_path)
        with patch.object(exp, "_make_runner", return_value=mock_runner):
            df = exp.stat()
        assert "metric" in df.columns
        assert "routine" in df.columns

    def test_calls_cube_stat(self, cubex_path: Path, mock_runner: MagicMock) -> None:
        _patch_runner(mock_runner, _STAT_OUTPUT)
        exp = _make_exp(cubex_path)
        with patch.object(exp, "_make_runner", return_value=mock_runner):
            exp.stat()
        mock_runner.run.assert_called_once()
        tool = mock_runner.run.call_args[0][0]
        assert tool == "cube_stat"

    def test_metrics_in_args(self, cubex_path: Path, mock_runner: MagicMock) -> None:
        _patch_runner(mock_runner, _STAT_OUTPUT)
        exp = _make_exp(cubex_path)
        with patch.object(exp, "_make_runner", return_value=mock_runner):
            exp.stat(metrics=("time", "visits"))
        args = mock_runner.run.call_args[0][1]
        assert "time,visits" in args


class TestInfoBasicMethod:
    """Tests for CubeExperiment.info_basic."""

    def test_returns_dict(self, cubex_path: Path, mock_runner: MagicMock) -> None:
        _patch_runner(mock_runner, _INFO_BASIC_OUTPUT)
        exp = _make_exp(cubex_path)
        with patch.object(exp, "_make_runner", return_value=mock_runner):
            d = exp.info_basic()
        assert isinstance(d, dict)
        assert d["processes"] == 4

    def test_calls_cube_info(self, cubex_path: Path, mock_runner: MagicMock) -> None:
        _patch_runner(mock_runner, _INFO_BASIC_OUTPUT)
        exp = _make_exp(cubex_path)
        with patch.object(exp, "_make_runner", return_value=mock_runner):
            exp.info_basic()
        tool = mock_runner.run.call_args[0][0]
        assert tool == "cube_info"


class TestInfoMethod:
    """Tests for CubeExperiment.info."""

    def test_returns_dataframe(self, cubex_path: Path, mock_runner: MagicMock) -> None:
        _patch_runner(mock_runner, _INFO_TREE_OUTPUT)
        exp = _make_exp(cubex_path)
        with patch.object(exp, "_make_runner", return_value=mock_runner):
            df = exp.info()
        assert "name" in df.columns
        assert "depth" in df.columns

    def test_metric_arg_passed(self, cubex_path: Path, mock_runner: MagicMock) -> None:
        _patch_runner(mock_runner, _INFO_TREE_OUTPUT)
        exp = _make_exp(cubex_path)
        with patch.object(exp, "_make_runner", return_value=mock_runner):
            exp.info(metric="visits")
        args = mock_runner.run.call_args[0][1]
        assert "visits" in args


class TestCalltreeMethod:
    """Tests for CubeExperiment.calltree."""

    def test_returns_dataframe(self, cubex_path: Path, mock_runner: MagicMock) -> None:
        _patch_runner(mock_runner, _CALLTREE_OUTPUT)
        exp = _make_exp(cubex_path)
        with patch.object(exp, "_make_runner", return_value=mock_runner):
            df = exp.calltree()
        assert "name" in df.columns
        assert "callpath" in df.columns

    def test_inclusive_flag_added(
        self, cubex_path: Path, mock_runner: MagicMock,
    ) -> None:
        _patch_runner(mock_runner, _CALLTREE_OUTPUT)
        exp = _make_exp(cubex_path)
        with patch.object(exp, "_make_runner", return_value=mock_runner):
            exp.calltree(inclusive=True)
        args = mock_runner.run.call_args[0][1]
        assert "-i" in args

    def test_exclusive_no_i_flag(
        self, cubex_path: Path, mock_runner: MagicMock,
    ) -> None:
        _patch_runner(mock_runner, _CALLTREE_OUTPUT)
        exp = _make_exp(cubex_path)
        with patch.object(exp, "_make_runner", return_value=mock_runner):
            exp.calltree(inclusive=False)
        args = mock_runner.run.call_args[0][1]
        assert "-i" not in args


class TestDumpMethod:
    """Tests for CubeExperiment.dump."""

    def test_returns_dataframe(self, cubex_path: Path, mock_runner: MagicMock) -> None:
        _patch_runner(mock_runner, _DUMP_OUTPUT)
        exp = _make_exp(cubex_path)
        with patch.object(exp, "_make_runner", return_value=mock_runner):
            df = exp.dump()
        assert "cnode_id" in df.columns
        assert "metric" in df.columns

    def test_csv2_format_in_args(
        self, cubex_path: Path, mock_runner: MagicMock,
    ) -> None:
        _patch_runner(mock_runner, _DUMP_OUTPUT)
        exp = _make_exp(cubex_path)
        with patch.object(exp, "_make_runner", return_value=mock_runner):
            exp.dump()
        args = mock_runner.run.call_args[0][1]
        assert "csv2" in args


# ---------------------------------------------------------------------------
# Algebra — cmp
# ---------------------------------------------------------------------------


class TestCmpMethod:
    """Tests for CubeExperiment.cmp."""

    def test_equal_when_no_differ(
        self, cubex_path: Path, other_cubex: Path, mock_runner: MagicMock,
    ) -> None:
        _patch_runner(mock_runner, "Files are equal.\n")
        exp = _make_exp(cubex_path)
        other = _make_exp(other_cubex)
        with patch.object(exp, "_make_runner", return_value=mock_runner):
            result = exp.cmp(other)
        assert result.equal is True

    def test_not_equal_when_differ_in_output(
        self, cubex_path: Path, other_cubex: Path, mock_runner: MagicMock,
    ) -> None:
        _patch_runner(mock_runner, "Files differ in metric 'time'.\n")
        exp = _make_exp(cubex_path)
        other = _make_exp(other_cubex)
        with patch.object(exp, "_make_runner", return_value=mock_runner):
            result = exp.cmp(other)
        assert result.equal is False

    def test_details_in_result(
        self, cubex_path: Path, other_cubex: Path, mock_runner: MagicMock,
    ) -> None:
        stdout = "some output\n"
        _patch_runner(mock_runner, stdout)
        exp = _make_exp(cubex_path)
        other = _make_exp(other_cubex)
        with patch.object(exp, "_make_runner", return_value=mock_runner):
            result = exp.cmp(other)
        assert result.details == stdout


# ---------------------------------------------------------------------------
# Public __all__ surface
# ---------------------------------------------------------------------------


class TestPublicSurface:
    """Verify the public API exports exactly the expected names."""

    _EXPECTED = {
        "CubeExperiment",
        "SystemDimension",
        "CompareResult",
        "configure",
        "CubeToolsError",
        "CubeToolError",
        "CubeParseError",
        "CubeConfigError",
    }

    def test_all_exports(self) -> None:
        assert set(pycubetools.__all__) == self._EXPECTED

    def test_imports_succeed(self) -> None:
        for name in self._EXPECTED:
            assert hasattr(pycubetools, name)

    def test_system_dimension_values(self) -> None:
        assert SystemDimension.KEEP.value == "keep"
        assert SystemDimension.REDUCE.value == "reduce"
        assert SystemDimension.COLLAPSE.value == "collapse"

    def test_cube_tools_error_hierarchy(self) -> None:
        from pycubetools.exceptions import (
            CubeConfigError,
            CubeParseError,
            CubeToolError,
            CubeToolsError,
        )

        assert issubclass(CubeConfigError, CubeToolsError)
        assert issubclass(CubeToolError, CubeToolsError)
        assert issubclass(CubeParseError, CubeToolsError)

    def test_cube_tool_error_fields(self) -> None:
        from pycubetools.exceptions import CubeToolError

        err = CubeToolError(
            tool="cube_stat",
            returncode=1,
            stderr="oops",
            cmd=["cube_stat", "x.cubex"],
        )
        assert err.tool == "cube_stat"
        assert err.returncode == 1
        assert "oops" in str(err)
        assert "cube_stat" in str(err)

    def test_cube_parse_error_fields(self) -> None:
        err = CubeParseError(tool="cube_info", raw="bad\noutput", reason="no rows")
        assert err.tool == "cube_info"
        assert err.raw == "bad\noutput"
        assert "no rows" in str(err)


# ---------------------------------------------------------------------------
# Integration stubs
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_integration_stat(cubex_path: Path) -> None:
    """Integration test: stat() against a real .cubex file (requires CubeLib)."""
    pytest.importorskip("pycubexr")
    exp = CubeExperiment(cubex_path)
    df = exp.stat()
    assert len(df) > 0
