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

import json
import os
import socket
import subprocess
import sys
import time
import urllib.request

APP_URL = "http://localhost:5000"

# Where we remember the last commit confirmed to be good. This file lives
# in the repo folder but is git-ignored — it's the tool's own memory, not
# part of the project history.
STATE_FILE = ".kane_bisect_state.txt"

# Tracks the exact process we started, so we can kill precisely that one
# instead of guessing by name (which is unreliable on Windows).
current_process = None

# The one thing this app is supposed to do correctly.
# Phrased to lean on Kane's stronger "presence" check rather than an
# implicit absence check, and to explicitly wait for the page to finish
# reloading before asserting — both are documented sources of false
# results in Kane CLI's current release.
KANE_OBJECTIVE = (
    "Type 'Clean' into the search box, click Search, "
    "then assert that the results list contains 'Clean Code'"
)


def run_command(command):
    """Run a shell command and return (success, output)."""
    result = subprocess.run(
        command,
        shell=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return result.returncode == 0, result.stdout + result.stderr


def checkout_commit(commit_hash):
    """Move the repo to a specific commit."""
    success, output = run_command(f"git checkout {commit_hash}")
    if not success:
        print(f"  WARNING: checkout may have failed:\n{output}")


def is_port_free(port=5000):
    """Check whether nothing is currently listening on this port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        result = sock.connect_ex(("127.0.0.1", port))
        return result != 0  # non-zero means nothing answered = port is free


def wait_until_port_free(port=5000, timeout_seconds=10):
    """Wait until the port is actually free, instead of assuming it is."""
    start_time = time.time()
    while time.time() - start_time < timeout_seconds:
        if is_port_free(port):
            return True
        time.sleep(0.5)
    return False


def start_app():
    """Start the Flask app in the background and remember its process ID."""
    global current_process

    if not is_port_free():
        print(
            "  WARNING: port 5000 was still occupied right before starting "
            "a new server. Waiting for it to clear..."
        )
        if not wait_until_port_free():
            print(
                "  ERROR: port 5000 never freed up. The previous server "
                "may not have been killed. Results from this test cannot "
                "be trusted."
            )

    current_process = subprocess.Popen(
        "flask --app app run --port 5000",
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    ready = wait_until_ready()

    # Check whether the process crashed immediately (e.g. address already
    # in use) instead of actually starting.
    if current_process.poll() is not None:
        _, stderr_output = current_process.communicate()
        print(
            f"  ERROR: the Flask process exited immediately. It likely "
            f"failed to start:\n{stderr_output}"
        )
        ready = False

    if not ready:
        print(
            "  WARNING: app did not respond correctly. Results from this "
            "test cannot be trusted."
        )


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
    """Stop the exact Flask process we started, and confirm the port is free."""
    global current_process
    if current_process is None:
        return

    if os.name == "nt":
        # Windows: kill this process and any children it spawned.
        run_command(f"taskkill /F /T /PID {current_process.pid}")
    else:
        current_process.terminate()
        try:
            current_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            current_process.kill()

    current_process = None

    # Don't just assume the port is free after a fixed delay — confirm it.
    if not wait_until_port_free():
        print(
            "  WARNING: port 5000 is still occupied after stopping the "
            "server. Something else may still be listening on it."
        )


def run_kane_flow():
    """Run the Kane CLI flow once against the running app. Returns (passed, output)."""
    command = f'kane-cli run --url {APP_URL} "{KANE_OBJECTIVE}" --headless --agent'
    return run_command(command)


def get_reason_code(output):
    """Pull the reason_code out of Kane's run_end JSON line, if present."""
    for line in output.strip().split("\n"):
        line = line.strip()
        if '"type":"run_end"' in line:
            try:
                data = json.loads(line)
                return data.get("reason_code", "")
            except json.JSONDecodeError:
                return ""
    return ""


def is_automation_stall(output):
    """
    Check whether a failure was Kane's agent stalling/losing its place,
    rather than a real, confirmed problem with the app itself. These
    reason codes describe the automation getting confused, not the page
    actually showing (or failing to show) the expected result.
    """
    reason_code = get_reason_code(output)
    return reason_code.startswith("agent_error") or reason_code.startswith("stuck")


def has_valid_run(output):
    """
    Check whether Kane actually completed a real test run — i.e. the
    output contains a proper run_end result — as opposed to failing to
    execute at all (auth errors, missing config, etc.), which produces
    no structured result and should never be trusted as a real verdict.
    """
    return get_reason_code(output) != "" or '"type":"run_end"' in output


def run_kane_flow_reliable(max_attempts=3):
    """
    Run the Kane flow and guard against every failure mode we've
    actually observed: a false PASSED result on broken code, a false
    FAILED result caused by the automation stalling, and a false FAILED
    result caused by Kane not even completing a run at all (auth/config
    errors). The first two get one confirmation run before being
    trusted. The third is never trusted as a verdict — it's retried
    until we get a real result or run out of attempts.
    Returns (passed, output_of_last_run).
    """
    for attempt in range(1, max_attempts + 1):
        passed, output = run_kane_flow()

        if not has_valid_run(output):
            print(
                f"    (attempt {attempt}: Kane didn't complete a real run "
                f"— likely an auth/config error, not a test result. Retrying...)"
            )
            continue

        needs_confirmation = passed or is_automation_stall(output)
        if not needs_confirmation:
            return passed, output

        reason = "PASSED" if passed else "an automation stall, not a real failure"
        print(f"    (first check was {reason} — confirming with a second run...)")
        passed_confirm, output_confirm = run_kane_flow()

        if not has_valid_run(output_confirm):
            print(
                "    (confirmation run also failed to execute — retrying from scratch...)"
            )
            continue

        if passed_confirm != passed:
            print("    (second run disagreed — treating as FAILED to be safe)")
            return False, output_confirm

        return passed_confirm, output_confirm

    print(
        f"    WARNING: Kane failed to complete a real run after "
        f"{max_attempts} attempts. Treating as FAILED, but this result "
        f"cannot be trusted — check your Kane CLI login/config."
    )
    return False, output


def test_commit(commit_hash):
    """Check out one commit, start the app, run Kane, then clean up."""
    checkout_commit(commit_hash)

    # Confirm which commit is actually checked out right now — this is
    # the ground truth, in case the requested checkout didn't fully apply.
    _, actual_commit = run_command("git rev-parse HEAD")
    print(f"  (actually on commit: {actual_commit.strip()})")

    start_app()
    passed, output = run_kane_flow_reliable()
    stop_app()

    # Always show Kane's raw output, not just on failure — a "PASSED"
    # result deserves the same scrutiny as a "FAILED" one, especially
    # while we're checking whether the verdict can be trusted.
    print(f"  Kane's raw output ({'PASSED' if passed else 'FAILED'}):")
    print("  " + "\n  ".join(output.strip().split("\n")))

    return passed, output


def list_commits(good_commit, bad_commit):
    """Get every commit between good and bad, oldest first."""
    _, output = run_command(f"git rev-list --reverse {good_commit}..{bad_commit}")
    return [line for line in output.strip().split("\n") if line]


def get_current_branch():
    """Get the name of the branch we're on right now, before any checkouts."""
    _, output = run_command("git rev-parse --abbrev-ref HEAD")
    return output.strip()


def get_current_ref():
    """
    Get whatever identifies where we are right now — a branch name if
    we're on one, or the exact commit hash if we're in detached HEAD.
    Either way, this is always safe to check out later to get back here.
    """
    branch = get_current_branch()
    if branch != "HEAD":
        return branch
    return get_current_commit()


def bisect(good_commit, bad_commit):
    """Binary search for the first commit where the Kane flow fails."""
    original_ref = get_current_ref()

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

    # Always return to exactly where we started — whether that was a
    # branch or a specific commit checked out directly. Checking out
    # individual commits above leaves git pointed at whichever one was
    # tested last otherwise, which is not where the user expects to be.
    run_command(f"git checkout {original_ref}")
    print(f"(back on: {original_ref})")

    return culprit


def get_current_commit():
    """Get the commit hash we're sitting on right now."""
    _, output = run_command("git rev-parse HEAD")
    return output.strip()


def propose_fix(diff, kane_failure_output, broken_file_content):
    """
    Ask Claude to fix the bug, given:
    - the diff of the commit that broke things
    - what Kane reported when it failed
    - the full current (broken) content of app.py

    Returns the full corrected file content as a string, or None if the
    API call failed for any reason.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print(
            "  ERROR: ANTHROPIC_API_KEY environment variable is not set. "
            "Cannot request a fix."
        )
        return None

    prompt = f"""A commit broke a working feature in a small Flask app.

Here is what changed in the breaking commit:

{diff}

Here is what Kane CLI (a browser-testing tool) reported when it tested
the app and the feature failed:

{kane_failure_output}

Here is the full current content of app.py, which contains the bug:

{broken_file_content}

Fix the bug. Return ONLY the complete corrected content of app.py —
no explanation, no markdown code fences, no commentary. Just the raw
Python file content, ready to be written directly to disk."""

    request_body = json.dumps(
        {
            "model": "claude-sonnet-5",
            "max_tokens": 2000,
            "messages": [{"role": "user", "content": prompt}],
        }
    ).encode("utf-8")

    request = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=request_body,
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            response_data = json.loads(response.read().decode("utf-8"))
    except Exception as e:
        print(f"  ERROR: API call failed: {e}")
        return None

    text_blocks = [
        block["text"]
        for block in response_data.get("content", [])
        if block.get("type") == "text"
    ]
    if not text_blocks:
        print("  ERROR: no text content in the API response. Raw response:")
        print(f"  {json.dumps(response_data, indent=2)}")
        return None

    return "\n".join(text_blocks).strip()


def apply_and_verify_fix(fixed_content):
    """
    Write the proposed fix to app.py and re-run Kane to check whether it
    actually resolved the problem. Returns True if the fix works.
    """
    with open("app.py", "w", encoding="utf-8") as f:
        f.write(fixed_content)

    print("  Applied the proposed fix. Re-testing with Kane...")
    start_app()
    passed, output = run_kane_flow_reliable()
    stop_app()

    print(f"  Kane's raw output after the fix ({'PASSED' if passed else 'FAILED'}):")
    print("  " + "\n  ".join(output.strip().split("\n")))

    return passed


def load_last_good_commit():
    """Read the saved good commit from the state file, or None if there isn't one."""
    if not os.path.exists(STATE_FILE):
        return None
    with open(STATE_FILE) as f:
        return f.read().strip() or None


def save_last_good_commit(commit_hash):
    """Remember this commit as the last one confirmed to work."""
    with open(STATE_FILE, "w") as f:
        f.write(commit_hash)


def check():
    """
    Self-tracking mode: no hashes needed.

    - If there's no saved good commit yet, test the current one. If it
      passes, save it as the baseline. If it fails, we have nothing to
      bisect from yet, so just report it.
    - If there is a saved good commit, and it's the same as HEAD, there's
      nothing new to check.
    - Otherwise, test HEAD directly. If it passes, save it as the new
      baseline. If it fails, bisect between the saved good commit and
      HEAD to find exactly where things broke.
    """
    current_commit = get_current_commit()
    last_good = load_last_good_commit()

    if last_good is None:
        print("No saved baseline yet. Testing the current commit...")
        passed, _ = test_commit(current_commit)
        if passed:
            save_last_good_commit(current_commit)
            print(f"PASSED. Saved {current_commit} as the baseline.")
        else:
            print(
                "FAILED, and there's no earlier known-good commit to "
                "compare against yet. Fix this manually, then run "
                "'check' again once it passes, to establish a baseline."
            )
        return

    if current_commit == last_good:
        print("Already at the last known-good commit. Nothing to check.")
        return

    print(f"Testing current commit ({current_commit})...")
    passed, _ = test_commit(current_commit)

    if passed:
        save_last_good_commit(current_commit)
        print(f"PASSED. Saved {current_commit} as the new baseline.")
        return

    print("FAILED. Bisecting to find exactly where this broke...")
    culprit = bisect(last_good, current_commit)

    if not culprit:
        return

    _, diff = run_command(f"git show {culprit}")
    print("\nWhat changed in the breaking commit:\n")
    print(diff)

    print("\nAsking the coding agent to propose a fix...")
    with open("app.py", encoding="utf-8") as f:
        broken_content = f.read()

    fixed_content = propose_fix(diff, "", broken_content)

    if fixed_content is None:
        print(
            "\nCould not get a fix automatically. Send the diff above, "
            "plus the Kane failure output, to your coding agent manually."
        )
        return

    fix_worked = apply_and_verify_fix(fixed_content)

    if fix_worked:
        print("\nThe fix works — Kane now passes.")
        new_commit_hash = get_current_commit()
        run_command("git add app.py")
        run_command('git commit -m "Auto-fix: resolve regression found by kane-bisect"')
        fixed_commit = get_current_commit()
        save_last_good_commit(fixed_commit)
        print(f"Committed the fix as {fixed_commit} and updated the baseline.")
    else:
        print(
            "\nThe proposed fix did NOT pass Kane's check. Manual review "
            "needed — the broken code is currently sitting in app.py, "
            "uncommitted, for you to inspect."
        )


def main():
    if len(sys.argv) == 2 and sys.argv[1] == "check":
        check()
    elif len(sys.argv) == 3:
        # Manual mode — still useful for demos or re-testing a known range.
        good_commit, bad_commit = sys.argv[1], sys.argv[2]
        culprit = bisect(good_commit, bad_commit)
        if culprit:
            _, diff = run_command(f"git show {culprit}")
            print("\nWhat changed in the breaking commit:\n")
            print(diff)
            print(
                "\nNext step (not yet automated here): send this diff, "
                "plus the Kane failure output above, to your coding "
                "agent and ask for a fix."
            )
    else:
        print("Usage:")
        print("  python kane_bisect.py check              (self-tracking mode)")
        print("  python kane_bisect.py <good_commit> <bad_commit>  (manual mode)")
        sys.exit(1)


if __name__ == "__main__":
    main()
