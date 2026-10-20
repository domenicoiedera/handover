"""The packet: what a handoff asserts, and how it is sealed.

A packet is a small JSON document. Its body holds facts, decisions, open
threads and file ownership. Every fact may carry claims - checkable statements
about the repository (a file's bytes, a path that must not exist, a line of
text, a git ref). The body is sealed with a sha256 so that any later edit is
visible, and each claim is re-evaluated on every ``check``.

The rule this module encodes: a brief that cannot be verified when it is
written is not allowed to be written. :func:`capture` evaluates every claim
before it seals anything.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

FORMAT = "handover:v1"
SEAL_ALG = "sha256"
REQUIRED_TOP = ("format", "created_at", "repo", "facts", "decisions", "open", "owners", "seal")


class PacketError(Exception):
    """The packet is malformed, or it cannot be built honestly."""


def canonical(body: dict) -> bytes:
    """The exact bytes that are sealed: sorted keys, no whitespace drift."""
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _body(packet: dict) -> dict:
    return {k: v for k, v in packet.items() if k != "seal"}


def seal_value(body: dict) -> str:
    return hashlib.sha256(canonical(body)).hexdigest()


def seal(packet: dict) -> dict:
    """Return a copy carrying a seal over everything else."""
    body = _body(packet)
    body["seal"] = {"alg": SEAL_ALG, "value": seal_value(body)}
    return body


def verify_seal(packet: dict) -> str:
    """Return the recomputed seal. Raises if the packet's seal does not match."""
    stored = packet.get("seal")
    if not isinstance(stored, dict) or stored.get("alg") != SEAL_ALG:
        raise PacketError("no usable seal: expected {'alg': 'sha256', 'value': ...}")
    if not isinstance(stored.get("value"), str) or len(stored["value"]) != 64:
        raise PacketError("seal value is not a sha256 hex digest")
    actual = seal_value(_body(packet))
    if actual != stored["value"]:
        raise PacketError(
            "SEAL-INVALID: the packet body was edited after it was sealed "
            f"(stored {stored['value'][:12]}..., recomputed {actual[:12]}...)"
        )
    return actual


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git(root: Path, *args: str) -> str | None:
    """Run a git read command. None means 'could not answer', never 'no'."""
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            timeout=20,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def repo_state(root: Path) -> dict:
    head = git(root, "rev-parse", "HEAD")
    branch = git(root, "rev-parse", "--abbrev-ref", "HEAD")
    status = git(root, "status", "--porcelain")
    if head is None:
        return {"head": None, "branch": None, "dirty": None}
    dirty = None if status is None else len([line for line in status.splitlines() if line.strip()])
    return {"head": head, "branch": branch, "dirty": dirty}


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise PacketError(message)


def validate(packet: dict, require_seal: bool = True) -> None:
    """Structural checks only. Says nothing about whether the claims are true."""
    _require(isinstance(packet, dict), "packet must be a JSON object")
    keys = REQUIRED_TOP if require_seal else tuple(key for key in REQUIRED_TOP if key != "seal")
    for key in keys:
        _require(key in packet, f"packet is missing {key!r}")
    _require(packet["format"] == FORMAT, f"unsupported format {packet['format']!r} (expected {FORMAT})")
    _require(isinstance(packet["created_at"], str) and packet["created_at"].endswith("Z"), "created_at must be an ISO-8601 UTC timestamp")
    try:
        datetime.fromisoformat(packet["created_at"].replace("Z", "+00:00"))
    except ValueError as exc:
        raise PacketError(f"created_at is not a timestamp: {packet['created_at']!r}") from exc
    _require(isinstance(packet["repo"], dict), "repo must be an object")
    for key in ("facts", "decisions", "open", "owners"):
        _require(isinstance(packet[key], list), f"{key} must be a list")
    for index, fact in enumerate(packet["facts"]):
        _require(isinstance(fact, dict) and isinstance(fact.get("text"), str) and fact["text"].strip(),
                 f"facts[{index}] needs a non-empty text")
        claims = fact.get("claims", [])
        _require(isinstance(claims, list), f"facts[{index}].claims must be a list")
        for position, claim in enumerate(claims):
            _require(isinstance(claim, dict) and isinstance(claim.get("kind"), str),
                     f"facts[{index}].claims[{position}] needs a kind")


def load(path: Path) -> dict:
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise PacketError(f"no packet at {path}") from exc
    try:
        packet = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise PacketError(f"packet is not valid JSON: {exc}") from exc
    validate(packet)
    return packet


def save(packet: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(packet, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def capture(spec: dict, root: Path) -> dict:
    """Build a packet from a source spec, pinning every claim to the disk.

    Anything that cannot be pinned - a file that is not there, a ref that does
    not resolve, a claim that is already false - is refused rather than written.
    """
    from .claims import evaluate, pin_claims

    _require(isinstance(spec, dict), "source spec must be a JSON object")
    facts = spec.get("facts", [])
    _require(isinstance(facts, list), "facts must be a list")

    pinned_facts = []
    for index, fact in enumerate(facts):
        _require(isinstance(fact, dict) and isinstance(fact.get("text"), str) and fact["text"].strip(),
                 f"facts[{index}] needs a non-empty text")
        claims = pin_claims(root, fact.get("claims", []))
        for claim in claims:
            verdict = evaluate(root, claim)
            if verdict["status"] != "OK":
                raise PacketError(
                    f"refusing to capture a brief that is already false: "
                    f"facts[{index}] {claim.get('kind')} {claim.get('path') or claim.get('ref')} "
                    f"is {verdict['status']} ({verdict['detail']})"
                )
        pinned_facts.append({"text": fact["text"], "claims": claims})

    packet = {
        "format": FORMAT,
        "created_at": now(),
        "repo": repo_state(root),
        "facts": pinned_facts,
        "decisions": spec.get("decisions", []),
        "open": spec.get("open", []),
        "owners": spec.get("owners", []),
    }
    validate(packet, require_seal=False)
    return seal(packet)


def root_of(packet_path: Path, explicit: str | None = None) -> Path:
    """The directory claims are relative to: the packet's own directory by default."""
    if explicit:
        return Path(explicit).expanduser().resolve()
    return packet_path.expanduser().resolve().parent
