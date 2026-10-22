"""Split methodology notes into headed chunks stored for hybrid retrieval."""

from __future__ import annotations

import hashlib
from pathlib import Path

from ccr_xva.utils.paths import repo_root


def load_markdown_chunks(docs_dir: Path | None = None) -> list[dict]:
    root = docs_dir or (repo_root() / "data" / "docs")
    chunks: list[dict] = []
    if not root.exists():
        return chunks
    for path in sorted(root.rglob("*.md")):
        source = str(path.relative_to(repo_root())) if path.is_relative_to(repo_root()) else path.name
        text = path.read_text(encoding="utf-8")
        for index, (title, piece) in enumerate(_split_markdown(text)):
            chunks.append(
                {
                    "id": _chunk_id(source, title, index),
                    "source": source,
                    "title": title,
                    "text": piece,
                }
            )
    return chunks


def _chunk_id(source: str, title: str, index: int) -> str:
    digest = hashlib.sha256(f"{source}|{title}|{index}".encode("utf-8")).hexdigest()
    return digest[:16]


def _split_markdown(text: str, limit: int = 900) -> list[tuple[str, str]]:
    """Return (section title, section text), keeping each heading with its body."""
    sections: list[tuple[str, str]] = []
    title = "Overview"
    body: list[str] = []

    def flush() -> None:
        content = "\n".join(body).strip()
        if content:
            sections.append((title, content))

    for line in text.splitlines():
        if line.startswith("#"):
            flush()
            title = line.lstrip("#").strip() or title
            body = [line]
        else:
            body.append(line)
    flush()
    pieces: list[tuple[str, str]] = []
    for heading, content in sections:
        if len(content) <= limit:
            pieces.append((heading, content))
            continue
        start = 0
        part = 0
        while start < len(content):
            label = heading if part == 0 else f"{heading} continued"
            pieces.append((label, content[start : start + limit].strip()))
            start += limit
            part += 1
    return pieces
