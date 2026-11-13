# Socratic Chess

A web app for a research study comparing two ways of practising chess tactics:

- **Question-based coaching:** the coach asks guiding questions and gives
  step-by-step hints.
- **Answer-based coaching:** the participant can retry or simply reveal the answer.

Each participant solves puzzles before practice, during practice and after
practice. The study compares their warm-up and final results and their survey
answers to see which style of practice helps more.

> **Status: prototype.** The chess puzzles are demo placeholders: two sample
> positions repeated to fill every slot. Do not collect real study data until
> real puzzles are added and your consent and data-retention procedures are
> approved.

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
shuffled for each participant. There is no visible timer, but time spent on
each move and each puzzle is recorded.

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
puzzles.py          Puzzle data and per-participant puzzle selection
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
| `puzzle_attempts` | puzzle slot (32 per participant) | phase, puzzle number, puzzle ID, theme, condition, solved, skipped, time spent, `is_demo` |
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

## Adding real puzzles

Puzzles live in `puzzles.py`. Each entry looks like this:

```python
"fork-001": {
    "theme": "Forks",                 # "Forks" or "Pins"
    "rating_min": 1200,
    "rating_max": 1399,
    "fen": "r2q3k/pp4pp/8/4N3/8/8/8/6K1 w - - 0 1",  # side to move = participant
    "solution": "e5f7",               # UCI: from-square + to-square (+ promotion piece)
    "solution_notation": "Nf7+",      # shown when the answer is revealed
    "prompt": "Find the fork that attacks two valuable targets.",
    "hints": [                        # practice puzzles only, vague to specific
        "Look for a move that gives check while creating another threat.",
        "A knight can attack two pieces from the same square.",
        "Try moving the knight from e5 to f7.",
    ],
},
```

**Puzzles needed per rating category:** 32 different puzzles (16 forks and
16 pins). 10 are for the warm-up, 12 for practice and 10 for the final check.
The 12 practice puzzles need hints. Across all 9 categories that is 288
puzzles, 108 of which need hints.

**Current limitations:**

- Only puzzles solved in **one move** are supported. Multi-move solutions are
  not implemented yet.
- Puzzles are currently picked at random with repeats, and the warm-up,
  practice and final sets are not kept separate. Before the real study,
  selection needs to be changed so that each participant sees 32 different
  puzzles.
- The coach shows one of three generic questions instead of a question
  written for each puzzle.
- `is_demo` is always `1`, so all data collected so far is demo data.

## Running tests

```bash
python -m unittest discover -s tests
```

The tests always use a temporary SQLite database and never touch
`DATABASE_URL`.
