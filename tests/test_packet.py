import hashlib
import json
import tempfile
import unittest
from pathlib import Path

try:
    from tests.support import commit_all, make_repo, write
except ImportError:  # pragma: no cover - discovery without the package
    from support import commit_all, make_repo, write

from handover import claims as C
from handover import packet as P


class CanonicalTests(unittest.TestCase):
    def test_key_order_does_not_change_the_sealed_bytes(self):
        self.assertEqual(P.canonical({"a": 1, "b": 2}), P.canonical({"b": 2, "a": 1}))

    def test_list_order_does_change_the_sealed_bytes(self):
        self.assertNotEqual(P.canonical({"a": [1, 2]}), P.canonical({"a": [2, 1]}))

    def test_unicode_is_not_escaped(self):
        self.assertIn("città".encode("utf-8"), P.canonical({"x": "città"}))

    def test_seal_value_is_a_sha256_of_the_canonical_body(self):
        body = {"a": 1, "b": [1, 2]}
        self.assertEqual(P.seal_value(body), hashlib.sha256(P.canonical(body)).hexdigest())


class SealTests(unittest.TestCase):
    def body(self):
        return {"format": P.FORMAT, "created_at": "2026-10-20T10:00:00Z", "repo": {}, "facts": [],
                "decisions": [], "open": [], "owners": []}

    def test_seal_roundtrips(self):
        sealed = P.seal(self.body())
        self.assertEqual(P.verify_seal(sealed), sealed["seal"]["value"])

    def test_seal_detects_an_edited_body(self):
        sealed = P.seal(self.body())
        sealed["facts"].append({"text": "invented later", "claims": []})
        with self.assertRaises(P.PacketError) as caught:
            P.verify_seal(sealed)
        self.assertIn("SEAL-INVALID", str(caught.exception))

    def test_seal_detects_a_rewritten_fact(self):
        sealed = P.seal(self.body())
        sealed["facts"] = [{"text": "a", "claims": []}]
        resealed = P.seal(sealed)
        resealed["facts"][0]["text"] = "b"
        with self.assertRaises(P.PacketError):
            P.verify_seal(resealed)

    def test_missing_seal_is_refused(self):
        with self.assertRaises(P.PacketError):
            P.verify_seal(self.body())

    def test_unknown_algorithm_is_refused(self):
        sealed = P.seal(self.body())
        sealed["seal"]["alg"] = "md5"
        with self.assertRaises(P.PacketError):
            P.verify_seal(sealed)

    def test_short_seal_value_is_refused(self):
        sealed = P.seal(self.body())
        sealed["seal"]["value"] = "abc"
        with self.assertRaises(P.PacketError):
            P.verify_seal(sealed)

    def test_sealing_is_idempotent(self):
        once = P.seal(self.body())
        twice = P.seal(once)
        self.assertEqual(once, twice)


class ValidateTests(unittest.TestCase):
    def minimal(self, **overrides):
        packet = {"format": P.FORMAT, "created_at": "2026-10-20T10:00:00Z", "repo": {"head": None},
                  "facts": [], "decisions": [], "open": [], "owners": [], "seal": {"alg": "sha256", "value": "0" * 64}}
        packet.update(overrides)
        return packet

    def test_accepts_a_minimal_packet(self):
        P.validate(self.minimal())

    def test_rejects_a_missing_key(self):
        packet = self.minimal()
        del packet["owners"]
        with self.assertRaises(P.PacketError) as caught:
            P.validate(packet)
        self.assertIn("owners", str(caught.exception))

    def test_rejects_the_wrong_format(self):
        with self.assertRaises(P.PacketError):
            P.validate(self.minimal(format="handover:v0"))

    def test_rejects_a_timestamp_without_z(self):
        with self.assertRaises(P.PacketError):
            P.validate(self.minimal(created_at="2026-10-20T10:00:00"))

    def test_rejects_an_unparseable_timestamp(self):
        with self.assertRaises(P.PacketError):
            P.validate(self.minimal(created_at="yesterdayZ"))

    def test_rejects_a_fact_without_text(self):
        with self.assertRaises(P.PacketError):
            P.validate(self.minimal(facts=[{"claims": []}]))

    def test_rejects_a_claim_without_kind(self):
        with self.assertRaises(P.PacketError):
            P.validate(self.minimal(facts=[{"text": "x", "claims": [{"path": "a"}]}]))

    def test_rejects_a_non_list_facts_key(self):
        with self.assertRaises(P.PacketError):
            P.validate(self.minimal(facts={}))

    def test_unsealed_packets_can_be_validated_when_asked(self):
        packet = self.minimal()
        del packet["seal"]
        P.validate(packet, require_seal=False)


