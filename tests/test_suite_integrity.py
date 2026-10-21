"""Suite integrity: the tests themselves are part of the product.

Two failure modes this guards: a module that quietly disappears from the
package (so every test still passes but the feature is gone), and the suite
shrinking to a shape that passes by testing less.
"""

import unittest
from pathlib import Path

REQUIRED_MODULES = ("claims", "cli", "brief", "packet")
MINIMUM_TESTS = 129
PACKAGE = Path(__file__).resolve().parents[1] / "handover"
TESTS = Path(__file__).resolve().parent


class SuiteIntegrityTests(unittest.TestCase):
    def test_every_required_module_still_ships(self):
        missing = [name for name in REQUIRED_MODULES if not (PACKAGE / f"{name}.py").exists()]
        self.assertEqual(missing, [], f"modules vanished from the package: {missing}")

    def test_no_module_is_an_empty_stub(self):
        thin = [name for name in REQUIRED_MODULES if (PACKAGE / f"{name}.py").stat().st_size < 500]
        self.assertEqual(thin, [], f"suspiciously small modules: {thin}")

    def test_the_suite_is_at_least_as_large_as_agreed(self):
        count = 0
        for path in TESTS.glob("test_*.py"):
            for line in path.read_text(encoding="utf-8").splitlines():
                stripped = line.strip()
                if stripped.startswith("def test_") or stripped.startswith("def test("):
                    count += 1
        self.assertGreaterEqual(count, MINIMUM_TESTS, f"only {count} tests found")

    def test_the_package_has_no_third_party_imports(self):
        import ast
        import sys
        stdlib = set(sys.stdlib_module_names)
        offenders = []
        for path in PACKAGE.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = [alias.name.split(".")[0] for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    names = [] if node.level else [(node.module or "").split(".")[0]]
                else:
                    continue
                for name in names:
                    if name and name not in stdlib and name != "handover":
                        offenders.append(f"{path.name}: {name}")
        self.assertEqual(offenders, [], f"third-party imports found: {offenders}")

    def test_version_is_single_sourced(self):
        import handover
        pyproject = (PACKAGE.parent / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn(f'version = "{handover.__version__}"', pyproject)

    def test_readme_states_the_install_paths_that_work(self):
        readme = (PACKAGE.parent / "README.md").read_text(encoding="utf-8")
        self.assertIn("handover --version", readme)


if __name__ == "__main__":
    unittest.main()
