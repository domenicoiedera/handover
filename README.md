# handover

**Your agent's handoff is a promise. This one carries proof.**

[![ci](https://github.com/domenicoiedera/handover/actions/workflows/ci.yml/badge.svg)](https://github.com/domenicoiedera/handover/actions/workflows/ci.yml)
[![license: MIT](https://img.shields.io/badge/license-MIT-black.svg)](LICENSE)
[![python 3.10+](https://img.shields.io/badge/python-3.10%2B-black.svg)](pyproject.toml)

A long agent session ends. The next one starts from a summary: *"the parser is in `src/parse.py`, the migration is done, `legacy.py` was deleted."* Some of that was true when it was written. Nothing in the summary says which parts stopped being true.

`handover` makes a handoff a **packet with claims**, seals it, and re-checks every claim before anyone is allowed to resume from it.

```
$ handover capture --from handover.src.json     # pin claims to the bytes on disk
$ handover check handover.json                  # re-verify, later, on any machine

seal OK (069f691c022a...), 4 check(s)
STALE  file    src/app.py  bytes changed (af4f8628d6d5... -> 74834ed405e9...)
STALE: 1 of 4 claim(s) no longer hold
$ echo $?
1
```

```
$ handover resume handover.json
refusing to resume: 1 of 4 claim(s) no longer hold.
```

## The claim, not the summary

A fact in a packet is prose plus optional **claims**. There are four kinds:

| kind | what it asserts |
|------|-----------------|
| `file` | this path exists and its bytes hash to this sha256 |
| `absent` | this path must not exist |
| `text` | this file still contains this string |
| `git` | this ref still resolves to this commit |

```json
{
  "facts": [
    { "text": "pay() lives in src/app.py and takes one argument",
      "claims": [ { "kind": "file", "path": "src/app.py" },
                  { "kind": "text", "path": "src/app.py", "contains": "def pay(x)" } ] },
    { "text": "legacy.py was deleted in the migration",
      "claims": [ { "kind": "absent", "path": "src/legacy.py" } ] }
  ],
  "decisions": [ { "text": "keep the gate advisory", "why": "no process mediation yet" } ],
  "open": [ { "text": "add a pre-commit hook", "owner": "engineer" } ],
  "owners": [ { "seat": "engineer", "paths": ["src/**"] } ]
}
```

You write the claims once. `capture` fills in the hashes and commits from the repository as it is right now - and **refuses to write a brief that is already false**.

## Install

Not on PyPI, and worth knowing why: the PyPI project named `handover` is an **unrelated tool by another author** (v1.2.1). `pip install handover` installs theirs, not this. Install from the release URL or the tag below - all four channels were executed on a clean machine for v0.1.0, and each printed `handover 0.1.0`:

```bash
# 1. the release wheel (no build, no account)
pip install https://github.com/domenicoiedera/handover/releases/download/v0.1.0/handover-0.1.0-py3-none-any.whl

# 2. straight from the tag, build locally
pip install "git+https://github.com/domenicoiedera/handover.git@v0.1.0"

# 3. isolated, on your PATH
pipx install https://github.com/domenicoiedera/handover/releases/download/v0.1.0/handover-0.1.0-py3-none-any.whl

# 4. uv
uv tool install https://github.com/domenicoiedera/handover/releases/download/v0.1.0/handover-0.1.0-py3-none-any.whl
```

```bash
handover --version    # handover 0.1.0
```

For development: `git clone https://github.com/domenicoiedera/handover && cd handover && pip install -e .`

Zero runtime dependencies. Python 3.10+ (3.10, 3.11, 3.12, 3.13 tested on Linux, macOS and Windows). No network calls, ever.

## Fail-closed by construction

Five rules, all enforced in code rather than in documentation:

1. **A claim that cannot be evaluated is a failure.** `UNKNOWN` is not "probably fine".
2. **Capture refuses to seal a lie.** Every claim is evaluated before the packet is written; a false one exits 2 and writes nothing.
3. **A packet with no claims is `UNCHECKED`, not verified.** A brief nobody can check is not a handoff, it is a rumour.
4. **The body is sealed.** Editing a fact after capture is `SEAL-INVALID` - the packet cannot be quietly improved to match a changed repository.
5. **Paths cannot escape the packet root.** `../secrets`, absolute paths and symlinks pointing outside are refused.

Exit codes: `0` verified, `1` stale or tampered, `2` refused (malformed, or a claim that cannot be built).

## Proven, not promised

- **128 tests** (`python -m unittest discover -s tests -t .`), no mocks around the filesystem: every check runs against real files and a real git repo.
- **8 mutation guards** (`tools/mutation_check.py`): each one breaks a single promised rule and the suite must go red. All 8 are killed - a rule that survives its own mutant is documentation, not enforcement.
- **7 adversarial probes** before publication, all refused: edited bytes, a tampered packet body, `..` escape, symlink escape, a packet with no claims, an unreadable file, and a claim that was already false at capture.
- **Zero runtime dependencies**, confirmed by the wheel's empty `Requires:`.
- CI runs the same suite on Python 3.10-3.13 across Linux, macOS and Windows.

## In CI

```yaml
- name: the brief must still be true
  run: |
    pip install https://github.com/domenicoiedera/handover/releases/download/v0.1.0/handover-0.1.0-py3-none-any.whl
    handover check docs/handover.json
```

Commit the packet next to the code it describes. A stale brief now turns the build red instead of misleading the next agent.

## What it is not

- **Not a memory store.** It keeps no database and calls no model. It carries *provenance*, not embeddings. Point it at the brief your agent already writes.
- **Not a gate on actions.** That is a different failure: see the sibling tools below.
- **Not proof of authorship.** The seal proves the packet has not changed since it was sealed. Commit it to git and the repository history supplies the rest. See [docs/threat-model.md](docs/threat-model.md).

## Format

A packet is one JSON document, canonicalised (sorted keys, no whitespace) and sealed with sha256 over everything except the seal. Full schema and exit codes: [docs/format.md](docs/format.md).

## The family

Three tools, three moments in an agent's life:

| | question | repository |
|---|---|---|
| **gatesmith** | was this change allowed to land? | [domenicoiedera/gatesmith](https://github.com/domenicoiedera/gatesmith) |
| **nullaosta** | was this action allowed to happen - and can I prove it after? | [domenicoiedera/nullaosta](https://github.com/domenicoiedera/nullaosta) |
| **handover** | is the context I am resuming from still true? | this one |

## License

MIT.
