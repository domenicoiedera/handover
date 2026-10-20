# Changelog

All notable changes are recorded here. Dates are UTC.

## 0.1.0 - 2026-10-20

First release.

- `capture` builds a sealed packet from a source spec, pinning `file` hashes and `git` commits, and refuses to seal a claim that is already false.
- `check` re-evaluates every claim; `OK`, `STALE`, `MISSING`, `UNKNOWN`, with `UNKNOWN` counted as failure.
- `resume` prints the brief and refuses (exit 1) unless every claim holds; `--force` prints it behind a warning banner.
- `SEAL-INVALID` on any post-capture edit to the packet body.
- Four claim kinds: `file`, `absent`, `text`, `git`.
- Path confinement to the packet root, including symlink escapes.
- Zero runtime dependencies; Python 3.10-3.13.
