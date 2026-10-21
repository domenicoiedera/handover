"""Claims: the checkable half of a fact.

Four kinds, deliberately few:

``file``    a path must exist and its bytes must hash to a given sha256
``absent``  a path must not exist
``text``    a path must still contain a given string
``git``     a ref must still resolve to a given commit

A claim that cannot be evaluated is never treated as satisfied. Unknown is a
failure in this tool, not a shrug.
"""

from __future__ import annotations

from pathlib import Path

from .packet import PacketError, git, sha256_file

OK = "OK"
STALE = "STALE"
MISSING = "MISSING"
UNKNOWN = "UNKNOWN"
KINDS = ("file", "absent", "text", "git")


class ClaimError(PacketError):
    """A claim is malformed or cannot be pinned."""


def _resolve(root: Path, rel: object) -> Path:
    if not isinstance(rel, str) or not rel.strip():
        raise ClaimError("claim needs a non-empty 'path'")
    candidate = (root / rel).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise ClaimError(f"path escapes the packet root: {rel!r}") from exc
    return candidate


def pin_claims(root: Path, claims: object) -> list[dict]:
    """Fill in what can be read from disk right now. Nothing is invented."""
    if claims is None:
        return []
    if not isinstance(claims, list):
        raise ClaimError("claims must be a list")
    pinned: list[dict] = []
    for index, claim in enumerate(claims):
        if not isinstance(claim, dict):
            raise ClaimError(f"claims[{index}] must be an object")
        kind = claim.get("kind")
        if kind not in KINDS:
            raise ClaimError(f"claims[{index}]: unknown kind {kind!r} (expected one of {', '.join(KINDS)})")
        entry = dict(claim)
        if kind in ("file", "absent", "text"):
            path = _resolve(root, claim.get("path"))
            if kind == "file" and not isinstance(claim.get("sha256"), str):
                if not path.is_file():
                    raise ClaimError(f"cannot pin a file claim for something that is not a file: {claim.get('path')!r}")
                entry["sha256"] = sha256_file(path)
            if kind == "text" and not isinstance(claim.get("contains"), str):
                raise ClaimError(f"claims[{index}]: a text claim needs 'contains'")
        if kind == "git":
            ref = claim.get("ref")
            if not isinstance(ref, str) or not ref.strip():
                raise ClaimError(f"claims[{index}]: a git claim needs 'ref'")
            if not isinstance(claim.get("sha"), str):
                resolved = git(root, "rev-parse", "--verify", f"{ref}^{{commit}}")
                if resolved is None:
                    raise ClaimError(f"cannot pin a git claim: ref {ref!r} does not resolve in {root}")
                entry["sha"] = resolved
        pinned.append(entry)
    return pinned


def evaluate(root: Path, claim: dict) -> dict:
    """Return {'status': ..., 'kind': ..., 'target': ..., 'detail': ...}."""
    kind = claim.get("kind")
    target = claim.get("path") if kind in ("file", "absent", "text") else claim.get("ref")
    result = {"kind": kind, "target": target, "status": OK, "detail": ""}

    if kind not in KINDS:
        raise ClaimError(f"unknown claim kind {kind!r}")

    if kind == "absent":
        path = _resolve(root, claim.get("path"))
        if path.exists():
            result.update(status=STALE, detail="path exists and must not")
        return result

    if kind in ("file", "text"):
        path = _resolve(root, claim.get("path"))
        if not path.exists():
            result.update(status=MISSING, detail="path is gone")
            return result
        if not path.is_file():
            result.update(status=UNKNOWN, detail="path is not a regular file")
            return result
        try:
            if kind == "file":
                expected = claim.get("sha256")
                if not isinstance(expected, str) or len(expected) != 64:
                    result.update(status=UNKNOWN, detail="claim carries no usable sha256")
                    return result
                actual = sha256_file(path)
                if actual != expected:
                    result.update(status=STALE, detail=f"bytes changed ({expected[:12]}... -> {actual[:12]}...)")
                return result
            needle = claim.get("contains")
            if not isinstance(needle, str) or not needle:
                result.update(status=UNKNOWN, detail="claim carries no usable 'contains'")
                return result
            text = path.read_text(encoding="utf-8", errors="replace")
            if needle not in text:
                result.update(status=STALE, detail="expected text is no longer present")
            return result
        except OSError as exc:
            result.update(status=UNKNOWN, detail=f"cannot read: {exc.strerror or exc}")
            return result

    ref = claim.get("ref")
    expected = claim.get("sha")
    if not isinstance(expected, str) or len(expected) < 7:
        result.update(status=UNKNOWN, detail="claim carries no usable sha")
        return result
    actual = git(root, "rev-parse", "--verify", f"{ref}^{{commit}}")
    if actual is None:
        result.update(status=MISSING, detail=f"ref {ref!r} no longer resolves")
        return result
    if actual != expected:
        result.update(status=STALE, detail=f"ref moved ({expected[:7]} -> {actual[:7]})")
    return result


def evaluate_packet(root: Path, packet: dict) -> list[dict]:
    results = []
    facts = packet.get("facts", [])
    any_claim = any(fact.get("claims") for fact in facts)
    for fact_index, fact in enumerate(facts):
        claims = fact.get("claims", [])
        if not claims:
            # In a packet that has real claims, an unclaimed fact is an unchecked
            # assertion and must count as a failure, never as silently verified.
            # A packet with no claims at all stays UNCHECKED (see summarise).
            if any_claim:
                results.append({"status": UNKNOWN, "kind": "none", "target": "",
                                "detail": "fact has no checkable claim",
                                "fact": fact.get("text", ""), "index": fact_index})
            continue
        for claim in claims:
            verdict = evaluate(root, claim)
            verdict["fact"] = fact.get("text", "")
            verdict["index"] = fact_index
            results.append(verdict)
    return results


def summarise(results: list[dict]) -> dict:
    counts = {OK: 0, STALE: 0, MISSING: 0, UNKNOWN: 0}
    for result in results:
        counts[result["status"]] = counts.get(result["status"], 0) + 1
    total = len(results)
    verified = total > 0 and counts[OK] == total
    return {"total": total, "ok": counts[OK], "stale": counts[STALE], "missing": counts[MISSING],
            "unknown": counts[UNKNOWN], "verified": verified}
