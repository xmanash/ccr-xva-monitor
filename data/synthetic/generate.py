"""CLI wrapper so sample books can be regenerated from data/synthetic."""

from pathlib import Path
import runpy

if __name__ == "__main__":
    runpy.run_path(str(Path(__file__).resolve().parents[2] / "scripts" / "seed_data.py"), run_name="__main__")
