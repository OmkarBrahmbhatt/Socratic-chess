from flask import Flask, render_template, request


def create_app():
    app = Flask(__name__)

    @app.route("/", methods=["GET", "POST"])
    def home():
        rating = None
        error = None

        if request.method == "POST":
            raw_rating = request.form.get("rating", "").strip()
            try:
                rating = int(raw_rating)
                if rating < 0:
                    error = "Enter a rating of zero or higher."
            except ValueError:
                error = "Enter a whole-number rating."

        response = render_template("index.html", rating=rating, error=error)
        return response, 400 if error else 200

    return app


app = create_app()


if __name__ == "__main__":
    app.run()
