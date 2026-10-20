import tempfile
import unittest
from pathlib import Path

try:
    from tests.support import commit_all, make_repo, write
except ImportError:  # pragma: no cover
    from support import commit_all, make_repo, write

from handover import claims as C
from handover.packet import PacketError


class FileClaimTests(unittest.TestCase):
    def test_file_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root, "a.txt", "same")
            claim = C.pin_claims(root, [{"kind": "file", "path": "a.txt"}])[0]
            self.assertEqual(C.evaluate(root, claim)["status"], C.OK)

    def test_file_stale_after_edit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root, "a.txt", "before")
            claim = C.pin_claims(root, [{"kind": "file", "path": "a.txt"}])[0]
            write(root, "a.txt", "after")
            verdict = C.evaluate(root, claim)
            self.assertEqual(verdict["status"], C.STALE)
            self.assertIn("bytes changed", verdict["detail"])

    def test_file_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root, "a.txt", "x")
            claim = C.pin_claims(root, [{"kind": "file", "path": "a.txt"}])[0]
            (root / "a.txt").unlink()
            self.assertEqual(C.evaluate(root, claim)["status"], C.MISSING)

    def test_a_directory_is_unknown_not_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "dir").mkdir()
            claim = {"kind": "file", "path": "dir", "sha256": "0" * 64}
            self.assertEqual(C.evaluate(root, claim)["status"], C.UNKNOWN)

    def test_file_claim_without_hash_is_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root, "a.txt", "x")
            self.assertEqual(C.evaluate(root, {"kind": "file", "path": "a.txt"})["status"], C.UNKNOWN)


class AbsentClaimTests(unittest.TestCase):
    def test_absent_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(C.evaluate(root, {"kind": "absent", "path": "gone.txt"})["status"], C.OK)

    def test_absent_stale_when_the_path_comes_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root, "gone.txt", "back")
            self.assertEqual(C.evaluate(root, {"kind": "absent", "path": "gone.txt"})["status"], C.STALE)

    def test_absent_covers_directories(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "dir").mkdir()
            self.assertEqual(C.evaluate(root, {"kind": "absent", "path": "dir"})["status"], C.STALE)


class TextClaimTests(unittest.TestCase):
    def test_text_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root, "a.py", "def pay(x):\n    return x\n")
            claim = {"kind": "text", "path": "a.py", "contains": "def pay(x)"}
            self.assertEqual(C.evaluate(root, claim)["status"], C.OK)

    def test_text_stale_when_the_line_is_gone(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root, "a.py", "def refund(x):\n    return x\n")
            claim = {"kind": "text", "path": "a.py", "contains": "def pay(x)"}
            self.assertEqual(C.evaluate(root, claim)["status"], C.STALE)

    def test_text_missing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            claim = {"kind": "text", "path": "nope.py", "contains": "x"}
            self.assertEqual(C.evaluate(root, claim)["status"], C.MISSING)

    def test_text_without_a_needle_is_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root, "a.py", "x")
            self.assertEqual(C.evaluate(root, {"kind": "text", "path": "a.py"})["status"], C.UNKNOWN)

    def test_text_handles_utf8(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root, "a.txt", "città permanente\n")
            claim = {"kind": "text", "path": "a.txt", "contains": "città"}
            self.assertEqual(C.evaluate(root, claim)["status"], C.OK)

    def test_text_does_not_match_across_a_deleted_unicode_word(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root, "a.txt", "citta\n")
            claim = {"kind": "text", "path": "a.txt", "contains": "città"}
            self.assertEqual(C.evaluate(root, claim)["status"], C.STALE)


