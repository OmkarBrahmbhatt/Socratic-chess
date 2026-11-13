# Socratic Chess

A Flask study prototype for comparing question-based and answer-based chess
tactics practice.

## Run locally

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
flask --app app run --debug
```

Open the local URL printed by Flask in your browser.

## Study flow

1. Participants choose a rating range (Below 400 up to 2000+) and confirm they are 18 or older.
2. Warm-up check: 10 no-feedback puzzle slots.
3. Question-based practice: 6 puzzles, followed by a short slider survey.
4. Answer-based practice: 6 puzzles, followed by the same survey.
5. Final check: 10 no-feedback puzzle slots, followed by a preference question.

In question-based practice, wrong moves prompt a coaching hint. In
answer-based practice, after an attempt participants can either retry or reveal
the answer.

Fork and pin themes are balanced across warm-up, practice conditions, and final
check. The final-check order is shuffled for each participant. Puzzle selection
is currently a demo: two sample positions are repeated to fill the slots.
Replace the entries in `puzzles.py` with verified Lichess puzzle positions,
solutions, and hints before using this app for a real study. The demo board
records a clicked from/to square pair and compares it with its placeholder
answer; legal-move validation and multi-move solutions are not implemented yet.
Demo attempts are marked in the database with `is_demo = 1`.

## Data storage

The app does not ask for a participant's name. It stores the rating range, consent
timestamp, anonymous player code, puzzle themes and attempts, move coordinates,
per-move and per-position elapsed times, hints/retries, and survey responses.

- If `DATABASE_URL` is set (e.g. a Neon Postgres connection string), data is
  stored in that Postgres database. Use this for any deployed instance: hosts
  like Render have ephemeral disks, so a local SQLite file would be wiped on
  each deploy or restart. Tables are created automatically on startup.
- Otherwise data goes to `instance/study.sqlite3` on the machine running Flask
  (handy for local development; tests always use a temporary SQLite file).

For local use, put `DATABASE_URL=...` in a `.env` file (gitignored; loaded by
`flask run`). On Render, add `DATABASE_URL` as an environment variable. Never
commit the connection string. Do not collect real study data until your study
consent and data-retention procedures are finalized.

Set `SOCRATIC_CHESS_SECRET_KEY` to a persistent random secret before running a
shared or deployed instance. Without it, the app generates an in-memory key,
so participant browser sessions will not survive an application restart.

## Run tests

```bash
python -m unittest discover -s tests
```
