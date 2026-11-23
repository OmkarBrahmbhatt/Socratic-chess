import os
import sqlite3
import tempfile
import unittest

from app import RATING_BANDS, build_schedule, create_app
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

    def start_study(
        self, rating_band="1200-1400", consent="yes", rating_system="lichess_puzzles", experience=""
    ):
        return self.client.post(
            "/",
            data={
                "rating_system": rating_system,
                "rating_band": rating_band,
                "experience": experience,
                "consent": consent,
            },
            follow_redirects=False,
        )

    def participant_row(self):
        """The participant row for whoever is signed in to the test client."""
        with self.client.session_transaction() as browser_session:
            player_code = browser_session["player_code"]
        with sqlite3.connect(self.database) as db:
            return db.execute(
                "SELECT rating, rating_band, rating_system, experience, puzzle_band "
                "FROM participants WHERE player_code = ?",
                (player_code,),
            ).fetchone()

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
        self.assertIn(b'<option value="Below 400"', response.data)
        self.assertIn(b'<option value="400-800"', response.data)

        for key in ("fide", "uscf", "national", "chesscom_rapid", "lichess_puzzles", "none"):
            self.assertIn(f'<option value="{key}"'.encode(), response.data)
        self.assertIn(b"I don't have a rating", response.data)

        missing_system = self.start_study(rating_system="")
        self.assertEqual(missing_system.status_code, 400)
        self.assertIn(b"Choose which chess rating you have", missing_system.data)

        unknown_system = self.start_study(rating_system="elo-ish")
        self.assertEqual(unknown_system.status_code, 400)
        self.assertIn(b"Choose which chess rating you have", unknown_system.data)

        missing_band = self.start_study(rating_band="")
        self.assertEqual(missing_band.status_code, 400)
        self.assertIn(b"Choose your rating range", missing_band.data)

        invalid_band = self.start_study(rating_band="1300")
        self.assertEqual(invalid_band.status_code, 400)
        self.assertIn(b"Choose your rating range", invalid_band.data)

        no_description = self.start_study(rating_system="none", rating_band="")
        self.assertEqual(no_description.status_code, 400)
        self.assertIn(b"Choose the description that fits you best", no_description.data)

        # An error keeps the participant's earlier answers selected.
        kept = self.start_study(rating_system="fide", rating_band="1400-1600", consent="")
        self.assertIn(b'value="fide" data-short="FIDE" selected', kept.data)
        self.assertIn(b'value="1400-1600" selected', kept.data)

        for band in ("Below 400", "400-800", "2000+"):
            self.assertEqual(self.start_study(rating_band=band).status_code, 302)

    def test_reported_rating_is_converted_to_a_puzzle_category(self):
        # Participants get puzzles one category above their estimated level.
        cases = [
            # (system, reported range, expected puzzle category)
            ("lichess_puzzles", "Below 400", "400-800"),
            ("lichess_puzzles", "1200-1400", "1400-1600"),
            ("lichess_rapid", "1400-1600", "1600-1800"),
            ("fide", "1400-1600", "1600-1800"),
            ("chesscom_rapid", "800-1000", "1400-1600"),
            ("chesscom_blitz", "400-800", "1400-1600"),
            ("uscf", "1000-1200", "1600-1800"),
            ("national", "1800-2000", "2000+"),  # already top: stays there
            ("lichess_puzzles", "2000+", "2000+"),
        ]
        for system, band, expected in cases:
            response = self.start_study(rating_system=system, rating_band=band)
            self.assertEqual(response.status_code, 302, system)
            rating, rating_band, rating_system, experience, puzzle_band = self.participant_row()
            self.assertEqual((rating_band, rating_system, experience), (band, system, None))
            self.assertEqual(puzzle_band, expected, f"{system} {band}")
            schedule = self.current_schedule()
            first = PUZZLES[schedule["warmup"][0]]
            self.assertTrue(
                all(PUZZLES[i]["rating_band"] == expected for ids in schedule.values() for i in ids),
                f"{system} {band}",
            )

    def test_participant_without_rating_describes_their_experience(self):
        response = self.start_study(rating_system="none", rating_band="", experience="casual")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.participant_row(), (1100, None, "none", "casual", "1200-1400"))
        # A stray range from the hidden question is ignored.
        self.start_study(rating_system="none", rating_band="2000+", experience="new")
        self.assertEqual(self.participant_row(), (300, None, "none", "new", "400-800"))

    def test_conversion_table_is_monotonic(self):
        from ratings import COMPARISON, RATING_SYSTEMS, puzzle_scale_rating
        for column in range(len(COMPARISON[0])):
            values = [row[column] for row in COMPARISON if row[column] is not None]
            self.assertEqual(values, sorted(values), column)
        for system in RATING_SYSTEMS:
            estimates = [puzzle_scale_rating(system, band) for band in RATING_BANDS]
            self.assertEqual(estimates, sorted(estimates), system)
            self.assertTrue(all(estimate >= 0 for estimate in estimates), system)

    def test_old_participants_get_their_puzzle_band_backfilled(self):
        with sqlite3.connect(self.database) as db:
            db.execute(
                "INSERT INTO participants (player_code, rating, rating_band, consented_at, created_at) "
                "VALUES ('P-OLD001', 800, '800-1000', 'x', 'x')"
            )
        create_app({"TESTING": True, "SECRET_KEY": "k", "DATABASE": self.database, "DATABASE_URL": None})
        with sqlite3.connect(self.database) as db:
            row = db.execute(
                "SELECT rating_system, puzzle_band FROM participants WHERE player_code = 'P-OLD001'"
            ).fetchone()
        self.assertEqual(row, (None, "800-1000"))

    def test_each_rating_category_uses_its_own_puzzles(self):
        for band, rating in RATING_BANDS.items():
            schedule = build_schedule(rating)
            for phase, puzzle_ids in schedule.items():
                self.assertTrue(
                    all(PUZZLES[puzzle_id]["rating_band"] == band for puzzle_id in puzzle_ids),
                    f"{band} {phase} got puzzles from another category",
                )
            # A participant never sees the same puzzle twice.
            all_ids = [puzzle_id for puzzle_ids in schedule.values() for puzzle_id in puzzle_ids]
            self.assertEqual(len(all_ids), 32)
            self.assertEqual(len(set(all_ids)), 32, band)
            # Each phase draws from its own fixed set.
            for phase, expected_set in (
                ("warmup", "warmup"),
                ("practice_question", "practice"),
                ("practice_answer", "practice"),
                ("final", "final"),
            ):
                self.assertEqual({PUZZLES[i]["set"] for i in schedule[phase]}, {expected_set})

    def test_practice_puzzles_are_split_at_random_between_conditions(self):
        seen_as_question = set()
        for _ in range(60):
            seen_as_question.update(build_schedule(1200)["practice_question"])
        self.assertEqual(len(seen_as_question), 12)

    def test_puzzles_are_well_formed(self):
        squares = {f"{file}{rank}" for file in "abcdefgh" for rank in "12345678"}
        for puzzle_id, puzzle in PUZZLES.items():
            self.assertIn(puzzle["theme"], ("Forks", "Pins"), puzzle_id)
            self.assertIn(puzzle["rating_band"], RATING_BANDS, puzzle_id)
            self.assertIn(puzzle["fen"].split()[1], ("w", "b"), puzzle_id)
            self.assertIn(puzzle["solution"][:2], squares, puzzle_id)
            self.assertIn(puzzle["solution"][2:4], squares, puzzle_id)
            self.assertIn(puzzle["set"], ("warmup", "practice", "final"), puzzle_id)
            self.assertIn(puzzle["last_move"][:2], squares, puzzle_id)
            self.assertTrue(puzzle["source"].startswith("https://lichess.org/training/"), puzzle_id)
            if puzzle["set"] == "practice":
                self.assertTrue(puzzle["question"].endswith("?"), puzzle_id)
                self.assertEqual(len(puzzle["hints"]), 3, puzzle_id)
        self.assertEqual(len(PUZZLES), 288)

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
        # Results: the first warm-up puzzle was solved, everything else skipped.
        page = complete.get_data(as_text=True)
        self.assertIn("How you did", page)
        self.assertIn("<strong>1</strong> / 10", page)
        self.assertIn("<strong>0</strong> / 10", page)
        self.assertIn("1 fewer", page)
        self.assertEqual(page.count("View on Lichess"), 20)
        self.assertIn(first_puzzle["solution_notation"], page)

        with sqlite3.connect(self.database) as db:
            participant = db.execute(
                "SELECT rating, rating_band, rating_system, puzzle_band FROM participants"
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

        self.assertEqual(participant, (1300, "1200-1400", "lichess_puzzles", "1400-1600"))
        self.assertEqual(len(attempts), 32)
        self.assertTrue(all(attempt[3] == 0 for attempt in attempts))
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
