"""Exercise the checker actually selected by the reusable workflow."""
import hashlib
import os
from pathlib import Path
import re
import unittest

import test_agents_profile as agents
import test_compliance_cleanup as cleanup
from workflow_checker_pin import NEW_ADAPTED, NEW_SOURCE, before_workflow_adoption

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = (ROOT / ".github/workflows/compliance.yml").read_text()
PIN = re.search(r"repository: stevekkall-beansgc/gate-kit\n\s+ref: (\S+)", WORKFLOW).group(1)
CHECKER = (ROOT / "tests/fixtures" / f"compliance-{PIN}.py").read_text()


class TestReleasedCheckerAdoption(unittest.TestCase):
    def test_selected_source_and_adapted_source_match_released_bytes(self):
        self.assertEqual(PIN, "v0.7.6")
        self.assertEqual(hashlib.sha256(CHECKER.rstrip("\n").encode()).hexdigest(), NEW_SOURCE)
        adapted = agents.NS["adapt_checker"](CHECKER)
        self.assertEqual(hashlib.sha256(adapted.encode()).hexdigest(), NEW_ADAPTED)

    def test_only_reviewed_checker_and_setup_selections_change_the_workflow(self):
        self.assertEqual(hashlib.sha256(before_workflow_adoption(WORKFLOW).encode()).hexdigest(),
                         "3fa7a25bfd091b4a652c5f31b42d29da910bb3d2a7cd1d6c897b0162de88f3c7")

    @unittest.skipUnless(os.name == "posix", "the supported runners are POSIX")
    def test_selected_normal_and_agents_profiles_stop_descendants(self):
        for adapted in (False, True):
            source = agents.NS["adapt_checker"](CHECKER) if adapted else CHECKER
            namespace = {"__name__": "checker_fixture", "__file__": str(ROOT / "bin/compliance.py")}
            exec(compile(source, "<selected-checker>", "exec"), namespace)
            for scenario in ({}, {"parent_exits": True}, {"cancelled": True}):
                with self.subTest(adapted=adapted, scenario=scenario):
                    cleanup.TestCheckCleanup._descendant(
                        self, runner=namespace["sh"], timeout=14400 if adapted else 900, **scenario)


if __name__ == "__main__":
    unittest.main()
