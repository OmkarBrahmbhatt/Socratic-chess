import os
import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, current_app, g, jsonify, redirect, render_template, request, session, url_for

from puzzles import PUZZLES, build_schedule
from ratings import (
    EXPERIENCE_LEVELS,
    NO_RATING,
    RATING_BANDS,
    RATING_SYSTEMS,
    grouped_systems,
    puzzle_band_for,
    puzzle_scale_rating,
)


PHASES = {
    "warmup": {"title": "Warm-up check", "count": 10, "condition": "no_feedback"},
    "practice_question": {
        "title": "Practice · Question-based",
        "count": 6,
        "condition": "question",
    },
    "practice_answer": {
        "title": "Practice · Answer-based",
        "count": 6,
        "condition": "answer",
    },
    "final": {"title": "Final check", "count": 10, "condition": "no_feedback"},
}
PRACTICE_SURVEYS = {
    "survey_question": "question",
    "survey_answer": "answer",
}
MAX_ELAPSED_MS = 24 * 60 * 60 * 1000
# Columns added to participants after the first release, with their types.
# They are added automatically to existing databases on startup.
PARTICIPANT_COLUMNS = {
    "rating_band": "TEXT",
    "rating_system": "TEXT",
    "experience": "TEXT",
    "puzzle_band": "TEXT",
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS participants (
    player_code TEXT PRIMARY KEY,
    rating INTEGER NOT NULL,
    rating_band TEXT,
    rating_system TEXT,
    experience TEXT,
    puzzle_band TEXT,
    consented_at TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS puzzle_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_code TEXT NOT NULL REFERENCES participants(player_code),
    phase TEXT NOT NULL,
    puzzle_number INTEGER NOT NULL,
    puzzle_id TEXT NOT NULL,
    theme TEXT NOT NULL,
    condition TEXT NOT NULL,
    is_demo INTEGER NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    elapsed_ms INTEGER NOT NULL DEFAULT 0,
    solved INTEGER,
    skipped INTEGER NOT NULL DEFAULT 0,
    UNIQUE (player_code, phase, puzzle_number)
);

CREATE TABLE IF NOT EXISTS move_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    attempt_id INTEGER NOT NULL REFERENCES puzzle_attempts(id),
    move_number INTEGER NOT NULL,
    move_uci TEXT NOT NULL,
    move_elapsed_ms INTEGER NOT NULL,
    position_elapsed_ms INTEGER NOT NULL,
    correct INTEGER NOT NULL,
    recorded_at TEXT NOT NULL,
    UNIQUE (attempt_id, move_number)
);

CREATE TABLE IF NOT EXISTS interaction_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_code TEXT NOT NULL REFERENCES participants(player_code),
    attempt_id INTEGER NOT NULL REFERENCES puzzle_attempts(id),
    event_type TEXT NOT NULL,
    value TEXT,
    elapsed_ms INTEGER NOT NULL,
    recorded_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS survey_responses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_code TEXT NOT NULL REFERENCES participants(player_code),
    stage TEXT NOT NULL,
    demand INTEGER,
    rushed INTEGER,
    success INTEGER,
    effort INTEGER,
    preference TEXT,
    explanation TEXT,
    created_at TEXT NOT NULL,
    UNIQUE (player_code, stage)
);

CREATE INDEX IF NOT EXISTS attempts_player_phase
    ON puzzle_attempts (player_code, phase);
CREATE INDEX IF NOT EXISTS moves_attempt
    ON move_events (attempt_id, move_number);
"""

QUESTION_PROMPTS = (
    "What checks, captures and threats do you have here?",
    "Which of your candidate moves creates the strongest threat?",
    "What changes if you move the piece you are considering?",
)


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _postgres_schema():
    return SCHEMA.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "SERIAL PRIMARY KEY")


class _Row(dict):
    """Row that supports both row["column"] and row[0], like sqlite3.Row."""

    def __init__(self, columns, values):
        super().__init__(zip(columns, values))
        self._values = tuple(values)

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._values[key]
        return super().__getitem__(key)


def _row_factory(cursor):
    columns = [column.name for column in cursor.description or ()]
    return lambda values: _Row(columns, values)


class _PostgresConnection:
    """Thin wrapper so the app's sqlite-style "?" queries run on Postgres."""

    def __init__(self, url):
        import psycopg

        self._connection = psycopg.connect(url, row_factory=_row_factory)

    def execute(self, sql, params=()):
        return self._connection.execute(sql.replace("?", "%s"), params)

    def commit(self):
        self._connection.commit()

    def close(self):
        self._connection.close()


