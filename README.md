# Book Search Demo App

A small Flask app with one feature: search a list of books. Built as the
demo target for a `kane-bisect` hackathon project.

## 1. Set up

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
npm install -g @testmuai/kane-cli
kane-cli login
```

## 2. Confirm the app works

```bash
flask --app app run --port 5000
```

Visit http://localhost:5000, search "Clean", confirm "Clean Code" shows up.
Stop the server (Ctrl+C).

## 3. Create your "good" commit

```bash
git init
git add .
git commit -m "Working book search"
```

Copy the commit hash it prints — this is your GOOD commit.

## 4. Plant the bug

Open `app.py` and change this line:

```python
results = [book for book in BOOKS if query.lower() in book.lower()]
```

to this (breaks partial matching — only exact full titles will match now):

```python
results = [book for book in BOOKS if query == book]
```

Commit it:

```bash
git add app.py
git commit -m "Simplify search matching"
```

Copy this commit hash too — this is your BAD commit.

## 5. Confirm Kane catches it

```bash
flask --app app run --port 5000 &
kane-cli run --url http://localhost:5000 "Type 'Clean' into the search box, click Search, and verify that 'Clean Code' appears in the results" --headless --agent
```

This should fail, since searching "Clean" no longer matches "Clean Code"
exactly. Stop the server: `pkill -f "flask --app app run"`

## 6. Run the bisector

```bash
python kane_bisect.py <good_commit_hash> <bad_commit_hash>
```

Since there's only one commit between good and bad in this small example,
it will find it immediately. For a more convincing demo, make 3–4 more
small commits (formatting tweaks, comments, an unrelated change) between
the good and bad commit, so the bisect actually narrows down through
several steps.

## 7. Wire in the fix (not yet automated)

The script prints the diff of the breaking commit and Kane's failure
output. Feed both to your coding agent (Claude Code, or a direct API
call) and ask for a fix. Apply the fix, re-run the Kane command from
step 5, confirm it now passes.