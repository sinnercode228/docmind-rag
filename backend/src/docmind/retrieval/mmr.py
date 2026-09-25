"""Maximal Marginal Relevance: trade relevance for diversity among retrieved chunks."""

from __future__ import annotations

import numpy as np

from docmind.domain import ScoredChunk


def mmr_select(
    candidates: list[ScoredChunk], k: int, lambda_mult: float = 0.6
) -> list[ScoredChunk]:
    """Greedy MMR over candidates that carry embeddings.

    ``lambda_mult`` = 1.0 is pure relevance ranking; 0.0 is pure diversity.
    Candidates without embeddings fall back to relevance order.
    """
    if not 0.0 <= lambda_mult <= 1.0:
        raise ValueError("lambda_mult must be within [0, 1]")
    if k <= 0 or not candidates:
        return []
    if any(c.embedding is None for c in candidates):
        return sorted(candidates, key=lambda c: c.score, reverse=True)[:k]

    matrix = np.vstack([c.embedding for c in candidates if c.embedding is not None])
    relevance = np.array([c.score for c in candidates], dtype=np.float32)
    similarity = matrix @ matrix.T

    selected: list[int] = []
    remaining = list(range(len(candidates)))
    while remaining and len(selected) < k:
        if selected:
            redundancy = similarity[np.ix_(remaining, selected)].max(axis=1)
        else:
            redundancy = np.zeros(len(remaining), dtype=np.float32)
        scores = lambda_mult * relevance[remaining] - (1.0 - lambda_mult) * redundancy
        best = remaining[int(np.argmax(scores))]
        selected.append(best)
        remaining.remove(best)
    return [candidates[i] for i in selected]
