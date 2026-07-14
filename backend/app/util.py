from collections.abc import Iterator, Sequence
from typing import TypeVar

T = TypeVar("T")


def chunks(seq: Sequence[T], size: int) -> Iterator[Sequence[T]]:
    for i in range(0, len(seq), size):
        yield seq[i : i + size]
