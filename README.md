# marshal2pyc

Turn a `marshal.dumps(...)` payload into a runnable `.pyc` file.

A `.pyc` is just a header followed by the marshalled code object:

```
MAGIC_NUMBER (4) | FLAGS (4) | mtime+size or source hash (8) | marshal payload
```

`marshal.dumps(code)` gives you the payload; this tool prepends the header.

## Library

```python
import marshal
from marshal2pyc import dumps_to_pyc

payload = marshal.dumps(compile("print('hi')", "<x>", "exec"))
dumps_to_pyc(payload, "hi.pyc")
```

Then run it:

```bash
python hi.pyc
```

`build_pyc(payload, ...)` returns the bytes without writing a file.
`convert` is an alias of `dumps_to_pyc`.

## CLI

```bash
# payload file -> payload.pyc
python -m marshal2pyc payload.bin

# explicit output
python -m marshal2pyc payload.bin -o out.pyc

# stdin -> stdout
cat payload.bin | python -m marshal2pyc > out.pyc

# compile a .py file directly
python -m marshal2pyc --from-source hello.py
```

Useful flags:

- `--magic HEX` : override the 4-byte magic (default: current interpreter)
- `--hash-based` : PEP 552 hash-based header (unchecked)
- `--source-hash HEX16` : checked hash-based header with an 8-byte hash
- `--mtime N`, `--source-size N` : timestamp-based header fields
- `--header-size {12,16}` : force a legacy or modern header
- `--no-validate` : skip the "payload is a code object" check, needed when the
  payload comes from a different Python version
- `--info` : print payload details to stderr

## Notes

- The magic number must match the interpreter that will run the `.pyc`.
  Payloads are also version-specific: a code object marshalled by 3.11 will not
  load in 3.12. Use `--no-validate` to wrap such payloads anyway.
- `--from-source` compiles with the running interpreter, so the result always
  matches it.

## Tests

```bash
python -m pytest
```
