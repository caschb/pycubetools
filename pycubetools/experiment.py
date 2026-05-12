"""Module that contains classes for managing CUBE files."""

from pathlib import Path


class CubeExperiment:
    """Manages operations with the CUBE file."""

    def __init__(self, filename: str | Path) -> None:
        """Create a CubeExperiment instance.

        Args:
            filename (str or PathLike): The filename of the CUBE file

        """
        self.filename = filename

    def __repr__(self) -> str:
        """Return representation of the instance."""
        return f"{self.filename=}"
