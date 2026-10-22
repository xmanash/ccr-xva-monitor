"""Load methodology markdown into the local chunk store."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ccr_xva.memory.repository import get_repository  # noqa: E402
from ccr_xva.rag.ingest import load_markdown_chunks  # noqa: E402
from shared.settings import get_settings  # noqa: E402


def main() -> None:
    settings = get_settings()
    chunks = load_markdown_chunks()
    get_repository(settings.database_url).replace_chunks(chunks)
    print(f"Stored {len(chunks)} chunks")


if __name__ == "__main__":
    main()
