"""Resolve a public counterpart branch once and expose its immutable commit SHA."""
import argparse
import os
import re
import subprocess

REPOSITORIES = {"hassanelmaayati/modeer-almalaaeb-frontend", "hassanelmaayati/modeer-almalaaeb-backend"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repository", choices=sorted(REPOSITORIES))
    args = parser.parse_args()
    result = subprocess.run(["git", "ls-remote", "--exit-code", "--heads",
                             f"https://github.com/{args.repository}.git", "refs/heads/main"],
                            capture_output=True, text=True, check=True, timeout=60)
    rows = result.stdout.strip().splitlines()
    if len(rows) != 1 or not re.fullmatch(r"[0-9a-f]{40}\s+refs/heads/main", rows[0]):
        raise RuntimeError("Counterpart main did not resolve to exactly one full commit SHA")
    sha = rows[0].split()[0]
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
        output.write(f"sha={sha}\n")
    with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as summary:
        summary.write(f"Counterpart: `{args.repository}@{sha}`\n")
    print(f"Resolved immutable counterpart: {args.repository}@{sha}")


if __name__ == "__main__":
    main()
