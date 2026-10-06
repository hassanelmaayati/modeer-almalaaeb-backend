"""Fail closed unless every mandatory GitHub Actions job succeeded."""
import argparse
import json
import unittest


def require_success(results, required):
    if not isinstance(results, dict) or not required:
        raise ValueError("Missing mandatory CI results")
    failures = {}
    for name in required:
        job = results.get(name)
        result = job.get("result", "missing") if isinstance(job, dict) else "missing"
        if result != "success":
            failures[name] = result
    if failures:
        raise ValueError("Mandatory jobs did not succeed: " + json.dumps(failures, sort_keys=True))


class GateTests(unittest.TestCase):
    def test_all_mandatory_jobs_must_succeed(self):
        require_success({"unit": {"result": "success"}, "e2e": {"result": "success"}}, ["unit", "e2e"])
        for result in ("failure", "skipped", "cancelled", "neutral", "timed_out", None):
            with self.subTest(result=result), self.assertRaises(ValueError):
                require_success({"unit": {"result": "success"}, "e2e": {"result": result}}, ["unit", "e2e"])

    def test_missing_results_are_not_success(self):
        for results in ({}, {"unit": {"result": "success"}}, {"unit": None}, None):
            with self.subTest(results=results), self.assertRaises(ValueError):
                require_success(results, ["unit", "e2e"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--results")
    parser.add_argument("--required", nargs="+")
    args = parser.parse_args()
    if args.self_test:
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(GateTests)
        return 0 if unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful() else 1
    try:
        require_success(json.loads(args.results or "null"), args.required)
    except (ValueError, TypeError) as error:
        parser.exit(1, f"CI gate failed: {error}\n")
    print("All mandatory CI jobs succeeded.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
