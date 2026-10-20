"""Command line: capture a brief, check it, resume from it."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import claims as claims_module
from .brief import brief, failures
from .packet import PacketError, capture, load, root_of, save, verify_seal

EXIT_OK = 0
EXIT_STALE = 1
EXIT_REFUSED = 2


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="handover",
        description="Verified handoff packets for AI agents: capture what is true, seal it, "
                    "and refuse to resume from a brief that has gone stale.",
    )
    parser.add_argument("--version", action="version", version=f"handover {_version()}")
    sub = parser.add_subparsers(dest="command", required=True)

    capture_cmd = sub.add_parser("capture", help="build a sealed packet from a source spec")
    capture_cmd.add_argument("--from", dest="source", required=True, metavar="SPEC", help="source spec JSON")
    capture_cmd.add_argument("--out", default="handover.json", metavar="PACKET", help="where to write the packet")
    capture_cmd.add_argument("--root", default=None, help="directory claims are relative to (default: the spec's directory)")

    check_cmd = sub.add_parser("check", help="re-verify a packet against the repository")
    check_cmd.add_argument("packet", nargs="?", default="handover.json")
    check_cmd.add_argument("--root", default=None, help="directory claims are relative to (default: the packet's directory)")
    check_cmd.add_argument("--json", action="store_true", dest="as_json", help="machine-readable result")
    check_cmd.add_argument("--quiet", action="store_true", help="print only failures")

    resume_cmd = sub.add_parser("resume", help="print the brief, refusing to do so if it is stale")
    resume_cmd.add_argument("packet", nargs="?", default="handover.json")
    resume_cmd.add_argument("--root", default=None, help="directory claims are relative to (default: the packet's directory)")
    resume_cmd.add_argument("--force", action="store_true", help="print the brief anyway, with a stale warning")
    return parser


def _version() -> str:
    from . import __version__
    return __version__


def _cmd_capture(args: argparse.Namespace) -> int:
    source = Path(args.source).expanduser()
    try:
        spec = json.loads(source.read_text(encoding="utf-8"))
    except OSError as exc:
        reason = getattr(exc, "strerror", None) or exc.__class__.__name__
        print(f"refusing: cannot read the source spec at {source}: {reason}", file=sys.stderr)
        return EXIT_REFUSED
    except json.JSONDecodeError as exc:
        print(f"refusing: source spec is not valid JSON: {exc}", file=sys.stderr)
        return EXIT_REFUSED
    root = Path(args.root).expanduser().resolve() if args.root else source.resolve().parent
    packet = capture(spec, root)
    save(packet, Path(args.out).expanduser())
    facts = len(packet["facts"])
    checks = sum(len(f.get("claims", [])) for f in packet["facts"])
    print(f"captured {facts} fact(s), {checks} check(s) -> {args.out}", file=sys.stderr)
    return EXIT_OK


def _evaluate(packet_path: Path, root_arg: str | None) -> tuple[dict, Path, list[dict], dict]:
    packet = load(packet_path)
    verify_seal(packet)
    root = root_of(packet_path, root_arg)
    results = claims_module.evaluate_packet(root, packet)
    return packet, root, results, claims_module.summarise(results)


def _cmd_check(args: argparse.Namespace) -> int:
    packet_path = Path(args.packet).expanduser()
    try:
        packet, _root, results, summary = _evaluate(packet_path, args.root)
    except PacketError as exc:
        message = str(exc)
        if args.as_json:
            print(json.dumps({"verdict": "UNTRUSTED", "error": message}, indent=2))
        print(f"refusing: {message}", file=sys.stderr)
        return EXIT_STALE if "SEAL-INVALID" in message else EXIT_REFUSED

    verdict = "VERIFIED" if summary["verified"] else ("UNCHECKED" if summary["total"] == 0 else "STALE")
    if args.as_json:
        print(json.dumps({"verdict": verdict, "summary": summary, "results": results}, indent=2, sort_keys=True))
    elif not args.quiet or not summary["verified"]:
        print(f"seal OK ({packet['seal']['value'][:12]}...), {summary['total']} check(s)")
        if summary["verified"]:
            print(f"VERIFIED: every claim still holds (captured {packet['created_at']})")
        elif summary["total"] == 0:
            print("UNCHECKED: this packet carries no claims, so there is nothing to verify. "
                  "A brief nobody can check is not a handoff, it is a rumour.")
        else:
            print(failures(results))
            print(f"STALE: {summary['total'] - summary['ok']} of {summary['total']} claim(s) no longer hold")
    return EXIT_OK if summary["verified"] else EXIT_STALE


def _cmd_resume(args: argparse.Namespace) -> int:
    packet_path = Path(args.packet).expanduser()
    try:
        packet, _root, results, summary = _evaluate(packet_path, args.root)
    except PacketError as exc:
        print(f"refusing to resume: {exc}", file=sys.stderr)
        return EXIT_STALE if "SEAL-INVALID" in str(exc) else EXIT_REFUSED

    if not summary["verified"]:
        if summary["total"] == 0:
            print("refusing to resume: this packet carries no claims, so nothing in it can be verified.", file=sys.stderr)
            return EXIT_STALE
        if not args.force:
            print(failures(results), file=sys.stderr)
            print(
                f"refusing to resume: {summary['total'] - summary['ok']} of {summary['total']} claim(s) no longer hold. "
                "Fix the brief with 'handover capture', or pass --force to read it with a warning.",
                file=sys.stderr,
            )
            return EXIT_STALE
        print(brief(packet, results, stale=True))
        return EXIT_OK
    print(brief(packet, results, stale=False))
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    handlers = {"capture": _cmd_capture, "check": _cmd_check, "resume": _cmd_resume}
    try:
        return handlers[args.command](args)
    except PacketError as exc:
        print(f"refusing: {exc}", file=sys.stderr)
        return EXIT_REFUSED
    except OSError as exc:
        reason = getattr(exc, "strerror", None) or exc.__class__.__name__
        print(f"refusing: {reason}", file=sys.stderr)
        return EXIT_REFUSED
    except BrokenPipeError:
        return EXIT_OK
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
