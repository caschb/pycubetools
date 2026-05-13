"""pyCubexR facade returning polars DataFrames."""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, Any

import polars as pl
import pycubexr

from pycubetools.exceptions import CubeParseError

if TYPE_CHECKING:
    from pathlib import Path


class CubexReader:
    """Wrap a ``.cubex`` file and expose its contents as polars DataFrames.

    All public methods are lazy and cached on the instance.  pyCubexR
    exceptions are caught and re-raised as
    :class:`~pycubetools.exceptions.CubeParseError` so they never leak
    through the public API.

    Parameters
    ----------
    path:
        Path to the ``.cubex`` file.

    """

    def __init__(self, path: Path) -> None:
        """Open the archive and parse the anchor document."""
        self._path = path
        try:
            self._parser = pycubexr.CubexParser(str(path))
            self._parser.__enter__()
        except Exception as exc:
            msg = f"Failed to open {path}"
            raise CubeParseError(tool="CubexReader", raw="", reason=msg) from exc

    def __del__(self) -> None:
        """Close the underlying archive when the reader is garbage-collected."""
        with contextlib.suppress(Exception):
            self._parser.__exit__(None, None, None)

    # ------------------------------------------------------------------
    # Public cached methods
    # ------------------------------------------------------------------

    def metric_tree(self) -> pl.DataFrame:
        """Return one row per metric in the file.

        Returns
        -------
        pl.DataFrame
            Columns: ``name``, ``display_name``, ``dtype``, ``uom``,
            ``description``.

        Raises
        ------
        CubeParseError
            If pyCubexR fails to read the metric tree.

        """
        if not hasattr(self, "_metric_tree"):
            self._metric_tree = self._build_metric_tree()
        return self._metric_tree

    def system_tree(self) -> pl.DataFrame:
        """Return one row per thread location with system hierarchy columns.

        Returns
        -------
        pl.DataFrame
            Columns: ``machine``, ``node``, ``process``, ``thread``.

        Raises
        ------
        CubeParseError
            If pyCubexR fails to read the system tree.

        """
        if not hasattr(self, "_system_tree"):
            self._system_tree = self._build_system_tree()
        return self._system_tree

    def cnode_tree(self) -> pl.DataFrame:
        """Return one row per call-tree node.

        Returns
        -------
        pl.DataFrame
            Columns: ``cnode_id``, ``region_name``, ``file``, ``line``,
            ``parent_id``, ``depth``.

        Raises
        ------
        CubeParseError
            If pyCubexR fails to read the call-tree.

        """
        if not hasattr(self, "_cnode_tree"):
            self._cnode_tree = self._build_cnode_tree()
        return self._cnode_tree

    def values(self, metric_name: str) -> pl.DataFrame:
        """Return per-cnode per-thread values for *metric_name*.

        Parameters
        ----------
        metric_name:
            The metric's unique name, e.g. ``"time"``.

        Returns
        -------
        pl.DataFrame
            Columns: ``cnode_id``, ``thread_id``, ``value``.

        Raises
        ------
        CubeParseError
            If the metric is not found or values cannot be read.

        """
        key = f"_values_{metric_name}"
        if not hasattr(self, key):
            setattr(self, key, self._build_values(metric_name))
        return getattr(self, key)

    # ------------------------------------------------------------------
    # Private builders
    # ------------------------------------------------------------------

    def _build_metric_tree(self) -> pl.DataFrame:
        try:
            metrics = list(self._parser.get_metrics())
        except Exception as exc:
            raise CubeParseError(
                tool="CubexReader.metric_tree",
                raw="",
                reason=str(exc),
            ) from exc

        rows: list[dict[str, str]] = []

        def _collect(metric_list: list) -> None:  # type: ignore[type-arg]
            for m in metric_list:
                rows.append(
                    {
                        "name": m.name,
                        "display_name": m.display_name,
                        "dtype": m.data_type,
                        "uom": m.units,
                        "description": m.description,
                    },
                )
                _collect(m.childs)

        _collect(metrics)
        schema = {
            "name": pl.Utf8,
            "display_name": pl.Utf8,
            "dtype": pl.Utf8,
            "uom": pl.Utf8,
            "description": pl.Utf8,
        }
        return pl.DataFrame(rows, schema=schema)

    def _build_system_tree(self) -> pl.DataFrame:
        try:
            roots = self._parser._anchor_result.system_tree_nodes  # noqa: SLF001
        except Exception as exc:
            raise CubeParseError(
                tool="CubexReader.system_tree",
                raw="",
                reason=str(exc),
            ) from exc

        rows: list[dict[str, str]] = []

        def _walk(node: Any, machine: str) -> None:  # noqa: ANN401 — pyCubexR tree nodes are not exported with a public type
            children = node._system_tree_node_children  # noqa: SLF001 — pyCubexR internal
            groups = node._location_group_children  # noqa: SLF001 — pyCubexR internal
            if groups:
                node_name: str = node.name  # type: ignore[attr-defined]
                for group in groups:
                    process_name: str = group.name
                    rows.extend(
                        {
                            "machine": machine,
                            "node": node_name,
                            "process": process_name,
                            "thread": loc.name,
                        }
                        for loc in group._locations  # noqa: SLF001 — pyCubexR internal
                    )
            for child in children:
                _walk(child, machine)

        for root in roots:
            _walk(root, root.name)

        schema = {
            "machine": pl.Utf8,
            "node": pl.Utf8,
            "process": pl.Utf8,
            "thread": pl.Utf8,
        }
        return pl.DataFrame(rows, schema=schema)

    def _build_cnode_tree(self) -> pl.DataFrame:
        try:
            all_cnodes = list(self._parser.all_cnodes())
        except Exception as exc:
            raise CubeParseError(
                tool="CubexReader.cnode_tree",
                raw="",
                reason=str(exc),
            ) from exc

        cnode_ids: list[int] = []
        region_names: list[str] = []
        files: list[str] = []
        line_numbers: list[int] = []
        parent_ids: list[int | None] = []
        depths: list[int] = []

        for cn in all_cnodes:
            depth = 0
            node = cn
            while node.parent is not None:
                depth += 1
                node = node.parent

            region = cn.region
            if region is not None:
                raw_line = region.begin
                line_num = int(raw_line) if raw_line and raw_line != -1 else 0
                region_name: str = region.name
                file_path: str = region.mod or ""
            else:
                line_num = 0
                region_name = ""
                file_path = ""

            cnode_ids.append(cn.id)
            region_names.append(region_name)
            files.append(file_path)
            line_numbers.append(line_num)
            parent_ids.append(cn.parent.id if cn.parent else None)
            depths.append(depth)

        return pl.DataFrame(
            {
                "cnode_id": cnode_ids,
                "region_name": region_names,
                "file": files,
                "line": line_numbers,
                "parent_id": parent_ids,
                "depth": depths,
            },
        )

    def _build_values(self, metric_name: str) -> pl.DataFrame:
        try:
            metric = self._parser.get_metric_by_name(metric_name)
        except Exception as exc:
            raise CubeParseError(
                tool="CubexReader.values",
                raw="",
                reason=f"Metric '{metric_name}' not found: {exc}",
            ) from exc

        try:
            mv = self._parser.get_metric_values(metric)
            # cnode_values() requires a CNode object, not an int; build a
            # lookup from the parser so we can resolve each index.
            cnode_by_id = {cn.id: cn for cn in self._parser.all_cnodes()}
            cnode_ids: list[int] = []
            thread_ids: list[int] = []
            values: list[float] = []

            for cnode_idx in mv.cnode_indices:
                cnode = cnode_by_id.get(cnode_idx)
                if cnode is None:
                    continue
                vals = mv.cnode_values(cnode)
                for thread_id, val in enumerate(vals):
                    cnode_ids.append(cnode_idx)
                    thread_ids.append(thread_id)
                    values.append(float(val))
        except CubeParseError:
            raise
        except Exception as exc:
            raise CubeParseError(
                tool="CubexReader.values",
                raw="",
                reason=f"Failed to read values for '{metric_name}': {exc}",
            ) from exc

        return pl.DataFrame(
            {
                "cnode_id": cnode_ids,
                "thread_id": thread_ids,
                "value": values,
            },
        )
