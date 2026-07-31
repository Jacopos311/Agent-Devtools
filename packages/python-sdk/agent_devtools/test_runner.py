"""Test runner for assertion-based testing."""

import json
from pathlib import Path
from typing import List, Optional
import glob

from .transport import Transport
from .assertions import TestResult, run_assertions


class TestRunner:
    def __init__(self):
        self.transport = Transport()

    def run(self, path: str) -> List[TestResult]:
        """Run tests from a file, directory, or glob pattern."""
        path_obj = Path(path)

        if path_obj.is_file():
            return [self._run_single_test(path_obj)]
        elif path_obj.is_dir():
            results = []
            for file_path in path_obj.glob("*.json"):
                results.append(self._run_single_test(file_path))
            return results
        else:
            # Treat as glob pattern
            results = []
            for file_path in glob.glob(path):
                results.append(self._run_single_test(Path(file_path)))
            return results

    def _run_single_test(self, file_path: Path) -> TestResult:
        try:
            data = json.loads(file_path.read_text())
            test_name = data.get("name", file_path.stem)

            # Load fixture
            fixture_path = data.get("fixture_path")
            if fixture_path:
                fixture_data = json.loads(Path(fixture_path).read_text())
                events = fixture_data.get("events", [])
            else:
                events = data.get("events", [])

            # Run assertions
            assertions_config = data.get("assertions", [])
            assertion_results = run_assertions(events, assertions_config)

            all_passed = all(r.passed for r in assertion_results)
            message = None if all_passed else "Some assertions failed"

            return TestResult(
                name=test_name,
                passed=all_passed,
                message=message,
                assertions=assertion_results
            )

        except Exception as e:
            return TestResult(
                name=file_path.stem,
                passed=False,
                message=f"Error running test: {str(e)}",
                assertions=[]
            )