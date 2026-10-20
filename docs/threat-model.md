# Threat model

What `handover` stops, what it does not stop, and what it assumes.

## Stops

- **Resuming from a brief whose evidence has moved.** Every claim is re-evaluated on `check`; a changed file, a deleted file that came back, a missing line of code or a moved git ref makes the packet stale and `resume` exits 1.
- **Quietly editing the brief to match reality.** The body is sealed with sha256; any edit after capture is `SEAL-INVALID` and the packet is refused before its claims are even considered.
- **Writing a brief that is already false.** `capture` evaluates every claim against the current tree and refuses to seal a claim that does not hold.
- **Passing off an unverifiable brief as verified.** A packet with zero claims is `UNCHECKED` and exits 1 - it can be read with `resume --force`, but never labelled verified.
- **Reading outside the packet's tree.** Relative paths are resolved and must stay under the packet root; `..` escapes, absolute paths elsewhere and symlinks pointing out are refused.

## Does not stop

- **A deliberate liar who re-seals.** Someone who edits a packet and runs `capture` again produces a validly sealed packet with new evidence. The seal proves *integrity since sealing*, not authorship. Commit packets to git if you need history; a signature layer is not in v0.1.
- **An agent that ignores the tool.** `handover` is a CLI. An agent that never runs `check` is not constrained by it. Enforcement belongs to the caller (a CI job, a hook, a supervisor).
- **False prose.** Claims cover what can be checked mechanically: bytes, absence, substrings, refs. "The parser handles nested cases" is prose unless you attach a claim; prose is labelled `unchecked assertion` in the brief, and a packet made only of prose is `UNCHECKED`.
- **Writer-asserted time.** `created_at` is the writer's clock, not a trusted timestamp. Keep packets in git if the time matters.
- **Rich semantic drift.** A refactor that preserves the exact bytes of a file is not detected for that file; a refactor that changes them is. Claims see what they are pointed at, nothing else.
- **Secrets in the packet.** Facts are plain text and are meant to be committed. Do not put credentials in a fact.

## Assumptions

- The packet directory is the repository (or a subdirectory of it). `--root` can point elsewhere, deliberately.
- `git`, when used, is on `PATH` and answers for the tree. If git cannot answer, the claim is `MISSING`/`UNKNOWN`, never `OK`.
- The filesystem is not being mutated concurrently with a check. A check is a point-in-time observation.

## Reporting

Open an issue at https://github.com/domenicoiedera/handover/issues. Please do not include real credentials or private repository content.
