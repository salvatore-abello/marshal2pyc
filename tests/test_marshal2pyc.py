"""Tests for marshal2pyc."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import marshal
import struct
import subprocess
import sys

import pytest

import marshal2pyc


def pyc_code(src="x = 6 * 7\n"):
    return compile(src, "<test>", "exec")


def marshal_code(src="x = 6 * 7\n"):
    return marshal.dumps(pyc_code(src))


def run_pyc(path):
    """Execute a .pyc as __main__ in a fresh interpreter and return stdout."""
    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            "import runpy, sys; runpy.run_path(sys.argv[1], run_name='__main__')",
            str(path),
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout


def test_header_magic_and_flags():
    data = marshal2pyc.dumps_to_pyc(marshal_code())
    assert data[:4] == marshal2pyc.MAGIC_NUMBER
    assert struct.unpack("<I", data[4:8])[0] == 0


def test_timestamp_header_roundtrip(tmp_path):
    out = tmp_path / "demo.pyc"
    marshal2pyc.dumps_to_pyc(
        marshal_code("print('hi', 6 * 7)\n"),
        out,
        source_mtime=1_700_000_000,
        source_size=123,
    )
    assert run_pyc(out) == "hi 42\n"
    header = out.read_bytes()[:16]
    assert struct.unpack("<I", header[8:12])[0] == 1_700_000_000
    assert struct.unpack("<I", header[12:16])[0] == 123


def test_hash_header_roundtrip(tmp_path):
    out = tmp_path / "hash.pyc"
    marshal2pyc.dumps_to_pyc(marshal_code("print('hash mode')\n"), out, hash_based=True)
    assert run_pyc(out) == "hash mode\n"
    header = out.read_bytes()[:16]
    assert struct.unpack("<I", header[4:8])[0] == marshal2pyc.FLAG_HASH_BASED
    assert header[8:16] == bytes(8)


def test_checked_hash_header(tmp_path):
    digest = bytes(range(8))
    out = tmp_path / "checked.pyc"
    marshal2pyc.dumps_to_pyc(marshal_code(), out, source_hash=digest)
    header = out.read_bytes()[:16]
    flags = struct.unpack("<I", header[4:8])[0]
    assert flags == marshal2pyc.FLAG_HASH_BASED | marshal2pyc.FLAG_CHECK_SOURCE
    assert header[8:16] == digest


def test_legacy_12_byte_header():
    payload = marshal_code()
    data = marshal2pyc.build_pyc(payload, header_size=12)
    assert len(data) == 12 + len(payload)
    with pytest.raises(ValueError):
        marshal2pyc.build_pyc(payload, header_size=12, hash_based=True)


def test_import_via_sourceless_loader(tmp_path):
    out = tmp_path / "mod.pyc"
    marshal2pyc.dumps_to_pyc(marshal_code("value = 42\n"), out)
    loader = importlib.machinery.SourcelessFileLoader("mod", str(out))
    spec = importlib.util.spec_from_loader("mod", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    assert mod.value == 42


def test_convert_alias_writes_file(tmp_path):
    out = tmp_path / "alias.pyc"
    marshal2pyc.convert(marshal_code(), out)
    assert out.exists()


def test_rejects_non_code_payload():
    with pytest.raises(TypeError):
        marshal2pyc.build_pyc(marshal.dumps({"not": "code"}))


def test_rejects_garbage_payload():
    with pytest.raises(TypeError):
        marshal2pyc.build_pyc(b"\x00\x01\x02")


def test_validate_false_skips_decode():
    raw = b"not marshal at all"
    data = marshal2pyc.build_pyc(raw, validate=False)
    assert data.endswith(raw)


def test_rejects_bad_magic_length():
    with pytest.raises(ValueError):
        marshal2pyc.build_pyc(marshal_code(), magic=b"\x01\x02")


def test_rejects_bad_source_hash_length():
    with pytest.raises(ValueError):
        marshal2pyc.build_pyc(marshal_code(), source_hash=b"short")


def test_cli_file_to_file(tmp_path):
    payload = tmp_path / "payload.bin"
    payload.write_bytes(marshal_code("print('cli')\n"))
    out = tmp_path / "cli.pyc"
    proc = subprocess.run(
        [sys.executable, "-m", "marshal2pyc", str(payload), "-o", str(out)],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert run_pyc(out) == "cli\n"


def test_cli_stdin_to_stdout(tmp_path):
    payload = tmp_path / "payload.bin"
    payload.write_bytes(marshal_code("print('piped')\n"))
    with payload.open("rb") as fh:
        proc = subprocess.run(
            [sys.executable, "-m", "marshal2pyc"], stdin=fh, capture_output=True
        )
    assert proc.returncode == 0, proc.stderr.decode()
    out = tmp_path / "piped.pyc"
    out.write_bytes(proc.stdout)
    assert run_pyc(out) == "piped\n"


def test_cli_from_source(tmp_path):
    src = tmp_path / "hello.py"
    src.write_text("print('from source')\n")
    proc = subprocess.run(
        [sys.executable, "-m", "marshal2pyc", "--from-source", str(src)],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert run_pyc(tmp_path / "hello.pyc") == "from source\n"


def test_cli_hash_based_flag(tmp_path):
    payload = tmp_path / "p.bin"
    payload.write_bytes(marshal_code())
    out = tmp_path / "hb.pyc"
    proc = subprocess.run(
        [sys.executable, "-m", "marshal2pyc", str(payload), "-o", str(out), "--hash-based"],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert struct.unpack("<I", out.read_bytes()[4:8])[0] == marshal2pyc.FLAG_HASH_BASED


def test_cli_rejects_bad_payload(tmp_path):
    bad = tmp_path / "bad.bin"
    bad.write_bytes(b"garbage")
    proc = subprocess.run(
        [sys.executable, "-m", "marshal2pyc", str(bad)],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 2
    assert "error:" in proc.stderr
    assert "Traceback" not in proc.stderr
