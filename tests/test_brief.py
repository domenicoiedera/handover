import unittest

from handover import brief as B
from handover.claims import MISSING, OK, STALE


def packet(**overrides):
    base = {
        "created_at": "2026-10-20T10:00:00Z",
        "repo": {"head": "a" * 40, "branch": "main", "dirty": 0},
        "facts": [{"text": "a fact", "claims": [{"kind": "file", "path": "a"}]}],
        "decisions": [], "open": [], "owners": [],
    }
    base.update(overrides)
    return base


def ok_results():
    return [{"status": OK, "kind": "file", "target": "a", "detail": "", "fact": "a fact", "index": 0}]


class BriefTests(unittest.TestCase):
    def test_is_deterministic(self):
        first = B.brief(packet(), ok_results(), stale=False)
        second = B.brief(packet(), ok_results(), stale=False)
        self.assertEqual(first, second)

    def test_starts_with_the_header_when_verified(self):
        text = B.brief(packet(), ok_results(), stale=False)
        self.assertTrue(text.startswith("# Handover brief - captured 2026-10-20T10:00:00Z"))

    def test_stale_banner_comes_first(self):
        text = B.brief(packet(), [{"status": STALE, "kind": "file", "target": "a", "detail": "x",
                                   "fact": "a fact", "index": 0}], stale=True)
        self.assertTrue(text.startswith("# WARNING"))
        self.assertIn("1 of 1 checks fail", text)

    def test_repo_line_reports_branch_head_and_dirty_files(self):
        self.assertIn("repo: main @ aaaaaaa, 0 file(s) dirty", B.brief(packet(), ok_results(), stale=False))

    def test_repo_line_says_unknown_rather_than_zero(self):
        text = B.brief(packet(repo={"head": None, "branch": None, "dirty": None}), ok_results(), stale=False)
        self.assertIn("dirty state unknown", text)

    def test_fact_with_passing_checks_is_labelled(self):
        self.assertIn("[1 check ok]", B.brief(packet(), ok_results(), stale=False))

    def test_fact_with_a_failing_check_is_labelled(self):
        results = [{"status": MISSING, "kind": "file", "target": "a", "detail": "", "fact": "a fact", "index": 0}]
        self.assertIn("CHECKS FAIL: MISSING", B.brief(packet(), results, stale=False))

    def test_fact_without_checks_is_marked_unchecked(self):
        text = B.brief(packet(facts=[{"text": "trust me", "claims": []}]), [], stale=False)
        self.assertIn("[unchecked assertion]", text)

    def test_decisions_render_with_their_reason(self):
        text = B.brief(packet(decisions=[{"text": "ship", "why": "cheap"}]), ok_results(), stale=False)
        self.assertIn("- ship  (cheap)", text)

    def test_open_threads_render_their_owner(self):
        text = B.brief(packet(open=[{"text": "fix it", "owner": "cto"}]), ok_results(), stale=False)
        self.assertIn("- fix it  [owner: cto]", text)

    def test_owners_render_their_paths(self):
        text = B.brief(packet(owners=[{"seat": "engineer", "paths": ["src/**", "tests/**"]}]), ok_results(), stale=False)
        self.assertIn("- engineer: src/**, tests/**", text)

    def test_empty_sections_are_omitted(self):
        text = B.brief(packet(), ok_results(), stale=False)
        self.assertNotIn("## Decisions", text)
        self.assertNotIn("## Open threads", text)

    def test_checks_line_counts_ok(self):
        self.assertIn("## Checks: 1/1 ok", B.brief(packet(), ok_results(), stale=False))

    def test_duplicate_fact_texts_do_not_cross_label(self):
        data = packet(facts=[{"text": "same words", "claims": [{"kind": "file", "path": "a"}]},
                             {"text": "same words", "claims": [{"kind": "file", "path": "b"}]}])
        results = [
            {"status": OK, "kind": "file", "target": "a", "detail": "", "fact": "same words", "index": 0},
            {"status": STALE, "kind": "file", "target": "b", "detail": "", "fact": "same words", "index": 1},
        ]
        lines = [line for line in B.brief(data, results, stale=False).splitlines() if line.startswith("- same words")]
        self.assertEqual(len(lines), 2)
        self.assertIn("[1 check ok]", lines[0])
        self.assertIn("CHECKS FAIL: STALE", lines[1])


class FailureFormattingTests(unittest.TestCase):
    def test_no_failures_is_empty(self):
        self.assertEqual(B.failures(ok_results()), "")

    def test_failures_name_status_kind_target_and_reason(self):
        text = B.failures([{"status": STALE, "kind": "file", "target": "src/a.py", "detail": "bytes changed"}])
        self.assertIn("STALE", text)
        self.assertIn("file", text)
        self.assertIn("src/a.py", text)
        self.assertIn("bytes changed", text)

    def test_several_failures_take_one_line_each(self):
        text = B.failures([
            {"status": STALE, "kind": "file", "target": "a", "detail": ""},
            {"status": MISSING, "kind": "text", "target": "b", "detail": ""},
        ])
        self.assertEqual(len(text.splitlines()), 2)


if __name__ == "__main__":
    unittest.main()