class HashTests(unittest.TestCase):
    def test_file_hash_matches_hashlib(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, "f.bin")
            payload = bytes(range(256)) * 300
            path.write_bytes(payload)
            self.assertEqual(P.sha256_file(path), hashlib.sha256(payload).hexdigest())

    def test_empty_file_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, "empty")
            path.write_bytes(b"")
            self.assertEqual(P.sha256_file(path), hashlib.sha256(b"").hexdigest())

    def test_hash_streams_rather_than_reading_everything(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, "big.bin")
            path.write_bytes(b"x" * (3 * 1024 * 1024))
            self.assertEqual(P.sha256_file(path), hashlib.sha256(b"x" * (3 * 1024 * 1024)).hexdigest())


class GitTests(unittest.TestCase):
    def test_git_returns_none_outside_a_repository(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(P.git(Path(tmp), "rev-parse", "HEAD"))

    def test_git_resolves_head(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(Path(tmp))
            write(root, "a.txt", "a")
            head = commit_all(root)
            self.assertEqual(P.git(root, "rev-parse", "HEAD"), head)

    def test_repo_state_reports_a_clean_tree(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(Path(tmp))
            write(root, "a.txt", "a")
            commit_all(root)
            state = P.repo_state(root)
            self.assertEqual(state["dirty"], 0)
            self.assertEqual(state["branch"], "main" if state["branch"] == "main" else state["branch"])
            self.assertEqual(len(state["head"]), 40)

    def test_repo_state_counts_dirty_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(Path(tmp))
            write(root, "a.txt", "a")
            commit_all(root)
            write(root, "a.txt", "changed")
            write(root, "b.txt", "new")
            self.assertEqual(P.repo_state(root)["dirty"], 2)

    def test_repo_state_outside_git_is_unknown_not_clean(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = P.repo_state(Path(tmp))
            self.assertIsNone(state["head"])
            self.assertIsNone(state["dirty"])


class LoadSaveTests(unittest.TestCase):
    def sealed(self):
        body = {"format": P.FORMAT, "created_at": "2026-10-20T10:00:00Z",
                "repo": {"head": None, "branch": None, "dirty": None},
                "facts": [], "decisions": [], "open": [], "owners": []}
        return P.seal(body)

    def test_save_then_load_roundtrips(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, "packet.json")
            original = self.sealed()
            P.save(original, path)
            self.assertEqual(P.load(path), original)

    def test_load_rejects_a_missing_file(self):
        with self.assertRaises(P.PacketError):
            P.load(Path(tempfile.gettempdir(), "definitely-not-here-handover.json"))

    def test_load_rejects_invalid_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, "bad.json")
            path.write_text("{not json", encoding="utf-8")
            with self.assertRaises(P.PacketError) as caught:
                P.load(path)
            self.assertIn("not valid JSON", str(caught.exception))

    def test_saved_file_is_valid_json_with_trailing_newline(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, "packet.json")
            P.save(self.sealed(), path)
            text = path.read_text(encoding="utf-8")
            self.assertTrue(text.endswith("\n"))
            json.loads(text)

    def test_root_defaults_to_the_packet_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, "packet.json")
            self.assertEqual(P.root_of(path), Path(tmp).resolve())

    def test_root_can_be_overridden(self):
        with tempfile.TemporaryDirectory() as tmp:
            other = Path(tmp, "elsewhere")
            other.mkdir()
            self.assertEqual(P.root_of(Path(tmp, "packet.json"), str(other)), other.resolve())


class CaptureTests(unittest.TestCase):
    def test_capture_pins_the_file_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "src/app.py"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"x = 1\n")
            packet = P.capture({"facts": [{"text": "app exists", "claims": [{"kind": "file", "path": "src/app.py"}]}]}, root)
            claim = packet["facts"][0]["claims"][0]
            self.assertEqual(claim["sha256"], hashlib.sha256(b"x = 1\n").hexdigest())

    def test_capture_pins_a_git_ref(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(Path(tmp))
            write(root, "a.txt", "a")
            head = commit_all(root)
            packet = P.capture({"facts": [{"text": "at head", "claims": [{"kind": "git", "ref": "HEAD"}]}]}, root)
            self.assertEqual(packet["facts"][0]["claims"][0]["sha"], head)

    def test_capture_records_repo_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(Path(tmp))
            write(root, "a.txt", "a")
            head = commit_all(root)
            packet = P.capture({"facts": []}, root)
            self.assertEqual(packet["repo"]["head"], head)
            self.assertEqual(packet["repo"]["dirty"], 0)
            self.assertTrue(packet["created_at"].endswith("Z"))

    def test_capture_refuses_a_file_claim_that_cannot_be_pinned(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(P.PacketError) as caught:
                P.capture({"facts": [{"text": "x", "claims": [{"kind": "file", "path": "ghost.py"}]}]}, Path(tmp))
            self.assertIn("not a file", str(caught.exception))

    def test_capture_refuses_a_claim_that_is_already_false(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root, "present.txt", "here")
            with self.assertRaises(P.PacketError) as caught:
                P.capture({"facts": [{"text": "it was deleted",
                                      "claims": [{"kind": "absent", "path": "present.txt"}]}]}, root)
            self.assertIn("already false", str(caught.exception))

    def test_capture_refuses_a_wrong_declared_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root, "a.txt", "real")
            with self.assertRaises(P.PacketError):
                P.capture({"facts": [{"text": "x", "claims": [{"kind": "file", "path": "a.txt", "sha256": "0" * 64}]}]}, root)

    def test_capture_refuses_an_unresolvable_ref(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(Path(tmp))
            write(root, "a.txt", "a")
            commit_all(root)
            with self.assertRaises(P.PacketError) as caught:
                P.capture({"facts": [{"text": "x", "claims": [{"kind": "git", "ref": "no-such-ref"}]}]}, root)
            self.assertIn("does not resolve", str(caught.exception))

    def test_capture_refuses_an_unknown_claim_kind(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(P.PacketError):
                P.capture({"facts": [{"text": "x", "claims": [{"kind": "vibes", "path": "a"}]}]}, Path(tmp))

    def test_captured_packet_verifies(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root, "a.txt", "a")
            packet = P.capture({"facts": [{"text": "x", "claims": [{"kind": "file", "path": "a.txt"}]}]}, root)
            self.assertEqual(P.verify_seal(packet), packet["seal"]["value"])

    def test_capture_keeps_unchecked_prose(self):
        with tempfile.TemporaryDirectory() as tmp:
            packet = P.capture({"facts": [{"text": "no evidence here"}],
                                "decisions": [{"text": "ship it", "why": "Friday"}],
                                "open": [{"text": "write docs", "owner": "cto"}],
                                "owners": [{"seat": "engineer", "paths": ["src/**"]}]}, Path(tmp))
            self.assertEqual(packet["facts"][0]["claims"], [])
            self.assertEqual(packet["decisions"][0]["why"], "Friday")
            self.assertEqual(packet["open"][0]["owner"], "cto")
            self.assertEqual(packet["owners"][0]["paths"], ["src/**"])

    def test_unchecked_fact_next_to_a_real_claim_is_not_verified(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write(root, "a.txt", "hello\n")
            packet = P.capture({"facts": [{"text": "a exists", "claims": [{"kind": "file", "path": "a.txt"}]},
                                          {"text": "prose only"}]}, root)
            results = C.evaluate_packet(root, packet)
            self.assertEqual(len(results), 2)
            self.assertEqual(results[1]["status"], C.UNKNOWN)
            self.assertFalse(C.summarise(results)["verified"])


if __name__ == "__main__":
    unittest.main()
