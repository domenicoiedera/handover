"""Rendering a packet as something a model (or a person) can resume from."""

from __future__ import annotations

from .claims import MISSING, OK, STALE, UNKNOWN


def _repo_line(packet: dict) -> str:
    repo = packet.get("repo") or {}
    head = repo.get("head")
    short = head[:7] if isinstance(head, str) else "unknown"
    branch = repo.get("branch") or "unknown"
    dirty = repo.get("dirty")
    dirty_text = "dirty state unknown" if dirty is None else f"{dirty} file(s) dirty"
    return f"repo: {branch} @ {short}, {dirty_text}"


def brief(packet: dict, results: list[dict], stale: bool) -> str:
    """Deterministic text: same packet in, same brief out."""
    lines: list[str] = []
    if stale:
        bad = [r for r in results if r["status"] != OK]
        lines.append(f"# WARNING: this brief is stale - {len(bad)} of {len(results)} checks fail.")
        lines.append("# Anything below may be false. Re-verify against the repository before acting.")
        lines.append("")
    lines.append(f"# Handover brief - captured {packet.get('created_at')}")
    lines.append(_repo_line(packet))
    lines.append("")

    facts = packet.get("facts", [])
    by_index: dict[int, list[str]] = {}
    for result in results:
        by_index.setdefault(result.get("index"), []).append(result["status"])
    lines.append(f"## Facts ({len(facts)})")
    for position, fact in enumerate(facts):
        claims = fact.get("claims", [])
        if claims:
            label = "check ok" if len(claims) == 1 else "checks ok"
            statuses = by_index.get(position, [])
            label_text = label if statuses and all(s == OK for s in statuses) else \
                    f"CHECKS FAIL: {', '.join(sorted({s for s in statuses if s != OK}))}"
            lines.append(f"- {fact['text']}  [{len(claims)} {label_text}]")
        else:
            lines.append(f"- {fact['text']}  [unchecked assertion]")
    lines.append("")

    decisions = packet.get("decisions", [])
    if decisions:
        lines.append(f"## Decisions ({len(decisions)})")
        for decision in decisions:
            text = decision.get("text") if isinstance(decision, dict) else str(decision)
            why = decision.get("why") if isinstance(decision, dict) else None
            lines.append(f"- {text}" + (f"  ({why})" if why else ""))
        lines.append("")

    open_items = packet.get("open", [])
    if open_items:
        lines.append(f"## Open threads ({len(open_items)})")
        for item in open_items:
            if isinstance(item, dict):
                owner = item.get("owner")
                text = item.get("text", "")
                lines.append(f"- {text}" + (f"  [owner: {owner}]" if owner else ""))
            else:
                lines.append(f"- {item}")
        lines.append("")

    owners = packet.get("owners", [])
    if owners:
        lines.append("## File ownership")
        for owner in owners:
            if isinstance(owner, dict):
                paths = owner.get("paths") or []
                label = owner.get("seat") or owner.get("owner") or "unassigned"
                lines.append(f"- {label}: {', '.join(str(p) for p in paths)}")
            else:
                lines.append(f"- {owner}")
        lines.append("")

    lines.append(f"## Checks: {sum(1 for r in results if r['status'] == OK)}/{len(results)} ok")
    return "\n".join(lines).rstrip() + "\n"


def failures(results: list[dict]) -> str:
    """One line per failed check, for stderr and for CI logs."""
    bad = [r for r in results if r["status"] != OK]
    if not bad:
        return ""
    width = max(len(r["status"]) for r in bad)
    lines = []
    for result in bad:
        target = result.get("target") or "?"
        lines.append(f"{result['status']:<{width}}  {result['kind']:<6}  {target}  {result['detail']}")
    return "\n".join(lines)


__all__ = ["brief", "failures", "MISSING", "STALE", "UNKNOWN"]
