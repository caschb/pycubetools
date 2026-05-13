# pycubetools

A Python wrapper around the [CubeLib 4.9](https://www.scalasca.org/software/cube-4.x/download.html) command-line tools, designed for HPC performance analysis in notebooks and scripts. All results are returned as [polars](https://pola.rs) DataFrames.

## Features

- **Inspection** — call-tree profiling, per-routine statistics, raw metric dump, and basic experiment metadata via `cube_calltree`, `cube_stat`, `cube_dump`, and `cube_info`
- **Algebra** — diff, merge, and mean of `.cubex` profiles via `cube_diff`, `cube_merge`, and `cube_mean`; automatic cleanup of temporary files
- **Direct file reading** — metric tree, system tree, and call-node tree read directly from `.cubex` files using [pyCubexR](https://github.com/extra-p/pycubexr), with no subprocess overhead

## Requirements

- Python ≥ 3.11
- [CubeLib 4.9](https://www.scalasca.org/software/cube-4.x/download.html) binaries on PATH **or** pointed to via `CUBE_INSTALL_DIR`

## Installation

```bash
pip install pycubetools
```

Or from source with [uv](https://github.com/astral-sh/uv):

```bash
git clone https://github.com/caschb/pycubetools
cd pycubetools
uv sync
```

## Quick start

```python
import pycubetools
from pycubetools import CubeExperiment, SystemDimension

# Point to CubeLib if it is not already on PATH
pycubetools.configure(install_dir="/opt/cube")
# or: export CUBE_INSTALL_DIR=/opt/cube

exp = CubeExperiment("profile.cubex")

# Experiment metadata (reads file directly — no subprocess)
print(exp.info_basic())          # {'nodes': 2, 'processes': 16, 'wallclock_time': 49.6}
print(exp.metric_tree)           # polars DataFrame
print(exp.system_tree)           # one row per thread location
print(exp.cnode_tree)            # one row per call-tree node

# Call-tree profiling
ct = exp.calltree(metric="time", inclusive=True)   # inclusive values
ct = exp.calltree(metric="time", inclusive=False)  # exclusive (self) time

# Per-routine statistics (count, sum, mean, variance, min, max per thread)
df = exp.stat(metrics=("time", "mpi"))

# Raw metric values (long-format, one row per cnode × thread × metric)
df = exp.dump(metrics=("time",), cnodes="all", threads="aggr")  # aggregated
df = exp.dump(metrics=("time",), cnodes="all", threads="0-7")   # per-thread

# Call-tree view with values
df = exp.info(metric="time")

# Algebra: diff two experiments (context manager guarantees cleanup)
other = CubeExperiment("profile2.cubex")
with exp.diff(other, system_dim=SystemDimension.COLLAPSE) as delta:
    df = delta.calltree(metric="time")

# Merge and mean
merged = CubeExperiment.merge(exp, other)
averaged = CubeExperiment.mean(exp, other)

# Compare
result = exp.cmp(other)
print(result.equal, result.details)
```

## Configuration

CubeLib binaries are resolved in this order (highest to lowest priority):

| Mechanism | Example |
|---|---|
| `pycubetools.configure(install_dir=…)` | `configure(install_dir="/opt/cube")` |
| `CUBE_INSTALL_DIR` env variable | `export CUBE_INSTALL_DIR=/opt/cube` |
| `~/.config/pycubetools/config.toml` | `[cubelib]\ninstall_dir = "/opt/cube"` |
| `shutil.which` PATH lookup | CubeLib on PATH |

## Development

```bash
uv sync                  # install all dependencies (including dev)
uv run pytest            # run unit tests (integration tests skipped by default)
uv run pytest -m integration   # run integration tests (requires CubeLib)
uv run ruff check .      # lint
uv run ruff format .     # format
uv run ty check          # type check
```

## Notebook

An interactive quick-start notebook is in [`notebooks/notebook.ipynb`](notebooks/notebook.ipynb). It covers all API methods with visualisations against real TeaLeaf benchmark profiles.

```bash
uv run jupyter lab notebooks/
```

## API reference

| Method / property | Underlying tool | Returns |
|---|---|---|
| `metric_tree` | pyCubexR (no subprocess) | `pl.DataFrame` |
| `system_tree` | pyCubexR | `pl.DataFrame` |
| `cnode_tree` | pyCubexR | `pl.DataFrame` |
| `info_basic()` | `cube_info -b` | `dict` |
| `info(metric)` | `cube_info -m metric` | `pl.DataFrame` |
| `calltree(metric, inclusive)` | `cube_calltree -a -c -p` | `pl.DataFrame` |
| `stat(metrics, …)` | `cube_stat -%` | `pl.DataFrame` |
| `dump(metrics, cnodes, threads)` | `cube_dump -s csv2` | `pl.DataFrame` |
| `diff(other, system_dim)` | `cube_diff` | `CubeExperiment` |
| `merge(*exps, system_dim)` | `cube_merge` | `CubeExperiment` |
| `mean(*exps, system_dim)` | `cube_mean` | `CubeExperiment` |
| `cmp(other)` | `cube_cmp` | `CompareResult` |

### `SystemDimension` enum

| Value | `cube_diff` / `cube_merge` / `cube_mean` flag | Behaviour |
|---|---|---|
| `KEEP` (default) | _(none)_ | Error on system-dimension mismatch |
| `REDUCE` | `-c` | Reduce to common system dimension |
| `COLLAPSE` | `-C` | Collapse all system dimensions to one |

### Exceptions

| Exception | Raised when |
|---|---|
| `CubeConfigError` | CubeLib binaries cannot be found |
| `CubeToolError` | A CubeLib binary exits with a non-zero return code |
| `CubeParseError` | Tool stdout cannot be parsed into a DataFrame |
