"""Seed handling & reproducibility.

A single *master seed* drives the whole track.  Every module receives its own
independent random stream derived from ``(master_seed, module_name)`` so that

* the same seed always yields exactly the same track, and
* regenerating one module (e.g. only the bass with a new seed) never changes
  the output of the other modules.
"""

from __future__ import annotations

import hashlib
import random
import secrets

import numpy as np

MAX_SEED = 2**31 - 1


def generate_seed() -> int:
    """Return a fresh random seed (printed to the user so the track can be reproduced)."""
    return secrets.randbelow(MAX_SEED) + 1


def derive_seed(seed: int, *names: object) -> int:
    """Deterministically derive a 64-bit sub-seed from a master seed and a name path."""
    text = ":".join([str(int(seed))] + [str(n) for n in names])
    return int.from_bytes(hashlib.sha256(text.encode("utf-8")).digest()[:8], "big")


class SeedManager:
    """Factory for named, independent and reproducible random streams."""

    def __init__(self, seed: int | None = None):
        self.seed = int(seed) if seed is not None else generate_seed()

    def rng(self, *names: object) -> random.Random:
        """Python ``random.Random`` stream for the given name path."""
        return random.Random(derive_seed(self.seed, *names))

    def np_rng(self, *names: object) -> np.random.Generator:
        """NumPy ``Generator`` stream for the given name path."""
        return np.random.default_rng(derive_seed(self.seed, *names))

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return f"SeedManager(seed={self.seed})"
