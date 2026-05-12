from pathlib import Path


class CubeExperiment:
    def __init__(self, filename: Path):
        self.filename = filename

    def __repr__(self):
        return f"{self.filename=}"
