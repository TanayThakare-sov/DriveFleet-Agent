"""Datasheet search tool (stand-in for Project 2's retrieval pipeline).

Markdown datasheets are split into sections ("## ..."), indexed with TF-IDF, and searched by
cosine similarity. If the question names a drive model, results are restricted to that model.
To plug in your Project 2 (embeddings + vector store / RAG), keep the `search_datasheets`
signature and return the same list-of-dicts shape.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from drivefleet.config import get_settings


@dataclass(frozen=True)
class Chunk:
    source: str
    model: str
    section: str
    text: str


def load_chunks(datasheet_dir: Path) -> list[Chunk]:
    chunks: list[Chunk] = []
    for path in sorted(Path(datasheet_dir).glob("*.md")):
        text = path.read_text(encoding="utf-8")
        title = re.search(r"^#\s+(.+?)(?:\s+Datasheet)?\s*$", text, re.MULTILINE)
        model = title.group(1).strip() if title else path.stem
        for part in re.split(r"^##\s+", text, flags=re.MULTILINE)[1:]:
            heading, _, body = part.partition("\n")
            chunks.append(Chunk(path.name, model, heading.strip(), body.strip()))
    return chunks


class DatasheetIndex:
    def __init__(self, chunks: list[Chunk]):
        if not chunks:
            raise ValueError("No datasheets found.")
        self.chunks = chunks
        self.models = sorted({c.model for c in chunks})
        self.vectorizer = TfidfVectorizer(ngram_range=(1, 2), stop_words="english", sublinear_tf=True)
        self.matrix = self.vectorizer.fit_transform(f"{c.model} {c.section}. {c.text}" for c in chunks)

    def search(self, query: str, top_k: int = 3) -> list[dict]:
        named = [m for m in self.models if m.lower() in query.lower()]
        scores = cosine_similarity(self.vectorizer.transform([query]), self.matrix)[0]
        ranked = sorted(range(len(self.chunks)), key=lambda i: scores[i], reverse=True)
        results = []
        for i in ranked:
            c = self.chunks[i]
            if named and c.model not in named:
                continue
            if scores[i] <= 0:
                continue
            results.append({"model": c.model, "section": c.section, "source": c.source,
                            "score": round(float(scores[i]), 4), "text": c.text})
            if len(results) >= top_k:
                break
        return results


@lru_cache(maxsize=4)
def _index(datasheet_dir: str) -> DatasheetIndex:
    return DatasheetIndex(load_chunks(Path(datasheet_dir)))


def search_datasheets(query: str, top_k: int = 3, datasheet_dir: Path | None = None) -> dict:
    top_k = max(1, min(int(top_k), 8))
    d = Path(datasheet_dir or get_settings().datasheet_dir)
    index = _index(str(d.resolve()))
    return {"query": query, "known_models": index.models, "results": index.search(query, top_k)}
