"""CLI: wrap a ``marshal.dumps`` payload into a runnable ``.pyc``.

Examples::

    python -m marshal2pyc payload.bin -o out.pyc
    cat payload.bin | python -m marshal2pyc > out.pyc
    python -m marshal2pyc --from-source hello.py
"""

from __future__ import annotations

import argparse
import marshal
import sys
import types
from pathlib import Path

from . import MAGIC_NUMBER, build_pyc


def _parse_magic(text: str) -> bytes:
    try:
        raw = bytes.fromhex(text.lower().removeprefix("0x").replace(" ", ""))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid hex magic: {text!r}") from exc
    if len(raw) != 4:
        raise argparse.ArgumentTypeError(
            f"magic must be 4 bytes (8 hex chars), got {len(raw)} bytes"
        )
    return raw


def _parse_hash(text: str) -> bytes:
    try:
        raw = bytes.fromhex(text.lower().removeprefix("0x").replace(" ", ""))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid hex hash: {text!r}") from exc
    if len(raw) != 8:
        raise argparse.ArgumentTypeError(f"source hash must be 8 bytes, got {len(raw)}")
    return raw


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="marshal2pyc",
        description=(
            "Wrap a marshal.dumps payload (a marshalled code object) into a .pyc "
            "file that Python can load or run directly."
        ),
    )
    p.add_argument(
        "payload",
        nargs="?",
        type=Path,
        help="file with the raw marshal bytes (omit to read stdin)",
    )
    p.add_argument(
        "-o",
        "--output",
        type=Path,
        help="output .pyc path (default: <payload>.pyc, or stdout when reading stdin)",
    )
    p.add_argument(
        "--from-source",
        type=Path,
        metavar="FILE.py",
        help="compile this .py file and wrap the result instead of reading marshal bytes",
    )
    p.add_argument(
        "--magic",
        type=_parse_magic,
        default=MAGIC_NUMBER,
        help="4-byte pyc magic as hex (default: this interpreter, %(default)s)",
    )
    p.add_argument(
        "--hash-based",
        action="store_true",
        help="PEP 552 hash-based header (unchecked, source hash zeroed)",
    )
    p.add_argument(
        "--source-hash",
        type=_parse_hash,
        metavar="HEX16",
        help="8-byte source hash for a checked hash-based header (implies --hash-based)",
    )
    p.add_argument(
        "--mtime",
        type=int,
        default=0,
        help="source mtime for a timestamp-based header (default: 0)",
    )
    p.add_argument(
        "--source-size",
        type=int,
        default=0,
        help="source size for a timestamp-based header (default: 0)",
    )
    p.add_argument(
        "--header-size",
        type=int,
        choices=(12, 16),
        help="override the header size (12 pre-3.7, 16 on 3.7+)",
    )
    p.add_argument(
        "--no-validate",
        action="store_true",
        help="do not require the payload to unmarshal as a code object "
        "(needed for payloads from a different Python version)",
    )
    p.add_argument(
        "--info",
        action="store_true",
        help="print payload details to stderr",
    )
    return p


def _load_payload(args: argparse.Namespace) -> tuple[bytes, Path | None]:
    if args.from_source is not None:
        source = args.from_source.read_bytes()
        code = compile(source, str(args.from_source), "exec", dont_inherit=True)
        return marshal.dumps(code), args.from_source.with_suffix(".pyc")
    if args.payload is None:
        return sys.stdin.buffer.read(), None
    return args.payload.read_bytes(), args.payload.with_suffix(".pyc")


def _print_info(payload: bytes) -> None:
    print(f"payload: {len(payload)} bytes", file=sys.stderr)
    try:
        obj = marshal.loads(payload)
    except (EOFError, ValueError, TypeError) as exc:
        print(f"payload does not unmarshal: {exc}", file=sys.stderr)
        return
    print(f"unmarshals to: {type(obj).__name__}", file=sys.stderr)
    if isinstance(obj, types.CodeType):
        print(f"code object: {obj.co_name!r} ({obj.co_filename!r})", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    if args.payload is not None and args.from_source is not None:
        print("error: give either a payload file or --from-source, not both", file=sys.stderr)
        return 2

    try:
        payload, default_out = _load_payload(args)
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.info:
        _print_info(payload)

    hash_based = args.hash_based or args.source_hash is not None

    try:
        data = build_pyc(
            payload,
            magic=args.magic,
            hash_based=hash_based,
            source_mtime=args.mtime,
            source_size=args.source_size,
            source_hash=args.source_hash,
            header_size=args.header_size,
            validate=not args.no_validate,
        )
    except (EOFError, ValueError, TypeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    out = args.output if args.output is not None else default_out
    if out is None:
        sys.stdout.buffer.write(data)
        sys.stdout.buffer.flush()
        return 0

    try:
        out.write_bytes(data)
    except OSError as exc:
        print(f"error: cannot write {out}: {exc}", file=sys.stderr)
        return 2
    print(f"wrote {out} ({len(data)} bytes)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
