"""Wrap a ``marshal.dumps`` payload into a runnable ``.pyc`` file.

A ``.pyc`` file is just::

    MAGIC_NUMBER | FLAGS | (mtime, size) or source-hash | marshalled code

``marshal.dumps(code_object)`` produces the last part; this module prepends the
header so the interpreter accepts and runs the result.

Usage::

    import marshal
    from marshal2pyc import dumps_to_pyc

    payload = marshal.dumps(compile("print('hi')", "<x>", "exec"))
    dumps_to_pyc(payload, "hi.pyc")

    # then: python hi.pyc
"""

from __future__ import annotations

import importlib.util
import marshal
import struct
import types
from pathlib import Path
from typing import Union

__all__ = [
    "MAGIC_NUMBER",
    "build_pyc",
    "dumps_to_pyc",
    "convert",
    "is_code_payload",
]

# Magic number of the interpreter that is running this code.
MAGIC_NUMBER: bytes = importlib.util.MAGIC_NUMBER

# PEP 552 header flags.
FLAG_HASH_BASED = 0b01
FLAG_CHECK_SOURCE = 0b10

# PEP 552 landed in 3.7; before that the header was 12 bytes (no flags field).
FIRST_PEP552_MAGIC = 3394

PathLike = Union[str, "Path"]


def _magic_number_int(magic: bytes) -> int:
    """Interpret the first two bytes of a pyc magic as its numeric magic."""
    if len(magic) < 2:
        raise ValueError("magic must be at least 2 bytes")
    return int.from_bytes(magic[:2], "little")


def default_header_size(magic: bytes = MAGIC_NUMBER) -> int:
    """Return the pyc header size implied by *magic* (12 before 3.7, else 16)."""
    return 16 if _magic_number_int(magic) >= FIRST_PEP552_MAGIC else 12


def is_code_payload(payload: bytes) -> bool:
    """Return True if *payload* unmarshals to a code object."""
    try:
        return isinstance(marshal.loads(payload), types.CodeType)
    except (EOFError, ValueError, TypeError):
        return False


def _build_header(
    magic: bytes,
    *,
    header_size: int,
    hash_based: bool,
    source_mtime: int,
    source_size: int,
    source_hash: bytes | None,
) -> bytes:
    if len(magic) != 4:
        raise ValueError(f"magic must be exactly 4 bytes, got {len(magic)}")
    if header_size == 12:
        if hash_based:
            raise ValueError("hash-based pycs need a 16-byte header (Python 3.7+)")
        return (
            magic
            + struct.pack("<I", source_mtime & 0xFFFFFFFF)
            + struct.pack("<I", source_size & 0xFFFFFFFF)
        )
    if header_size != 16:
        raise ValueError(f"header_size must be 12 or 16, got {header_size}")

    if hash_based:
        if source_hash is None:
            # Unchecked hash-based pyc: the interpreter trusts the file as-is.
            flags = FLAG_HASH_BASED
            source_hash = bytes(8)
        else:
            flags = FLAG_HASH_BASED | FLAG_CHECK_SOURCE
            if len(source_hash) != 8:
                raise ValueError("source_hash must be 8 bytes (siphash-128/8)")
        return magic + struct.pack("<I", flags) + source_hash

    flags = 0
    return (
        magic
        + struct.pack("<I", flags)
        + struct.pack("<I", source_mtime & 0xFFFFFFFF)
        + struct.pack("<I", source_size & 0xFFFFFFFF)
    )


def build_pyc(
    payload: bytes,
    *,
    magic: bytes = MAGIC_NUMBER,
    hash_based: bool = False,
    source_mtime: int = 0,
    source_size: int = 0,
    source_hash: bytes | None = None,
    header_size: int | None = None,
    validate: bool = True,
) -> bytes:
    """Return the full bytes of a ``.pyc`` built from marshal *payload*.

    ``header_size`` defaults to the value implied by *magic* (16 on 3.7+).
    Set ``validate=False`` for payloads produced by another Python version.
    """
    if not isinstance(payload, (bytes, bytearray, memoryview)):
        raise TypeError(f"payload must be bytes-like, got {type(payload).__name__}")
    payload = bytes(payload)

    # Supplying a source hash only makes sense for hash-based pycs.
    if source_hash is not None:
        hash_based = True

    if validate and not is_code_payload(payload):
        raise TypeError(
            "payload does not unmarshal to a code object; "
            "pass validate=False if it comes from a different Python version"
        )

    if header_size is None:
        header_size = default_header_size(magic)

    header = _build_header(
        magic,
        header_size=header_size,
        hash_based=hash_based,
        source_mtime=source_mtime,
        source_size=source_size,
        source_hash=source_hash,
    )
    return header + payload


def dumps_to_pyc(
    payload: bytes,
    out_path: PathLike | None = None,
    **kwargs,
) -> bytes:
    """Build a ``.pyc`` from marshal bytes and optionally write it to *out_path*."""
    data = build_pyc(payload, **kwargs)
    if out_path is not None:
        Path(out_path).write_bytes(data)
    return data


# Friendly alias.
convert = dumps_to_pyc
