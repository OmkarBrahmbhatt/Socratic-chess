import os
import sqlite3
import tempfile
import unittest

from app import build_schedule, create_app
from puzzles import PUZZLES


class StudyFlowTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = os.path.join(self.temp_dir.name, "study.sqlite3")
        self.app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "test-key",
                "DATABASE": self.database,
                "DATABASE_URL": None,
            }
        )
        self.client = self.app.test_client()

    def tearDown(self):
        self.temp_dir.cleanup()

    def start_study(self, rating_band="1200-1400", consent="yes"):
        return self.client.post(
            "/",
            data={"rating_band": rating_band, "consent": consent},
            follow_redirects=False,
        )

    def current_schedule(self):
        with self.client.session_transaction() as browser_session:
            return browser_session["schedule"]

    def skip_puzzles(self, count):
        for _ in range(count):
            page = self.client.get("/study")
            self.assertEqual(page.status_code, 200)
            response = self.client.post(
                "/advance",
                data={"action": "skip", "elapsed_ms": "1250"},
            )
        return response

    def test_onboarding_requires_valid_rating_and_consent(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Start the warm-up check", response.data)

        no_consent = self.start_study(consent="")
        self.assertEqual(no_consent.status_code, 400)
        self.assertIn(b"confirm the study consent", no_consent.data)

        self.assertIn(b'<option value="2000+"', response.data)
        self.assertIn(b'<option value="400-800"', response.data)

        missing_band = self.start_study(rating_band="")
        self.assertEqual(missing_band.status_code, 400)
        self.assertIn(b"Choose your rating category", missing_band.data)

        invalid_band = self.start_study(rating_band="1300")
        self.assertEqual(invalid_band.status_code, 400)
        self.assertIn(b"Choose your rating category", invalid_band.data)

        for band in ("400-800", "2000+"):
            self.assertEqual(self.start_study(rating_band=band).status_code, 302)

    def test_schedule_balances_themes_and_phase_counts(self):
        schedule = build_schedule(1200)
        expected = {
            "warmup": (10, 5),
            "practice_question": (6, 3),
            "practice_answer": (6, 3),
            "final": (10, 5),
        }
        for phase, (count, per_theme) in expected.items():
            self.assertEqual(len(schedule[phase]), count)
            themes = [PUZZLES[puzzle_id]["theme"] for puzzle_id in schedule[phase]]
            self.assertEqual(themes.count("Forks"), per_theme)
            self.assertEqual(themes.count("Pins"), per_theme)

    def test_complete_study_saves_timing_attempts_and_surveys(self):
        response = self.start_study()
        self.assertEqual(response.status_code, 302)

        schedule = self.current_schedule()
        self.client.get("/study")
        first_puzzle = PUZZLES[schedule["warmup"][0]]
        unscored_response = self.client.post(
            "/move",
            json={
                "move": first_puzzle["solution"],
                "elapsed_ms": 3200,
                "move_elapsed_ms": 3200,
            },
        )
        self.assertEqual(unscored_response.status_code, 200)
        self.assertNotIn("correct", unscored_response.json)
        self.client.post("/advance", data={"elapsed_ms": "3200"})
        self.skip_puzzles(9)

        self.client.get("/study")
        question_puzzle = PUZZLES[schedule["practice_question"][0]]
        wrong_question_move = self.client.post(
            "/move",
            json={"move": "a1a2", "elapsed_ms": 1500, "move_elapsed_ms": 1500},
        )
        self.assertFalse(wrong_question_move.json["correct"])
        self.assertIn("message", wrong_question_move.json)
        hint = self.client.post("/hint", json={"elapsed_ms": 1800})
        self.assertEqual(hint.status_code, 200)
        self.assertEqual(hint.json["hint_number"], 1)
        denied_retry = self.client.post("/retry", json={"elapsed_ms": 1800})
        self.assertEqual(denied_retry.status_code, 409)

        correct_question_move = self.client.post(
            "/move",
            json={
                "move": question_puzzle["solution"],
                "elapsed_ms": 2500,
                "move_elapsed_ms": 1000,
            },
        )
        self.assertTrue(correct_question_move.json["correct"])
        self.client.post("/advance", data={"elapsed_ms": "2500"})
        self.skip_puzzles(5)

        survey_page = self.client.get("/survey")
        self.assertIn(b"How did that practice feel?", survey_page.data)
        slider_answers = {"demand": "4", "rushed": "3", "success": "5", "effort": "4"}
        self.client.post("/survey", data=slider_answers)

        self.client.get("/study")
        answer_puzzle = PUZZLES[schedule["practice_answer"][0]]
        wrong_answer_move = self.client.post(
            "/move",
            json={"move": "a1a2", "elapsed_ms": 1100, "move_elapsed_ms": 1100},
        )
        self.assertIn("Retry", wrong_answer_move.json["message"])
        self.assertEqual(
            self.client.post("/retry", json={"elapsed_ms": 1400}).status_code,
            200,
        )
        self.client.post(
            "/move",
            json={
                "move": "a1a2",
                "elapsed_ms": 2100,
                "move_elapsed_ms": 700,
            },
        )
        shown_answer = self.client.post("/show-answer", json={"elapsed_ms": 2500})
        self.assertEqual(shown_answer.json["answer"], answer_puzzle["solution_notation"])
        self.assertEqual(
            self.client.post("/retry", json={"elapsed_ms": 2600}).status_code,
            409,
        )
        self.client.post("/advance", data={"elapsed_ms": "2700"})
        self.skip_puzzles(5)

        self.assertIn(b"How did that practice feel?", self.client.get("/survey").data)
        self.client.post("/survey", data=slider_answers)
        self.skip_puzzles(10)

        final_survey = self.client.get("/survey")
        self.assertIn(b"Which kind of help", final_survey.data)
        self.client.post(
            "/survey",
            data={"preference": "questions", "explanation": "I like hints."},
        )
        complete = self.client.get("/complete")
        self.assertIn(b"Thanks, you're finished!", complete.data)

        with sqlite3.connect(self.database) as db:
            participant = db.execute(
                "SELECT rating, rating_band FROM participants"
            ).fetchone()
            attempts = db.execute(
                "SELECT phase, theme, elapsed_ms, is_demo FROM puzzle_attempts"
            ).fetchall()
            move_events = db.execute(
                "SELECT move_elapsed_ms, position_elapsed_ms, correct FROM move_events"
            ).fetchall()
            interactions = db.execute(
                "SELECT event_type FROM interaction_events ORDER BY event_type"
            ).fetchall()
            surveys = db.execute(
                "SELECT stage, preference, explanation FROM survey_responses"
            ).fetchall()

        self.assertEqual(participant, (1200, "1200-1400"))
        self.assertEqual(len(attempts), 32)
        self.assertTrue(all(attempt[3] == 1 for attempt in attempts))
        self.assertTrue(all(attempt[2] >= 0 for attempt in attempts))
        self.assertEqual(len(move_events), 5)
        self.assertEqual(move_events[0], (3200, 3200, 1))
        self.assertEqual(
            sorted(event[0] for event in interactions),
            ["answer_shown", "hint_shown", "retry_clicked"],
        )
        self.assertEqual(len(surveys), 3)
        self.assertIn(("final_preference", "questions", "I like hints."), surveys)


if __name__ == "__main__":
    unittest.main()
