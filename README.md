# Socratic Chess

**Live study:** https://socratic-chess.onrender.com/

A web app for a research study comparing two ways of practising chess tactics:

- **Question-based coaching:** the coach asks guiding questions and gives
  step-by-step hints.
- **Answer-based coaching:** the participant can retry or simply reveal the answer.

Each participant solves puzzles before practice, during practice and after
practice. The study compares their warm-up and final results and their survey
answers to see which style of practice helps more.

> **Status:** the app uses 288 real puzzles from the Lichess open puzzle
> database. The coach questions and hints were written for this study and
> should be reviewed (see `docs/puzzle_review.csv`) before collecting data. Do
> not collect real study data until your consent and data-retention procedures
> are approved.

## Study flow

| Step | What happens | Puzzles | Feedback |
|---|---|---|---|
| Start | Participant picks a rating category and confirms they are 18+ | - | - |
| 1. Warm-up check | Baseline test | 10 (5 forks, 5 pins) | None: the first move counts |
| 2a. Question-based practice | Wrong moves show a hint; a "Show next hint" button is available | 6 (3 forks, 3 pins) | Questions and hints |
| Survey | Four 1–7 sliders: demand, rushed, success, effort | - | - |
| 2b. Answer-based practice | After a move: **Retry** or **Show answer** | 6 (3 forks, 3 pins) | Answer on request |
| Survey | Same four sliders | - | - |
| 3. Final check | Post-test | 10 (5 forks, 5 pins) | None |
| Final survey | Which kind of help they preferred, and why | - | - |

**Rating categories:** Below 400, 400-800, 800-1000, 1000-1200, 1200-1400,
1400-1600, 1600-1800, 1800-2000, 2000+.

Fork and pin puzzles are balanced in every block, and puzzle order is
shuffled for each participant. No participant sees the same puzzle twice. The
12 practice puzzles are split at random between the two practice styles, so
across participants every practice puzzle is used with both. There is no
visible timer, but time spent on each move and each puzzle is recorded.

## Tech stack

