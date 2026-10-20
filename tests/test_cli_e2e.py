import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

try:
    from tests.support import commit_all, make_repo, write
except ImportError:  # pragma: no cover
    from support import commit_all, make_repo, write

from handover import cli

REPO_ROOT = Path(__file__).resolve().parents[1]


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = cli.main(argv)
    return code, out.getvalue(), err.getvalue()


def spec_file(root: Path, facts, **extra) -> Path:
    payload = {"facts": facts, **extra}
    path = root / "source.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


class CaptureThenCheckTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        write(self.root, "src/app.py", "def pay(x):\n    return x\n")
        self.spec = spec_file(self.root, [
            {"text": "pay lives here",
             "claims": [{"kind": "file", "path": "src/app.py"},
                        {"kind": "text", "path": "src/app.py", "contains": "def pay(x)"}]},
        ], decisions=[{"text": "keep it simple", "why": "v0.1"}],
           open=[{"text": "add CI", "owner": "cto"}],
           owners=[{"seat": "engineer", "paths": ["src/**"]}])
        self.packet = self.root / "handover.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_capture_writes_a_packet(self):
        code, _out, err = run(["capture", "--from", str(self.spec), "--out", str(self.packet)])
        self.assertEqual(code, 0)
        self.assertIn("captured 1 fact(s), 2 check(s)", err)
        self.assertTrue(self.packet.exists())

    def test_check_verifies_a_fresh_packet(self):
        run(["capture", "--from", str(self.spec), "--out", str(self.packet)])
        code, out, _err = run(["check", str(self.packet)])
        self.assertEqual(code, 0)
        self.assertIn("VERIFIED", out)

    def test_check_json_is_machine_readable(self):
        run(["capture", "--from", str(self.spec), "--out", str(self.packet)])
        code, out, _err = run(["check", str(self.packet), "--json"])
        payload = json.loads(out)
        self.assertEqual(code, 0)
        self.assertEqual(payload["verdict"], "VERIFIED")
        self.assertEqual(payload["summary"]["total"], 2)
        self.assertEqual({r["status"] for r in payload["results"]}, {"OK"})

    def test_check_quiet_prints_nothing_when_verified(self):
        run(["capture", "--from", str(self.spec), "--out", str(self.packet)])
        code, out, _err = run(["check", str(self.packet), "--quiet"])
        self.assertEqual((code, out), (0, ""))

    def test_a_changed_file_goes_stale(self):
        run(["capture", "--from", str(self.spec), "--out", str(self.packet)])
        write(self.root, "src/app.py", "def pay(x):\n    return x * 2\n")
        code, out, _err = run(["check", str(self.packet)])
        self.assertEqual(code, 1)
        self.assertIn("STALE", out)
        self.assertIn("src/app.py", out)

    def test_stale_json_verdict(self):
        run(["capture", "--from", str(self.spec), "--out", str(self.packet)])
        write(self.root, "src/app.py", "gone\n")
        code, out, _err = run(["check", str(self.packet), "--json"])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(out)["verdict"], "STALE")

    def test_resume_prints_the_brief_when_verified(self):
        run(["capture", "--from", str(self.spec), "--out", str(self.packet)])
        code, out, _err = run(["resume", str(self.packet)])
        self.assertEqual(code, 0)
        self.assertIn("# Handover brief", out)
        self.assertIn("pay lives here", out)
        self.assertIn("keep it simple", out)
        self.assertIn("add CI", out)
        self.assertIn("engineer: src/**", out)
        self.assertNotIn("WARNING", out)

    def test_resume_refuses_a_stale_brief(self):
        run(["capture", "--from", str(self.spec), "--out", str(self.packet)])
        write(self.root, "src/app.py", "changed\n")
        code, out, err = run(["resume", str(self.packet)])
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn("refusing to resume", err)

    def test_resume_force_prints_with_a_warning(self):
        run(["capture", "--from", str(self.spec), "--out", str(self.packet)])
        write(self.root, "src/app.py", "changed\n")
        code, out, _err = run(["resume", str(self.packet), "--force"])
        self.assertEqual(code, 0)
        self.assertTrue(out.startswith("# WARNING: this brief is stale"))
        self.assertIn("pay lives here", out)

    def test_a_tampered_packet_is_refused(self):
        run(["capture", "--from", str(self.spec), "--out", str(self.packet)])
        packet = json.loads(self.packet.read_text(encoding="utf-8"))
        packet["facts"][0]["text"] = "something the packet never said"
        self.packet.write_text(json.dumps(packet), encoding="utf-8")
        code, _out, err = run(["check", str(self.packet)])
        self.assertEqual(code, 1)
        self.assertIn("SEAL-INVALID", err)

    def test_tampered_packet_json_says_untrusted(self):
        run(["capture", "--from", str(self.spec), "--out", str(self.packet)])
        packet = json.loads(self.packet.read_text(encoding="utf-8"))
        packet["open"] = []
        self.packet.write_text(json.dumps(packet), encoding="utf-8")
        code, out, _err = run(["check", str(self.packet), "--json"])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(out)["verdict"], "UNTRUSTED")

    def test_malformed_json_is_refused_with_exit_2(self):
        self.packet.write_text("{oops", encoding="utf-8")
        code, _out, err = run(["check", str(self.packet)])
        self.assertEqual(code, 2)
        self.assertIn("not valid JSON", err)

    def test_a_missing_packet_is_refused(self):
        code, _out, err = run(["check", str(self.root / "nothing.json")])
        self.assertEqual(code, 2)
        self.assertIn("no packet at", err)

    def test_capture_refuses_a_false_claim_and_writes_nothing(self):
        bad = spec_file(self.root, [{"text": "x", "claims": [{"kind": "file", "path": "ghost.py"}]}])
        code, _out, err = run(["capture", "--from", str(bad), "--out", str(self.root / "never.json")])
        self.assertEqual(code, 2)
        self.assertIn("refusing", err)
        self.assertFalse((self.root / "never.json").exists())

    def test_capture_without_a_source_is_refused(self):
        code, _out, err = run(["capture", "--from", str(self.root / "missing.json")])
        self.assertEqual(code, 2)
        self.assertIn("no source spec", err)

    def test_capture_with_invalid_source_json_is_refused(self):
        path = self.root / "bad-spec.json"
        path.write_text("[]", encoding="utf-8")
        code, _out, err = run(["capture", "--from", str(path)])
        self.assertEqual(code, 2)
        self.assertIn("must be a JSON object", err)

    def test_packet_without_claims_is_unchecked_not_verified(self):
        prose = spec_file(self.root, [{"text": "no evidence attached"}])
        packet = self.root / "prose.json"
        self.assertEqual(run(["capture", "--from", str(prose), "--out", str(packet)])[0], 0)
        code, out, _err = run(["check", str(packet)])
        self.assertEqual(code, 1)
        self.assertIn("UNCHECKED", out)

    def test_resume_refuses_an_unchecked_packet(self):
        prose = spec_file(self.root, [{"text": "no evidence attached"}])
        packet = self.root / "prose.json"
        run(["capture", "--from", str(prose), "--out", str(packet)])
        code, _out, err = run(["resume", str(packet)])
        self.assertEqual(code, 1)
        self.assertIn("carries no claims", err)

    def test_root_can_point_at_another_tree(self):
        elsewhere = self.root / "copy"
        write(elsewhere, "src/app.py", "def pay(x):\n    return x\n")
        run(["capture", "--from", str(self.spec), "--out", str(self.packet)])
        code, _out, _err = run(["check", str(self.packet), "--root", str(elsewhere)])
        self.assertEqual(code, 0)

    def test_unicode_facts_survive_the_roundtrip(self):
        fancy = spec_file(self.root, [{"text": "città permanente, not città"}])
        packet = self.root / "fancy.json"
        run(["capture", "--from", str(fancy), "--out", str(packet)])
        code, out, _err = run(["resume", str(packet), "--force"])
        self.assertEqual(code, 1)
        self.assertIn("città permanente", packet.read_text(encoding="utf-8"))

    def test_git_claim_goes_stale_after_a_commit(self):
        make_repo(self.root)
        commit_all(self.root)
        spec = spec_file(self.root, [{"text": "at the captured commit",
                                      "claims": [{"kind": "git", "ref": "HEAD"}]}])
        packet = self.root / "git.json"
        run(["capture", "--from", str(spec), "--out", str(packet)])
        self.assertEqual(run(["check", str(packet)])[0], 0)
        write(self.root, "new.txt", "new")
        commit_all(self.root)
        code, out, _err = run(["check", str(packet)])
        self.assertEqual(code, 1)
        self.assertIn("ref moved", out)


class ArgumentTests(unittest.TestCase):
    def test_no_arguments_exits_2(self):
        with self.assertRaises(SystemExit) as caught:
            cli.main([])
        self.assertEqual(caught.exception.code, 2)

    def test_version_exits_0(self):
        with self.assertRaises(SystemExit) as caught:
            cli.main(["--version"])
        self.assertEqual(caught.exception.code, 0)

    def test_unknown_command_exits_2(self):
        with self.assertRaises(SystemExit) as caught:
            cli.main(["polish"])
        self.assertEqual(caught.exception.code, 2)


class ProcessTests(unittest.TestCase):
    def test_python_dash_m_entry_point_runs(self):
        result = subprocess.run([sys.executable, "-m", "handover", "--version"],
                                capture_output=True, text=True, cwd=str(REPO_ROOT))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("handover 0.1.0", result.stdout)

    def test_module_and_cli_report_the_same_version(self):
        import handover
        result = subprocess.run([sys.executable, "-m", "handover", "--version"],
                                capture_output=True, text=True, cwd=str(REPO_ROOT))
        self.assertIn(handover.__version__, result.stdout)


if __name__ == "__main__":
    unittest.main()