class GitClaimTests(unittest.TestCase):
    def test_git_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(Path(tmp))
            write(root, "a", "a")
            head = commit_all(root)
            claim = {"kind": "git", "ref": "HEAD", "sha": head}
            self.assertEqual(C.evaluate(root, claim)["status"], C.OK)

    def test_git_stale_after_a_new_commit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(Path(tmp))
            write(root, "a", "a")
            first = commit_all(root)
            write(root, "a", "b")
            commit_all(root)
            verdict = C.evaluate(root, {"kind": "git", "ref": "HEAD", "sha": first})
            self.assertEqual(verdict["status"], C.STALE)
            self.assertIn("ref moved", verdict["detail"])

    def test_git_missing_ref(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(Path(tmp))
            write(root, "a", "a")
            head = commit_all(root)
            verdict = C.evaluate(root, {"kind": "git", "ref": "no-such-branch", "sha": head})
            self.assertEqual(verdict["status"], C.MISSING)

    def test_git_claim_without_sha_is_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(Path(tmp))
            self.assertEqual(C.evaluate(root, {"kind": "git", "ref": "HEAD"})["status"], C.UNKNOWN)

    def test_git_outside_a_repo_is_missing_not_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            verdict = C.evaluate(Path(tmp), {"kind": "git", "ref": "HEAD", "sha": "a" * 40})
            self.assertEqual(verdict["status"], C.MISSING)


class SafetyTests(unittest.TestCase):
    def test_unknown_kind_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(PacketError):
                C.evaluate(Path(tmp), {"kind": "telepathy", "path": "a"})

    def test_path_escaping_the_root_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp, "root")
            root.mkdir()
            write(Path(tmp), "secret.txt", "s")
            with self.assertRaises(PacketError) as caught:
                C.evaluate(root, {"kind": "file", "path": "../secret.txt", "sha256": "0" * 64})
            self.assertIn("escapes", str(caught.exception))

    def test_absolute_path_outside_the_root_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp, "root")
            root.mkdir()
            outside = write(Path(tmp), "outside.txt", "x")
            with self.assertRaises(PacketError):
                C.evaluate(root, {"kind": "text", "path": str(outside), "contains": "x"})

    def test_a_path_inside_the_root_is_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root, "sub/a.txt", "x")
            self.assertEqual(C.evaluate(root, {"kind": "text", "path": "sub/a.txt", "contains": "x"})["status"], C.OK)


class PinningTests(unittest.TestCase):
    def test_pin_returns_empty_for_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(C.pin_claims(Path(tmp), None), [])

    def test_pin_rejects_a_non_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(PacketError):
                C.pin_claims(Path(tmp), {"kind": "file"})

    def test_pin_keeps_a_declared_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root, "a", "x")
            claim = C.pin_claims(root, [{"kind": "file", "path": "a", "sha256": "a" * 64}])[0]
            self.assertEqual(claim["sha256"], "a" * 64)

    def test_pin_fills_a_missing_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root, "a", "x")
            claim = C.pin_claims(root, [{"kind": "file", "path": "a"}])[0]
            self.assertEqual(len(claim["sha256"]), 64)

    def test_pin_refuses_a_text_claim_without_a_needle(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root, "a", "x")
            with self.assertRaises(PacketError):
                C.pin_claims(root, [{"kind": "text", "path": "a"}])

    def test_pin_fills_a_git_sha(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(Path(tmp))
            write(root, "a", "x")
            head = commit_all(root)
            claim = C.pin_claims(root, [{"kind": "git", "ref": "HEAD"}])[0]
            self.assertEqual(claim["sha"], head)


class AggregateTests(unittest.TestCase):
    def packet(self):
        return {"facts": [
            {"text": "one", "claims": [{"kind": "absent", "path": "gone-1"}]},
            {"text": "two", "claims": [{"kind": "absent", "path": "gone-2"}, {"kind": "absent", "path": "gone-3"}]},
        ]}

    def test_evaluate_packet_collects_every_claim_with_its_fact(self):
        with tempfile.TemporaryDirectory() as tmp:
            results = C.evaluate_packet(Path(tmp), self.packet())
            self.assertEqual(len(results), 3)
            self.assertEqual([r["fact"] for r in results], ["one", "two", "two"])

    def test_summary_of_a_verified_packet(self):
        with tempfile.TemporaryDirectory() as tmp:
            summary = C.summarise(C.evaluate_packet(Path(tmp), self.packet()))
            self.assertTrue(summary["verified"])
            self.assertEqual(summary["ok"], 3)

    def test_summary_of_a_stale_packet(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root, "gone-3", "appeared")
            summary = C.summarise(C.evaluate_packet(root, self.packet()))
            self.assertFalse(summary["verified"])
            self.assertEqual(summary["stale"], 1)

    def test_an_empty_packet_is_not_verified(self):
        self.assertFalse(C.summarise([])["verified"])


if __name__ == "__main__":
    unittest.main()
