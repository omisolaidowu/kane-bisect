#!/usr/bin/env python3
"""
kane-bisect (wired to the book search demo app)
-------------------------------------------------
When the search feature breaks, this script finds the exact commit
that broke it, using Kane CLI to check each commit instead of a human.

Usage:
    python kane_bisect.py <good_commit> <bad_commit>

Example:
    python kane_bisect.py a1b2c3d f9e8d7c
"""

import subprocess
import sys
import time
import urllib.request

APP_URL = "http://localhost:5000"

# The one thing this app is supposed to do correctly.
KANE_OBJECTIVE = (
    "Type 'Clean' into the search box, click Search, "
    "and verify that 'Clean Code' appears in the results"
)


def run_command(command):
    """Run a shell command and return (success, output)."""
    result = subprocess.run(command, shell=True, capture_output=True, text=True)
    return result.returncode == 0, result.stdout + result.stderr


def checkout_commit(commit_hash):
    """Move the repo to a specific commit."""
    run_command(f"git checkout {commit_hash}")


def start_app():
    """Start the Flask app in the background."""
    subprocess.Popen(
        "flask --app app run --port 5000",
        shell=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    wait_until_ready()


def wait_until_ready(timeout_seconds=15):
    """Keep checking the app's homepage until it responds, or give up."""
    start_time = time.time()
    while time.time() - start_time < timeout_seconds:
        try:
            urllib.request.urlopen(APP_URL, timeout=1)
            return True
        except Exception:
            time.sleep(0.5)
    return False


def stop_app():
    """Stop the Flask app so the next commit can use the same port."""
    run_command("pkill -f 'flask --app app run'")
    time.sleep(1)


def run_kane_flow():
    """Run the Kane CLI flow against the running app. Returns (passed, output)."""
    command = (
        f'kane-cli run --url {APP_URL} "{KANE_OBJECTIVE}" --headless --agent'
    )
    return run_command(command)


def test_commit(commit_hash):
    """Check out one commit, start the app, run Kane, then clean up."""
    checkout_commit(commit_hash)
    start_app()
    passed, output = run_kane_flow()
    stop_app()
    return passed, output


def list_commits(good_commit, bad_commit):
    """Get every commit between good and bad, oldest first."""
    _, output = run_command(f"git rev-list --reverse {good_commit}..{bad_commit}")
    return [line for line in output.strip().split("\n") if line]


def bisect(good_commit, bad_commit):
    """Binary search for the first commit where the Kane flow fails."""
    commits = list_commits(good_commit, bad_commit)
    if not commits:
        print("No commits between good and bad — check your commit hashes.")
        return None

    low, high = 0, len(commits) - 1

    while low < high:
        mid = (low + high) // 2
        commit = commits[mid]
        print(f"Testing commit {commit} ...")
        passed, _ = test_commit(commit)
        print("  PASSED" if passed else "  FAILED")

        if passed:
            low = mid + 1  # bug is later in history
        else:
            high = mid  # bug is here or earlier

    culprit = commits[low]
    print(f"\nFound the breaking commit: {culprit}")
    return culprit


def main():
    if len(sys.argv) != 3:
        print("Usage: python kane_bisect.py <good_commit> <bad_commit>")
        sys.exit(1)

    good_commit, bad_commit = sys.argv[1], sys.argv[2]
    culprit = bisect(good_commit, bad_commit)

    if culprit:
        _, diff = run_command(f"git show {culprit}")
        print("\nWhat changed in the breaking commit:\n")
        print(diff)
        print(
            "\nNext step (not yet automated here): send this diff, plus the "
            "Kane failure output above, to your coding agent and ask for a fix."
        )


if __name__ == "__main__":
    main()