"""Binary location resolution for CubeLib tools."""

from __future__ import annotations

import os
import shutil
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from pycubetools.exceptions import CubeConfigError

_ENV_VAR = "CUBE_INSTALL_DIR"


@dataclass
class CubeConfig:
    """Resolve and cache CubeLib binary paths.

    Parameters
    ----------
    install_dir:
        Explicit installation prefix. When set, binaries are looked up at
        ``install_dir / "bin" / name``. When ``None``, :func:`shutil.which`
        is used instead.

    """

    install_dir: Path | None = None
    _cache: dict[str, Path] = field(default_factory=dict, init=False, repr=False)

    def binary(self, name: str) -> Path:
        """Return the resolved path for *name*, raising on failure.

        Results are cached; subsequent calls for the same name are free.

        Parameters
        ----------
        name:
            Binary name, e.g. ``"cube_stat"``.

        Returns
        -------
        Path
            Absolute path to the binary.

        Raises
        ------
        CubeConfigError
            When the binary cannot be found.

        """
        if name in self._cache:
            return self._cache[name]

        path = self._resolve(name)
        self._cache[name] = path
        return path

    def _resolve(self, name: str) -> Path:
        if self.install_dir is not None:
            candidate = self.install_dir / "bin" / name
            if candidate.is_file():
                return candidate
            msg = (
                f"Binary '{name}' not found at {candidate}. "
                f"Check that install_dir={self.install_dir!r} is correct."
            )
            raise CubeConfigError(msg)

        found = shutil.which(name)
        if found is None:
            msg = (
                f"Binary '{name}' not found on PATH. "
                "Set CUBE_INSTALL_DIR, configure ~/.config/pycubetools/config.toml, "
                "or call pycubetools.configure(install_dir=...)."
            )
            raise CubeConfigError(msg)
        return Path(found)


# Module-level singleton — None until first use.
_config: CubeConfig | None = None


def configure(install_dir: str | Path | None = None) -> None:
    """Set the global CubeLib configuration.

    Calling this again replaces the previous configuration and clears the
    binary path cache.  Pass ``install_dir=None`` to revert to automatic
    resolution (environment variable → config file → PATH).

    Parameters
    ----------
    install_dir:
        Path to the CubeLib installation prefix.  Binaries are expected at
        ``<install_dir>/bin/<name>``.  ``None`` enables automatic resolution.

    """
    global _config  # noqa: PLW0603 — intentional module-level singleton
    resolved = Path(install_dir) if install_dir is not None else None
    _config = CubeConfig(install_dir=resolved)


def get_config() -> CubeConfig:
    """Return the active :class:`CubeConfig`, initialising lazily on first call.

    Resolution order when no explicit :func:`configure` call has been made:

    1. ``CUBE_INSTALL_DIR`` environment variable
    2. ``~/.config/pycubetools/config.toml``  (``[cubelib] install_dir = "…"``)
    3. :func:`shutil.which` PATH lookup (``install_dir=None``)

    Returns
    -------
    CubeConfig
        The active configuration instance.

    """
    global _config  # noqa: PLW0603 — intentional module-level singleton
    if _config is not None:
        return _config

    _config = _build_default_config()
    return _config


def _build_default_config() -> CubeConfig:
    """Build a CubeConfig from environment / config file / PATH."""
    env_val = os.environ.get(_ENV_VAR)
    if env_val:
        return CubeConfig(install_dir=Path(env_val))

    toml_dir = _read_toml_install_dir()
    if toml_dir is not None:
        return CubeConfig(install_dir=toml_dir)

    return CubeConfig(install_dir=None)


def _read_toml_install_dir() -> Path | None:
    """Read install_dir from the TOML config file, or return None."""
    # Evaluated here (not at module level) to avoid side effects on import.
    toml_path = Path.home() / ".config" / "pycubetools" / "config.toml"
    if not toml_path.is_file():
        return None

    with toml_path.open("rb") as fh:
        data = tomllib.load(fh)

    raw = data.get("cubelib", {}).get("install_dir")
    return Path(raw) if raw else None