def _init_postgres(url):
    import psycopg

    with psycopg.connect(url) as connection:
        # Serialize schema creation across gunicorn workers starting at once.
        connection.execute("SELECT pg_advisory_xact_lock(724181)")
        connection.execute(_postgres_schema())
        for column, kind in PARTICIPANT_COLUMNS.items():
            connection.execute(
                f"ALTER TABLE participants ADD COLUMN IF NOT EXISTS {column} {kind}"
            )
        connection.execute(_BACKFILL_PUZZLE_BAND)


# Before rating systems were asked, the chosen range was also the puzzle range.
_BACKFILL_PUZZLE_BAND = (
    "UPDATE participants SET puzzle_band = rating_band "
    "WHERE puzzle_band IS NULL AND rating_system IS NULL AND rating_band IS NOT NULL"
)


def _connect_db():
    url = current_app.config.get("DATABASE_URL")
    if url:
        return _PostgresConnection(url)
    connection = sqlite3.connect(current_app.config["DATABASE"])
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def get_db():
    if "db" not in g:
        g.db = _connect_db()
    return g.db


def close_db(_error=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("SOCRATIC_CHESS_SECRET_KEY") or secrets.token_hex(32),
        DATABASE=os.path.join(app.instance_path, "study.sqlite3"),
        DATABASE_URL=os.environ.get("DATABASE_URL"),
    )
    if test_config:
        app.config.update(test_config)
    if app.config["DATABASE_URL"]:
        _init_postgres(app.config["DATABASE_URL"])
    else:
        Path(app.instance_path).mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(app.config["DATABASE"])
        try:
            connection.executescript(SCHEMA)
            columns = {row[1] for row in connection.execute("PRAGMA table_info(participants)")}
            for column, kind in PARTICIPANT_COLUMNS.items():
                if column not in columns:
                    connection.execute(f"ALTER TABLE participants ADD COLUMN {column} {kind}")
            connection.execute(_BACKFILL_PUZZLE_BAND)
            connection.commit()
        finally:
            connection.close()
    app.teardown_appcontext(close_db)

    def start_page(error=None, status=200, **answers):
        return render_template(
            "index.html",
            error=error,
            rating_system_groups=grouped_systems(),
            no_rating=NO_RATING,
            rating_bands=RATING_BANDS,
            experience_levels=EXPERIENCE_LEVELS,
            rating_system=answers.get("rating_system", ""),
            rating_band=answers.get("rating_band", ""),
            experience=answers.get("experience", ""),
        ), status

    @app.get("/")
    def home():
        return start_page()

    @app.post("/")
    def start_study():
        answers = {
            "rating_system": request.form.get("rating_system", "").strip(),
            "rating_band": request.form.get("rating_band", "").strip(),
            "experience": request.form.get("experience", "").strip(),
        }
        rating_system = answers["rating_system"]
        if rating_system != NO_RATING and rating_system not in RATING_SYSTEMS:
            return start_page("Choose which chess rating you have.", 400, **answers)
        if rating_system == NO_RATING:
            if answers["experience"] not in EXPERIENCE_LEVELS:
                return start_page("Choose the description that fits you best.", 400, **answers)
            rating_band, experience = None, answers["experience"]
        else:
            if answers["rating_band"] not in RATING_BANDS:
                return start_page("Choose your rating range.", 400, **answers)
            rating_band, experience = answers["rating_band"], None
        if request.form.get("consent") != "yes":
            return start_page("Please confirm the study consent before continuing.", 400, **answers)
        # The estimate on the Lichess puzzle scale, moved up DIFFICULTY_STEP
        # categories, picks the puzzles.
        rating = puzzle_scale_rating(rating_system, rating_band, experience)
        puzzle_band = puzzle_band_for(rating)

        db = get_db()
        player_code = f"P-{secrets.token_hex(3).upper()}"
        while db.execute(
            "SELECT 1 FROM participants WHERE player_code = ?", (player_code,)
        ).fetchone():
            player_code = f"P-{secrets.token_hex(3).upper()}"
        now = utc_now()
        db.execute(
            "INSERT INTO participants "
            "(player_code, rating, rating_band, rating_system, experience, puzzle_band, "
            "consented_at, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (player_code, rating, rating_band, rating_system, experience, puzzle_band, now, now),
        )
        db.commit()
        session.clear()
        session.update(
            player_code=player_code,
            rating=rating,
            schedule=build_schedule(RATING_BANDS[puzzle_band]),
            phase="warmup",
            puzzle_index=0,
        )
        return redirect(url_for("study"))

    @app.get("/study")
    def study():
        player_code = session.get("player_code")
        phase = session.get("phase")
        if not player_code or phase not in PHASES:
            return redirect(url_for("home"))

        phase_info = PHASES[phase]
        index = session.get("puzzle_index", 0)
        if index >= phase_info["count"]:
            return redirect(url_for("home"))
        puzzle_id = session["schedule"][phase][index]
        puzzle = PUZZLES[puzzle_id]
        db = get_db()
        attempt = db.execute(
            "SELECT * FROM puzzle_attempts "
            "WHERE player_code = ? AND phase = ? AND puzzle_number = ?",
            (player_code, phase, index + 1),
        ).fetchone()
        if attempt is None:
            cursor = db.execute(
                "INSERT INTO puzzle_attempts "
                "(player_code, phase, puzzle_number, puzzle_id, theme, condition, "
                "is_demo, started_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?) RETURNING id",
                (
                    player_code,
                    phase,
                    index + 1,
                    puzzle_id,
                    puzzle["theme"],
                    phase_info["condition"],
                    int(bool(puzzle.get("demo"))),
                    utc_now(),
                ),
            )
            attempt_id = cursor.fetchone()["id"]
            db.commit()
        else:
            attempt_id = attempt["id"]
        session["attempt_id"] = attempt_id

        return render_template(
            "study.html",
            phase=phase,
            phase_title=phase_info["title"],
            phase_number=1 if phase == "warmup" else 2 if phase.startswith("practice") else 3,
            phase_count=3,
            puzzle_number=index + 1,
            puzzle_count=phase_info["count"],
            player_code=player_code,
            puzzle=puzzle,
            side_to_move=puzzle["fen"].split()[1],
            condition=phase_info["condition"],
            attempt_id=attempt_id,
            phase_progress=(index + 1) / phase_info["count"] * 100,
            question_prompt=puzzle.get("question")
            or QUESTION_PROMPTS[(index // 2) % len(QUESTION_PROMPTS)],
        )

    @app.post("/move")
    def record_move():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            payload = {}
        move_uci = payload.get("move")
        if (
            not isinstance(move_uci, str)
            or len(move_uci) not in (4, 5)
            or move_uci[:2] not in {f"{file}{rank}" for file in "abcdefgh" for rank in "12345678"}
            or move_uci[2:4] not in {f"{file}{rank}" for file in "abcdefgh" for rank in "12345678"}
        ):
            return jsonify(error="Select a from-square and a to-square."), 400
        elapsed = _validated_elapsed(payload.get("elapsed_ms"))
        move_elapsed = _validated_elapsed(payload.get("move_elapsed_ms"))
        if elapsed is None or move_elapsed is None:
            return jsonify(error="Timing data was invalid."), 400

        attempt, puzzle, error_response = _active_attempt()
        if error_response:
            return error_response
        db = get_db()
        if attempt["finished_at"] or attempt["solved"] == 1:
            return jsonify(error="This puzzle is already complete."), 409
        move_number = db.execute(
            "SELECT COUNT(*) + 1 FROM move_events WHERE attempt_id = ?",
            (attempt["id"],),
        ).fetchone()[0]
        correct = move_uci == puzzle["solution"]
        db.execute(
            "INSERT INTO move_events "
            "(attempt_id, move_number, move_uci, move_elapsed_ms, position_elapsed_ms, "
            "correct, recorded_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                attempt["id"],
                move_number,
                move_uci,
                move_elapsed,
                elapsed,
                int(correct),
                utc_now(),
            ),
        )
        db.execute(
            "UPDATE puzzle_attempts SET elapsed_ms = ?, solved = ? WHERE id = ?",
            (elapsed, int(correct) if correct else 0, attempt["id"]),
        )
        db.commit()

        condition = attempt["condition"]
        if condition == "no_feedback":
            response = {
                "condition": condition,
                "message": "Move recorded. Continue when you are ready.",
                "can_advance": True,
            }
        elif correct:
            response = {
                "condition": condition,
                "correct": True,
                "message": "Correct. Nice work.",
                "can_advance": True,
            }
        elif condition == "question":
            wrong_count = db.execute(
                "SELECT COUNT(*) FROM move_events WHERE attempt_id = ? AND correct = 0",
                (attempt["id"],),
            ).fetchone()[0]
            response = {
                "condition": condition,
                "correct": False,
                "message": puzzle["hints"][min(wrong_count - 1, len(puzzle["hints"]) - 1)],
                "can_advance": False,
            }
        else:
            response = {
                "condition": condition,
                "correct": False,
                "message": "Not quite. Retry the puzzle or show the answer.",
                "can_advance": False,
            }
        return jsonify(response)

    @app.post("/hint")
    def show_hint():
        attempt, puzzle, error_response = _active_attempt()
        if error_response:
            return error_response
        if attempt["condition"] != "question":
            return jsonify(error="Hints are not available in this practice block."), 409
        if attempt["finished_at"] or attempt["solved"] == 1:
            return jsonify(error="This puzzle is already complete."), 409
        db = get_db()
        hint_number = db.execute(
            "SELECT COUNT(*) + 1 FROM interaction_events "
            "WHERE attempt_id = ? AND event_type = 'hint_shown'",
            (attempt["id"],),
        ).fetchone()[0]
        hint_index = min(hint_number - 1, len(puzzle["hints"]) - 1)
        payload = request.get_json(silent=True)
        elapsed = _validated_elapsed(payload.get("elapsed_ms") if isinstance(payload, dict) else None)
        if elapsed is None:
            return jsonify(error="Timing data was invalid."), 400
        db.execute(
            "INSERT INTO interaction_events "
            "(player_code, attempt_id, event_type, value, elapsed_ms, recorded_at) "
            "VALUES (?, ?, 'hint_shown', ?, ?, ?)",
            (session["player_code"], attempt["id"], str(hint_index + 1), elapsed, utc_now()),
        )
        db.commit()
        return jsonify(hint_number=hint_index + 1, message=puzzle["hints"][hint_index])

    @app.post("/retry")
    def record_retry():
        attempt, _puzzle, error_response = _active_attempt()
        if error_response:
            return error_response
        if attempt["condition"] != "answer" or attempt["finished_at"] or attempt["solved"] == 1:
            return jsonify(error="Retry is not available for this puzzle."), 409
        payload = request.get_json(silent=True)
        elapsed = _validated_elapsed(payload.get("elapsed_ms") if isinstance(payload, dict) else None)
        if elapsed is None:
            return jsonify(error="Timing data was invalid."), 400
        db = get_db()
        answer_shown = db.execute(
            "SELECT 1 FROM interaction_events "
            "WHERE attempt_id = ? AND event_type = 'answer_shown' LIMIT 1",
            (attempt["id"],),
        ).fetchone()
        if answer_shown:
            return jsonify(error="The answer has already been shown."), 409
        db.execute(
            "INSERT INTO interaction_events "
            "(player_code, attempt_id, event_type, elapsed_ms, recorded_at) "
            "VALUES (?, ?, 'retry_clicked', ?, ?)",
            (session["player_code"], attempt["id"], elapsed, utc_now()),
        )
        db.commit()
        return jsonify(ok=True)

    @app.post("/show-answer")
    def show_answer():
        attempt, puzzle, error_response = _active_attempt()
        if error_response:
            return error_response
        if attempt["condition"] != "answer" or attempt["finished_at"] or attempt["solved"] == 1:
            return jsonify(error="The answer is not available for this puzzle."), 409
        payload = request.get_json(silent=True)
        elapsed = _validated_elapsed(payload.get("elapsed_ms") if isinstance(payload, dict) else None)
        if elapsed is None:
            return jsonify(error="Timing data was invalid."), 400
        db = get_db()
        move_count = db.execute(
            "SELECT COUNT(*) FROM move_events WHERE attempt_id = ?", (attempt["id"],)
        ).fetchone()[0]
        if move_count == 0:
            return jsonify(error="Try a move before requesting the answer."), 409
        db.execute(
            "INSERT INTO interaction_events "
            "(player_code, attempt_id, event_type, value, elapsed_ms, recorded_at) "
            "VALUES (?, ?, 'answer_shown', ?, ?, ?)",
            (
                session["player_code"],
                attempt["id"],
                puzzle["solution_notation"],
                elapsed,
                utc_now(),
            ),
        )
        db.commit()
        return jsonify(answer=puzzle["solution_notation"], solution=puzzle["solution"])

    @app.post("/advance")
    def advance_puzzle():
        attempt, _puzzle, error_response = _active_attempt()
        if error_response:
            return error_response
        elapsed = _validated_elapsed(request.form.get("elapsed_ms", "0"))
        if elapsed is None:
            return "Invalid timing data.", 400
        skipped = request.form.get("action") == "skip"
        db = get_db()
        move_count = db.execute(
            "SELECT COUNT(*) FROM move_events WHERE attempt_id = ?", (attempt["id"],)
        ).fetchone()[0]
        if not skipped and (
            move_count == 0
            or (
                attempt["condition"] == "question"
                and attempt["solved"] != 1
            )
            or (
                attempt["condition"] == "answer"
                and attempt["solved"] != 1
                and db.execute(
                    "SELECT 1 FROM interaction_events "
                    "WHERE attempt_id = ? AND event_type = 'answer_shown' LIMIT 1",
                    (attempt["id"],),
                ).fetchone()
                is None
            )
        ):
            return "Make a move or skip this puzzle before continuing.", 409
        db.execute(
            "UPDATE puzzle_attempts SET finished_at = ?, elapsed_ms = ?, "
            "skipped = ?, solved = COALESCE(solved, 0) WHERE id = ?",
            (utc_now(), elapsed, int(skipped), attempt["id"]),
        )
        db.commit()

        phase = session["phase"]
        next_index = session.get("puzzle_index", 0) + 1
        session.pop("attempt_id", None)
        if next_index < PHASES[phase]["count"]:
            session["puzzle_index"] = next_index
            return redirect(url_for("study"))

        session["puzzle_index"] = 0
        if phase == "warmup":
            session["phase"] = "practice_question"
            return redirect(url_for("study"))
        if phase == "practice_question":
            session["phase"] = "survey_question"
            return redirect(url_for("survey"))
        if phase == "practice_answer":
            session["phase"] = "survey_answer"
            return redirect(url_for("survey"))
        session["phase"] = "survey_final"
        return redirect(url_for("survey"))

    @app.get("/survey")
    def survey():
        stage = session.get("phase")
        if stage in PHASES:
            return redirect(url_for("study"))
        if stage == "survey_final":
            return render_template("survey.html", survey_type="final", player_code=session.get("player_code"))
        if stage in ("survey_question", "survey_answer"):
            return render_template(
                "survey.html",
                survey_type="practice",
                practice_condition=PRACTICE_SURVEYS[stage],
                player_code=session.get("player_code"),
            )
        return redirect(url_for("home"))

    @app.post("/survey")
    def save_survey():
        stage = session.get("phase")
        db = get_db()
        if stage in ("survey_question", "survey_answer"):
            values = {}
            for key in ("demand", "rushed", "success", "effort"):
                try:
                    values[key] = int(request.form.get(key, ""))
                except ValueError:
                    return render_template(
                        "survey.html",
                        survey_type="practice",
                        practice_condition=PRACTICE_SURVEYS[stage],
                        player_code=session.get("player_code"),
                        error="Please answer each slider question.",
                    ), 400
                if values[key] not in range(1, 8):
                    return "Slider values must be between 1 and 7.", 400
            db.execute(
                "INSERT INTO survey_responses "
                "(player_code, stage, demand, rushed, success, effort, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    session["player_code"],
                    PRACTICE_SURVEYS[stage],
                    values["demand"],
                    values["rushed"],
                    values["success"],
                    values["effort"],
                    utc_now(),
                ),
            )
            session["phase"] = (
                "practice_answer" if stage == "survey_question" else "final"
            )
            session["puzzle_index"] = 0
        elif stage == "survey_final":
            preference = request.form.get("preference", "")
            if preference not in ("questions", "answer", "no_preference"):
                return render_template(
                    "survey.html",
                    survey_type="final",
                    player_code=session.get("player_code"),
                    error="Choose one preference before submitting.",
                ), 400
            explanation = request.form.get("explanation", "").strip()[:2000]
            db.execute(
                "INSERT INTO survey_responses "
                "(player_code, stage, preference, explanation, created_at) "
                "VALUES (?, 'final_preference', ?, ?, ?)",
                (session["player_code"], preference, explanation, utc_now()),
            )
            session["phase"] = "complete"
        else:
            return redirect(url_for("home"))
        db.commit()
        return redirect(url_for("complete") if session["phase"] == "complete" else url_for("study"))

    @app.get("/complete")
    def complete():
        if session.get("phase") != "complete":
            return redirect(url_for("home"))
        return render_template(
            "complete.html",
            player_code=session["player_code"],
            results=_check_results(session["player_code"]),
        )

    return app


