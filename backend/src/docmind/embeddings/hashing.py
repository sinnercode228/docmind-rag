"""Deterministic, dependency-free embedder based on the hashing trick.

It is *lexical*, not semantic: unigrams, bigrams and character trigrams are hashed into a
fixed-size signed vector. That makes it perfect for tests and offline demos (stable output,
no network, no model download) and a surprisingly decent baseline for keyword-heavy corpora.
"""

from __future__ import annotations

import hashlib
import itertools
import math
from collections import Counter

import numpy as np

from docmind.domain import Vector
from docmind.embeddings.base import l2_normalize
from docmind.text import STOPWORDS, stem, tokenize


def _bucket(feature: str, dim: int) -> tuple[int, float]:
    digest = hashlib.blake2b(feature.encode(), digest_size=8).digest()
    value = int.from_bytes(digest, "little")
    return value % dim, (1.0 if (value >> 63) & 1 else -1.0)


class HashingEmbedder:
    def __init__(self, dim: int = 384) -> None:
        if dim < 16:
            raise ValueError("dim must be >= 16")
        self._dim = dim

    @property
    def dim(self) -> int:
        return self._dim

    @property
    def name(self) -> str:
        return f"hashing-{self._dim}"

    def _features(self, text: str) -> Counter[str]:
        words = [stem(t) for t in tokenize(text) if t not in STOPWORDS]
        features: Counter[str] = Counter()
        for word in words:
            features[f"w:{word}"] += 2
            padded = f"<{word}>"
            for i in range(len(padded) - 2):
                features[f"c:{padded[i : i + 3]}"] += 1
        for left, right in itertools.pairwise(words):
            features[f"b:{left}_{right}"] += 1
        return features

    def embed(self, text: str) -> Vector:
        vector = np.zeros(self._dim, dtype=np.float32)
        for feature, count in self._features(text).items():
            index, sign = _bucket(feature, self._dim)
            vector[index] += sign * (1.0 + math.log(count))
        return l2_normalize(vector)

    async def embed_documents(self, texts: list[str]) -> list[Vector]:
        return [self.embed(text) for text in texts]

    async def embed_query(self, text: str) -> Vector:
        return self.embed(text)
