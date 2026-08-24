# kane-bisect — Book Search Demo App

**kane-bisect** watches your repo, catches regressions with real browser
tests, finds the exact commit that caused them, and fixes them —
automatically. No commit hashes to remember, no manual bisecting.

This folder contains a small Flask demo app (one feature: search a list
of books) used as the test subject, plus `kane_bissect.py`, the tool
itself.

## 1. Set up

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
npm install -g @testmuai/kane-cli
kane-cli login
kane-cli install skill
```

You'll also need an Anthropic API key (from console.anthropic.com) set
as an environment variable, since the fix step calls Claude directly:

```bash
setx ANTHROPIC_API_KEY "your-key-here"
```
(restart your terminal after this)

## 2. Confirm the app works

```bash
flask --app app run --port 5000
```

Visit http://localhost:5000, search "Clean", confirm "Clean Code" shows
up. Stop the server (Ctrl+C) — from here on, `kane_bissect.py` starts
and stops the server itself; don't run it manually alongside the tool.

## 3. How to use it

There's exactly one command:

```bash
python kane_bissect.py check
```

Run this any time after making a commit.

- **First time ever:** it tests whatever commit you're on. If it
  passes, that becomes the saved baseline.
- **Every time after:** it compares your current commit to the saved
  baseline.
  - Same commit → nothing to do.
  - New commit, still passing → baseline quietly updates.
  - New commit, now failing → it automatically bisects between the
    saved baseline and your current commit to find the exact commit
    that broke things, asks Claude to propose a fix based on that
    commit's diff and Kane's failure output, applies the fix, re-tests
    with Kane, and — if it passes — commits the fix and updates the
    baseline. All of this happens with zero commit hashes typed by you.

The tool remembers its baseline in `.kane_bissect_state.txt`, which is
git-ignored — it's the tool's own memory, not part of the project.

## 4. Reproducing the demo from scratch

To rebuild the exact commit chain used for testing/demoing this tool:

```bash
git checkout -b bisect-demo
# ... make your "good" baseline commit here ...

echo # helper comment >> app.py
git add app.py
git commit -m "Add helper comment"

echo # another note >> app.py
git add app.py
git commit -m "Add another note"

echo # one more tweak >> app.py
git add app.py
git commit -m "Add one more tweak"
```

Then plant the bug — open `app.py` and change:
```python
results = [book for book in BOOKS if query.lower() in book.lower()]
```
to:
```python
results = [book for book in BOOKS if query == book]
```
```bash
git add app.py
git commit -m "Simplify search matching"
```

Then run `python kane_bissect.py check` on the good commit first (to
save it as the baseline), then on this branch's tip — it should
detect, bisect, fix, and verify automatically.

## 5. Reliability notes

Kane CLI's live browser check occasionally disagreed with itself on
identical, unchanged code — both in the direction of a false PASS on
broken code, and a false FAIL on working code (usually from the
automation stalling mid-run, or from a transient auth/session error
producing no real result at all). `kane_bissect.py` handles this by:

- Never trusting a PASSED or an inconclusive/stalled FAILED result on
  a single run — it re-confirms with a second run before trusting it.
- Detecting when Kane didn't complete a real run at all (e.g. an auth
  error) and retrying, rather than treating that as a genuine failure.
- Actively confirming port 5000 is free before starting a new server
  instance and after stopping the old one, instead of assuming a fixed
  delay is enough — a stale leftover server was an early, hard-to-spot
  source of false results during development.

This is a deliberate design choice, not a workaround being hidden: a
single flaky check is a poor foundation for an automated pipeline, so
the tool treats agreement across runs as the real signal of truth.