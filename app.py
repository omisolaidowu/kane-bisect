from flask import Flask, render_template, request

app = Flask(__name__)


@app.after_request
def add_no_cache_headers(response):
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    return response


BOOKS = [
    "The Pragmatic Programmer",
    "Clean Code",
    "The Mythical Man-Month",
    "Refactoring",
    "Design Patterns",
]


@app.route("/")
def index():
    query = request.args.get("q", "")
    results = []
    if query:
        # This line matches a book if the search text appears anywhere
        # inside its title, ignoring uppercase/lowercase differences.
        results = [book for book in BOOKS if query.lower() in book.lower()]
    return render_template("index.html", query=query, results=results)


if __name__ == "__main__":
    app.run(debug=True, port=5000)
