"""Public CubeExperiment class and re-exported algebra types."""

from __future__ import annotations

import contextlib
import functools
from pathlib import Path
from typing import TYPE_CHECKING, Self

from pycubetools._internal import algebra as _algebra
from pycubetools._internal import inspection as _inspection
from pycubetools._internal.algebra import CompareResult, SystemDimension
from pycubetools._internal.reader import CubexReader
from pycubetools._internal.runner import ToolRunner
from pycubetools._internal.tempfiles import TempfileManager
from pycubetools.config import get_config

if TYPE_CHECKING:
    from types import TracebackType

    import polars as pl

_VALID_SUFFIXES = {".cubex", ".cube", ".gz"}


def _validate_path(path: Path) -> None:
    """Raise if *path* does not exist or has an unexpected suffix."""
    if not path.exists():
        msg = f"No such file: {path}"
        raise FileNotFoundError(msg)
    name = path.name
    if not name.endswith((".cubex", ".cube", ".cube.gz")):
        msg = f"Expected a .cubex, .cube, or .cube.gz file; got: {name!r}"
        raise ValueError(msg)


class CubeExperiment:
    """A lazily-evaluated wrapper around a CubeLib ``.cubex`` experiment.

    Parameters
    ----------
    path:
        Path to the ``.cubex`` (or ``.cube`` / ``.cube.gz``) file.
    output_dir:
        Directory for intermediate files created by algebra operations.
        When ``None``, a temporary directory is used and cleaned up
        automatically.

    Examples
    --------
    Basic usage::

        exp = CubeExperiment("profile.cubex")
        df = exp.stat()

    As a context manager (guarantees temp-file cleanup)::

        with CubeExperiment("profile.cubex").diff(other) as result:
            df = result.calltree()

    """

    def __init__(
        self,
        path: str | Path,
        output_dir: str | Path | None = None,
    ) -> None:
        """Initialise and validate the experiment path."""
        self._path = Path(path)
        _validate_path(self._path)
        self._output_dir: Path | None = Path(output_dir) if output_dir else None
        # True when this instance owns its output file and should clean it up.
        self._owned: bool = False
        self._owned_path: Path | None = None
        # Keeps the TempfileManager alive when the output was written to a
        # temporary directory — prevents the directory from being deleted by GC
        # before we finish using the file.
        self._temp_mgr: TempfileManager | None = None

    # ------------------------------------------------------------------
    # Dunder helpers
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        """Return a concise representation."""
        return f"CubeExperiment({str(self._path)!r})"

    def __enter__(self) -> Self:
        """Enter the context manager."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Exit the context manager, cleaning up owned temp files."""
        self._cleanup()

    def __del__(self) -> None:
        """Clean up owned temp files on garbage collection."""
        self._cleanup()

    def _cleanup(self) -> None:
        """Remove the owned output file and any associated temp directory."""
        if getattr(self, "_owned", False) and self._owned_path is not None:
            with contextlib.suppress(OSError):
                self._owned_path.unlink(missing_ok=True)
            temp_mgr = getattr(self, "_temp_mgr", None)
            if temp_mgr is not None:
                temp_mgr.cleanup()
            self._owned = False

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def path(self) -> Path:
        """Absolute path to the underlying ``.cubex`` file."""
        return self._path

    # ------------------------------------------------------------------
    # Lazily cached structural properties (via CubexReader, not subprocess)
    # ------------------------------------------------------------------

    @functools.cached_property
    def metric_tree(self) -> pl.DataFrame:
        """Return one row per metric in the file.

        Returns
        -------
        pl.DataFrame
            Columns: ``name``, ``display_name``, ``dtype``, ``uom``,
            ``description``.

        """
        return CubexReader(self._path).metric_tree()

    @functools.cached_property
    def system_tree(self) -> pl.DataFrame:
        """Return one row per thread location.

        Returns
        -------
        pl.DataFrame
            Columns: ``machine``, ``node``, ``process``, ``thread``.

        """
        return CubexReader(self._path).system_tree()

    @functools.cached_property
    def cnode_tree(self) -> pl.DataFrame:
        """Return one row per call-tree node.

        Returns
        -------
        pl.DataFrame
            Columns: ``cnode_id``, ``region_name``, ``file``, ``line``,
            ``parent_id``, ``depth``.

        """
        return CubexReader(self._path).cnode_tree()

    # ------------------------------------------------------------------
    # Algebra — instance methods
    # ------------------------------------------------------------------

    def diff(
        self,
        other: CubeExperiment,
        system_dim: SystemDimension = SystemDimension.KEEP,
        output_dir: str | Path | None = None,
    ) -> CubeExperiment:
        """Subtract *other* from this experiment using ``cube_diff``.

        Parameters
        ----------
        other:
            The experiment to subtract.
        system_dim:
            How to handle system-dimension mismatches.
        output_dir:
            Override for the output directory.  When ``None`` the
            instance's default (or a temporary directory) is used.

        Returns
        -------
        CubeExperiment
            A new experiment wrapping the diff result.

        """
        out_dir = self._resolve_output_dir(
            Path(output_dir) if output_dir else None,
        )
        mgr = TempfileManager(out_dir)
        out_path = mgr.next_path()
        runner = self._make_runner()
        _algebra.diff(self._path, other._path, out_path, system_dim, runner)
        return _make_owned(out_path, out_dir, mgr if out_dir is None else None)

    def cmp(self, other: CubeExperiment) -> CompareResult:
        """Compare this experiment with *other* using ``cube_cmp``.

        Parameters
        ----------
        other:
            The experiment to compare against.

        Returns
        -------
        CompareResult
            Equality flag and full ``cube_cmp`` stdout.

        """
        return _algebra.cmp(self._path, other._path, self._make_runner())

    # ------------------------------------------------------------------
    # Algebra — class methods
    # ------------------------------------------------------------------

    @classmethod
    def merge(
        cls,
        *experiments: CubeExperiment,
        system_dim: SystemDimension = SystemDimension.KEEP,
        output_dir: str | Path | None = None,
    ) -> CubeExperiment:
        """Merge two or more experiments using ``cube_merge``.

        Parameters
        ----------
        *experiments:
            Experiments to merge (at least two).
        system_dim:
            How to handle system-dimension mismatches.
        output_dir:
            Directory for the result file.

        Returns
        -------
        CubeExperiment
            A new experiment wrapping the merged result.

        """
        if len(experiments) < 2:  # noqa: PLR2004 — minimum arity, not a magic number
            msg = f"merge() requires at least 2 experiments, got {len(experiments)}"
            raise ValueError(msg)
        out_dir = Path(output_dir) if output_dir else None
        runner = experiments[0]._make_runner()  # noqa: SLF001
        mgr = TempfileManager(out_dir)
        out_path = mgr.next_path()
        _algebra.merge(
            [e._path for e in experiments], out_path, system_dim, runner,  # noqa: SLF001
        )
        return _make_owned(out_path, out_dir, mgr if out_dir is None else None)

    @classmethod
    def mean(
        cls,
        *experiments: CubeExperiment,
        system_dim: SystemDimension = SystemDimension.KEEP,
        output_dir: str | Path | None = None,
    ) -> CubeExperiment:
        """Average two or more experiments using ``cube_mean``.

        Parameters
        ----------
        *experiments:
            Experiments to average (at least two).
        system_dim:
            How to handle system-dimension mismatches.
        output_dir:
            Directory for the result file.

        Returns
        -------
        CubeExperiment
            A new experiment wrapping the averaged result.

        """
        if len(experiments) < 2:  # noqa: PLR2004 — minimum arity, not a magic number
            msg = f"mean() requires at least 2 experiments, got {len(experiments)}"
            raise ValueError(msg)
        out_dir = Path(output_dir) if output_dir else None
        runner = experiments[0]._make_runner()  # noqa: SLF001
        mgr = TempfileManager(out_dir)
        out_path = mgr.next_path()
        _algebra.mean(
            [e._path for e in experiments], out_path, system_dim, runner,  # noqa: SLF001
        )
        return _make_owned(out_path, out_dir, mgr if out_dir is None else None)

    # ------------------------------------------------------------------
    # Inspection
    # ------------------------------------------------------------------

    def calltree(
        self,
        metric: str = "time",
        threshold: float = 0.0,
        inclusive: bool = True,
    ) -> pl.DataFrame:
        """Return the calltree as a DataFrame.

        Parameters
        ----------
        metric:
            Metric to display (``-m``).
        threshold:
            Minimum percentage threshold (``-t``).
        inclusive:
            Compute inclusive values (``-i``).

        Returns
        -------
        pl.DataFrame
            Columns: ``cnode_id``, ``name``, ``callpath``, ``value``,
            ``pct``, ``depth``.

        """
        return _inspection.calltree(
            self._path, metric, threshold, inclusive, self._make_runner(),
        )

    def stat(
        self,
        metrics: tuple[str, ...] = ("time",),
        routines: tuple[str, ...] | None = None,
        top_n: int | None = None,
        per_thread: bool = False,
    ) -> pl.DataFrame:
        """Return per-routine statistics as a DataFrame.

        Parameters
        ----------
        metrics:
            Metrics to include.
        routines:
            Routines to filter on; ``None`` means all.
        top_n:
            Return only the top *N* routines by exclusive time.
        per_thread:
            Request per-thread statistical breakdown.

        Returns
        -------
        pl.DataFrame
            Columns: ``metric``, ``routine``, ``count``, ``sum``,
            ``mean``, ``variance``, ``minimum``, ``maximum``.

        """
        return _inspection.stat(
            self._path, metrics, routines, top_n, per_thread, self._make_runner(),
        )

    def dump(
        self,
        metrics: tuple[str, ...] = ("time",),
        cnodes: str = "all",
        threads: str = "aggr",
        z: str = "excl",
    ) -> pl.DataFrame:
        """Return raw metric values as a long-format DataFrame.

        Parameters
        ----------
        metrics:
            Metrics to dump.
        cnodes:
            Cnode selection string (e.g. ``"all"`` or ``"0,1,5-10"``).
        threads:
            Thread selection string (e.g. ``"aggr"`` or ``"0"``).
        z:
            Calltree value mode: ``"incl"`` or ``"excl"``.

        Returns
        -------
        pl.DataFrame
            Columns: ``cnode_id``, ``thread_id``, ``metric``, ``value``.

        """
        return _inspection.dump(
            self._path, metrics, cnodes, threads, z, self._make_runner(),
        )

    def info(self, metric: str = "time") -> pl.DataFrame:
        """Return the calltree with metric values from ``cube_info -m``.

        Parameters
        ----------
        metric:
            Metric name to display.

        Returns
        -------
        pl.DataFrame
            Columns: ``metric``, ``value``, ``cnode_id``, ``name``,
            ``depth``.

        """
        return _inspection.info_tree(self._path, metric, self._make_runner())

    def info_basic(self) -> dict[str, int | float]:
        """Return basic experiment metadata from ``cube_info -b``.

        Returns
        -------
        dict
            Keys: ``nodes``, ``processes``, ``wallclock_time``.

        """
        return _inspection.info_basic(self._path, self._make_runner())

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _make_runner(self) -> ToolRunner:
        """Return a fresh ToolRunner using the current global config."""
        return ToolRunner(get_config())

    def _resolve_output_dir(self, override: Path | None) -> Path | None:
        """Return the effective output directory for an algebra result."""
        return override if override is not None else self._output_dir


def _make_owned(
    out_path: Path,
    out_dir: Path | None,
    temp_mgr: TempfileManager | None = None,
) -> CubeExperiment:
    """Construct a CubeExperiment that owns *out_path* and will delete it.

    ``_owned`` is always ``True`` for algebra-created instances.
    ``_owned_path`` is only set when *out_dir* is ``None`` (temp dir),
    because user-provided output directories must not be auto-deleted.
    *temp_mgr* is stored to keep the ``TemporaryDirectory`` alive until
    ``_cleanup`` runs.
    """
    exp = CubeExperiment.__new__(CubeExperiment)
    exp._path = out_path  # noqa: SLF001 — constructing without __init__
    exp._output_dir = out_dir  # noqa: SLF001 — constructing without __init__
    exp._owned = True  # noqa: SLF001 — always True for algebra results
    exp._owned_path = out_path if out_dir is None else None  # noqa: SLF001 — only clean up temp-dir outputs
    exp._temp_mgr = temp_mgr  # noqa: SLF001 — constructing without __init__
    return exp