- **Backend:** Python 3.9+, Flask, served by gunicorn in production
- **Database:** PostgreSQL (e.g. [Neon](https://neon.tech)) in production;
  SQLite for local development and tests
- **Board:** [chessground](https://github.com/lichess-org/chessground), the
  Lichess board, together with [chess.js](https://github.com/jhlywa/chess.js).
  The board only allows legal moves and promotes pawns to a queen
  automatically. Both libraries are loaded from a CDN.

## Project structure

```
app.py              Flask app: routes, study flow, database access
puzzles.py          Loads the puzzles and builds each participant's schedule
puzzle_data.json    The 288 puzzles (generated; see "Puzzles" below)
docs/puzzle_review.csv   Every puzzle, answer, question and hint, for review
scripts/build_puzzles/   Scripts that rebuild puzzle_data.json from Lichess
templates/          Pages: start (index), study, survey, complete
static/board.js     Chess board and move handling
static/study.js     Study-page interactions
static/style.css    Styles
tests/test_app.py   End-to-end tests of the study flow
```

## Running locally

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
flask --app app run --debug
```

Open the URL Flask prints (usually http://127.0.0.1:5000).

Without any configuration, data is saved to `instance/study.sqlite3`. To use
Postgres locally instead, create a `.env` file in the project root:

```
DATABASE_URL=postgresql://USER:PASSWORD@HOST/DBNAME?sslmode=require
```

`.env` is gitignored, and `flask run` loads it automatically. **Note:** if this
points at the production database, local test runs will add rows to your real
study data. Use a separate Neon branch for development.

## Configuration

| Environment variable | Required | Purpose |
|---|---|---|
| `DATABASE_URL` | In production | Postgres connection string. If it is not set, the app falls back to SQLite. |
| `SOCRATIC_CHESS_SECRET_KEY` | In production | Secret used to sign participant sessions. Without it, a random key is generated at startup, and anyone in the middle of the study loses their progress when the server restarts. Generate one with `python3 -c "import secrets; print(secrets.token_hex(32))"`. |

Never commit real values for either variable.

## Deploying on Render

The live instance runs at https://socratic-chess.onrender.com/. On Render's
free plan the service sleeps after a period with no visitors, so the first
page load after that can take up to a minute.

1. Create a **Web Service** from this repository.
2. **Build command:** `pip install -r requirements.txt`
3. **Start command:** `gunicorn app:app`
4. Under **Environment**, add `DATABASE_URL` and `SOCRATIC_CHESS_SECRET_KEY`.

Render's disk is wiped on every deploy and restart, so a deployed instance
**must** use Postgres. Otherwise all collected data is lost. Tables are
created automatically when the app starts, so no migration step is needed.

## Data collected

Participants are identified only by a random code such as `P-E7B64A`. No
names or contact details are collected.

| Table | One row per | Contents |
|---|---|---|
| `participants` | participant | `player_code`, `rating_band` (the chosen category), `rating` (the category's lower bound, used for puzzle selection), consent time |
| `puzzle_attempts` | puzzle slot (32 per participant) | phase, puzzle number, puzzle ID (the Lichess ID), theme, condition, solved, skipped, time spent, `is_demo` (`1` for attempts made on the earlier placeholder puzzles, `0` for real puzzles) |
| `move_events` | move | move in UCI format (e.g. `e5f7`), whether it was correct, time for the move and time since the puzzle started |
| `interaction_events` | button click | `hint_shown`, `retry_clicked` or `answer_shown`, with timing |
| `survey_responses` | survey | slider answers (1–7), final preference and explanation |

`move_events.attempt_id` links to `puzzle_attempts.id`. Every other table links
by `player_code`.

### Exporting data

The simplest way is to run queries in the Neon **SQL Editor** and download the
results as CSV. Example: one row per finished puzzle attempt.

```sql
SELECT p.player_code, p.rating_band, a.phase, a.puzzle_number, a.theme,
       a.condition, a.solved, a.skipped, a.elapsed_ms
FROM puzzle_attempts a
JOIN participants p USING (player_code)
WHERE a.finished_at IS NOT NULL
ORDER BY p.player_code, a.phase, a.puzzle_number;
```

Participants who finished the whole study have a `survey_responses` row with
`stage = 'final_preference'`.

## Puzzles

All puzzles come from the [Lichess open puzzle database](https://database.lichess.org/#puzzles)
(public domain, CC0). Each rating category has 32 puzzles: 16 forks and 16
pins, in three fixed sets.

| Set | Puzzles | Used in | Coach question and hints |
|---|---|---|---|
| `warmup` | 5 forks + 5 pins | Warm-up check | No |
| `practice` | 6 forks + 6 pins | Both practice styles | Yes |
| `final` | 5 forks + 5 pins | Final check | No |

That is 288 puzzles in total, 108 of them with a question and three hints.

### How they were chosen

1. **Theme:** tagged `fork` or `pin` on Lichess (not both, and no mating puzzles).
2. **Verified first move:** a chess library confirms that the first move the
   participant has to find is itself the fork or the pin, and that the line
   wins material. The app checks only this first move.
3. **Quality:** stable rating, high popularity and many plays. The median
   puzzle was played about 4,100 times with 99% popularity. The lowest
   categories had to accept less-played puzzles.
4. **Variety:** forks by knight, queen, bishop, rook and pawn; pins of three
   kinds (pin a piece and win it, attack a piece that is already pinned, and
   capture something a pinned piece only appears to defend).
5. **Matched sets:** within each category the warm-up, practice and final sets
   have the same average rating to within a few points, so warm-up and final
   results are comparable.

Lichess has no puzzles rated under 399. The "Below 400" category therefore
uses the easiest puzzles available (rated 414-549), and "400-800" uses puzzles
rated 550-799. Every "Below 400" pin is the same kind (pin a piece and win
it), because only about 20 pins that easy passed the checks.

### Format

`puzzle_data.json` maps each Lichess puzzle ID to an entry like this:

```json
"7gkHr": {
  "theme": "Forks",
  "rating_band": "400-800",
  "rating_min": 400,
  "rating_max": 799,
  "rating": 798,
  "set": "practice",
  "fen": "r5k1/pp3p1p/6p1/q3N3/5Q2/bPn1P1P1/P4P1P/1R1R2K1 b - - 2 26",
  "last_move": "g4f4",
  "solution": "c3e2",
  "solution_notation": "Ne2+",
  "line": ["Ne2+", "Kg2", "Nxf4+"],
  "source": "https://lichess.org/training/7gkHr",
  "question": "White just played Qf4. What do the queen's new square and ...",
  "hints": ["...", "...", "..."]
}
```

- `fen` is the position the participant sees, and the side to move is the
  participant. `last_move` is the opponent's move that led to it, highlighted
  on the board.
- `solution` is the move that is checked. `line` is the full Lichess solution.
- `rating_min` and `rating_max` are the participant ratings the puzzle is
  shown to. `rating` is the puzzle's own Lichess rating.
- `question` and `hints` exist only for `practice` puzzles. Hints go from
  vague to specific, and the third names the move.

### Reviewing and editing

`docs/puzzle_review.csv` lists every puzzle with its answer, question, hints
and a link to the puzzle on Lichess. To change a question or hint, edit
`puzzle_data.json` directly. To swap a puzzle or change the selection rules,
edit the scripts and rebuild:

```bash
pip install -r scripts/build_puzzles/requirements.txt
sh scripts/build_puzzles/run.sh
```

This downloads the database (about 310 MB) into `data/`, which is gitignored.
A rebuild regenerates all questions and hints from
`scripts/build_puzzles/coach_text.py` and overwrites hand edits in
`puzzle_data.json`.

### Current limitations

- Only the **first move** of each puzzle is checked. Participants do not play
  out the rest of the line.
- Pawns always promote to a queen (no selected puzzle needs anything else).
- Question-based practice always comes before answer-based practice. The
  order is not counterbalanced between participants.
- This repository contains the answers. If it is public, a participant could
  look them up.

## Running tests

```bash
python -m unittest discover -s tests
```

The tests always use a temporary SQLite database and never touch
`DATABASE_URL`.
