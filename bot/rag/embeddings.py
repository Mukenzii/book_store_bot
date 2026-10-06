"""Replaceable embedding interface for hybrid retrieval.

Retrieval works without embeddings (PostgreSQL full-text only). A provider adds
a vector rerank; swapping providers means re-running the importer with
`--embeddings <name>` — chunks whose stored `embedding_model` differs are
re-embedded, everything else is untouched.

Providers:
  NoEmbeddings      — disabled (default).
  HashingEmbeddings — free, local, deterministic character-n-gram hashing over
                      the script-normalised text. Good for tests and as an
                      offline fuzzy matcher; not a semantic model.
  OpenAIEmbeddings  — paid API. Refuses to run unless explicitly allowed, so a
                      bulk import can never spend money by accident.
"""

import hashlib
import math
from typing import Protocol

from bot.rag.normalize import search_key


class EmbeddingProvider(Protocol):
    name: str  # stored as book_chunks.embedding_model; "" = disabled

    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class NoEmbeddings:
    name = ""

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return []


class HashingEmbeddings:
    def __init__(self, dim: int = 256, n: int = 4) -> None:
        self.dim = dim
        self.n = n
        self.name = f"hashing-{n}gram-{dim}"

    def _vector(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        key = f" {search_key(text)} "
        for i in range(max(0, len(key) - self.n + 1)):
            h = int.from_bytes(hashlib.blake2b(key[i : i + self.n].encode(), digest_size=4).digest(), "big")
            vec[h % self.dim] += 1.0 if h & 1 else -1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(t) for t in texts]


class PaidEmbeddingsNotAllowed(RuntimeError):
    pass


class OpenAIEmbeddings:
    def __init__(self, client, model: str, *, allow_paid: bool, batch: int = 64) -> None:
        if not allow_paid:
            raise PaidEmbeddingsNotAllowed(
                "OpenAI embeddings cost money; pass allow_paid=True (importer: --allow-paid)."
            )
        self._client = client
        self.name = f"openai:{model}"
        self._model = model
        self._batch = batch

    async def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), self._batch):
            resp = await self._client.embeddings.create(model=self._model, input=texts[i : i + self._batch])
            out.extend(d.embedding for d in resp.data)
        return out


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


def get_provider(name: str, *, allow_paid: bool = False, client=None, model: str = "") -> EmbeddingProvider:
    """Build a provider by config name: "none" | "hashing" | "openai"."""
    name = (name or "none").strip().lower()
    if name in ("", "none"):
        return NoEmbeddings()
    if name == "hashing":
        return HashingEmbeddings()
    if name == "openai":
        return OpenAIEmbeddings(client, model, allow_paid=allow_paid)
    raise ValueError(f"Unknown embedding provider: {name!r}")