def _check_results(player_code):
    """Score the warm-up and final checks for the results page.

    A puzzle counts as solved when the participant's move matched the answer.
    Skipped puzzles count as not solved.
    """
    rows = get_db().execute(
        "SELECT a.phase, a.puzzle_number, a.puzzle_id, a.theme, a.solved, a.skipped, "
        "(SELECT m.move_uci FROM move_events m "
        " WHERE m.attempt_id = a.id AND m.move_number = 1) AS first_move "
        "FROM puzzle_attempts a "
        "WHERE a.player_code = ? AND a.phase IN ('warmup', 'final') "
        "ORDER BY a.puzzle_number",
        (player_code,),
    ).fetchall()
    results = {}
    for phase in ("warmup", "final"):
        puzzles = []
        for row in rows:
            if row["phase"] != phase:
                continue
            puzzle = PUZZLES.get(row["puzzle_id"], {})
            first_move = row["first_move"]
            puzzles.append(
                {
                    "number": row["puzzle_number"],
                    "theme": row["theme"],
                    "solved": row["solved"] == 1,
                    "skipped": bool(row["skipped"]),
                    "your_move": f"{first_move[:2]} to {first_move[2:4]}" if first_move else None,
                    "answer": puzzle.get("solution_notation"),
                    "source": puzzle.get("source"),
                }
            )
        themes = {}
        for theme in ("Forks", "Pins"):
            themed = [p for p in puzzles if p["theme"] == theme]
            themes[theme] = {"solved": sum(p["solved"] for p in themed), "total": len(themed)}
        results[phase] = {
            "title": PHASES[phase]["title"],
            "solved": sum(p["solved"] for p in puzzles),
            "total": len(puzzles),
            "themes": themes,
            "puzzles": puzzles,
        }
    results["change"] = results["final"]["solved"] - results["warmup"]["solved"]
    return results


def _validated_elapsed(value):
    try:
        elapsed = int(value)
    except (TypeError, ValueError):
        return None
    return elapsed if 0 <= elapsed <= MAX_ELAPSED_MS else None


def _active_attempt():
    player_code = session.get("player_code")
    attempt_id = session.get("attempt_id")
    if not player_code or not attempt_id:
        return None, None, (jsonify(error="No active puzzle."), 409)
    attempt = get_db().execute(
        "SELECT * FROM puzzle_attempts WHERE id = ? AND player_code = ?",
        (attempt_id, player_code),
    ).fetchone()
    if attempt is None:
        return None, None, (jsonify(error="No active puzzle."), 409)
    puzzle = PUZZLES[attempt["puzzle_id"]]
    return attempt, puzzle, None


app = create_app()


if __name__ == "__main__":
    app.run()
