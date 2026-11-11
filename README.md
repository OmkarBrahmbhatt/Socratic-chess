# Socratic Chess

A Flask web app for deliberate, study-focused chess practice.

## Run locally

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
flask --app app run --debug
```

Open the local URL printed by Flask in your browser.

## Current starting point

The home page accepts a player's rating and validates it on the server. Puzzle
selection, puzzle content, move/position timing, and persistence are not
implemented yet; those can be shaped as the product requirements are defined.

## Run tests

```bash
python -m unittest discover -s tests
```
