#!/bin/sh
# Rebuild puzzle_data.json from the Lichess puzzle database.
# Needs: curl, zstd, and `pip install -r scripts/build_puzzles/requirements.txt`.
# Run from the project root. Downloads about 310 MB into data/ (gitignored).
set -e
here="$(dirname "$0")"
mkdir -p data
[ -f data/lichess_db_puzzle.csv.zst ] || curl -o data/lichess_db_puzzle.csv.zst https://database.lichess.org/lichess_db_puzzle.csv.zst
zstd -dc data/lichess_db_puzzle.csv.zst | awk -F, 'NR==1 || $8 ~ /(^| )(fork|pin)( |$)/' > data/fork_pin.csv
python "$here/analyze.py" data/fork_pin.csv data/candidates.jsonl
python "$here/select_puzzles.py" data/candidates.jsonl data/selection.json
python "$here/build.py" data/selection.json puzzle_data.json
