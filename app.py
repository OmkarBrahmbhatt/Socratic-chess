import os
import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, current_app, g, jsonify, redirect, render_template, request, session, url_for

from puzzles import PUZZLES, puzzle_slots


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

SCHEMA = """
CREATE TABLE IF NOT EXISTS participants (
    player_code TEXT PRIMARY KEY,
    rating INTEGER NOT NULL,
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


def build_schedule(rating):
    return {
        "warmup": puzzle_slots(10, rating, shuffle=True),
        "practice_question": puzzle_slots(6, rating, shuffle=True),
        "practice_answer": puzzle_slots(6, rating, shuffle=True),
        "final": puzzle_slots(10, rating, shuffle=True),
    }


def board_squares(fen):
    rows = []
    files = "abcdefgh"
    for row_index, fen_row in enumerate(fen.split()[0].split("/")):
        rank = 8 - row_index
        file_index = 0
        row = []
        for token in fen_row:
            if token.isdigit():
                for _ in range(int(token)):
                    row.append(
                        {
                            "name": f"{files[file_index]}{rank}",
                            "piece": "",
                            "color": "",
                            "tone": "light" if (file_index + row_index) % 2 == 1 else "dark",
                        }
                    )
                    file_index += 1
            else:
                row.append(
                    {
                        "name": f"{files[file_index]}{rank}",
                        "piece": PUZZLES["glyphs"][token],
                        "color": "white" if token.isupper() else "black",
                        "tone": "light" if (file_index + row_index) % 2 == 1 else "dark",
                    }
                )
                file_index += 1
        rows.append(row)
    return rows


def _connect_db():
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
    )
    if test_config:
        app.config.update(test_config)
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(app.config["DATABASE"])
    try:
        connection.executescript(SCHEMA)
    finally:
        connection.close()
    app.teardown_appcontext(close_db)

    @app.get("/")
    def home():
        return render_template("index.html", error=None, rating="")

    @app.post("/")
    def start_study():
        raw_rating = request.form.get("rating", "").strip()
        try:
            rating = int(raw_rating)
        except ValueError:
            return render_template(
                "index.html",
                error="Enter a whole-number rating.",
                rating=raw_rating,
            ), 400
        if rating < 0:
            return render_template(
                "index.html",
                error="Enter a rating of zero or higher.",
                rating=raw_rating,
            ), 400
        if rating > 10000:
            return render_template(
                "index.html",
                error="Enter a rating of 10,000 or lower.",
                rating=raw_rating,
            ), 400
        if request.form.get("consent") != "yes":
            return render_template(
                "index.html",
                error="Please confirm the study consent before continuing.",
                rating=raw_rating,
            ), 400

        db = get_db()
        player_code = f"P-{secrets.token_hex(3).upper()}"
        while db.execute(
            "SELECT 1 FROM participants WHERE player_code = ?", (player_code,)
        ).fetchone():
            player_code = f"P-{secrets.token_hex(3).upper()}"
        now = utc_now()
        db.execute(
            "INSERT INTO participants (player_code, rating, consented_at, created_at) "
            "VALUES (?, ?, ?, ?)",
            (player_code, rating, now, now),
        )
        db.commit()
        session.clear()
        session.update(
            player_code=player_code,
            rating=rating,
            schedule=build_schedule(rating),
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
                "is_demo, started_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    player_code,
                    phase,
                    index + 1,
                    puzzle_id,
                    puzzle["theme"],
                    phase_info["condition"],
                    1,
                    utc_now(),
                ),
            )
            db.commit()
            attempt_id = cursor.lastrowid
        else:
            attempt_id = attempt["id"]
        session["attempt_id"] = attempt_id

        rows = board_squares(puzzle["fen"])
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
            rows=rows,
            condition=phase_info["condition"],
            attempt_id=attempt_id,
            phase_progress=(index + 1) / phase_info["count"] * 100,
            question_prompt=QUESTION_PROMPTS[(index // 2) % len(QUESTION_PROMPTS)],
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
        return jsonify(answer=puzzle["solution_notation"])

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
        return render_template("complete.html", player_code=session["player_code"])

    return app


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
