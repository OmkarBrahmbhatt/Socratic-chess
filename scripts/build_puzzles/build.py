"""Stage 4: write puzzle_data.json for the app from data/selection.json."""
import json
import sys

import chess

from coach_text import coach_text


def main(src, dst):
    out = {}
    for p in json.load(open(src)):
        board = chess.Board(p["fen"])
        p["in_check"] = board.is_check()
        move = chess.Move.from_uci(p["solution"])
        assert move in board.legal_moves, p["id"]
        entry = {
            "theme": p["theme"],
            "rating_band": p["rating_band"],
            "rating_min": p["rating_min"],
            "rating_max": p["rating_max"],
            "rating": p["rating"],
            "set": p["set"],
            "fen": p["fen"],
            "last_move": p["opponent_uci"],
            "solution": p["solution"],
            "solution_notation": p["solution_notation"],
            "line": p["line"],
            "source": f"https://lichess.org/training/{p['id']}",
        }
        if p["set"] == "practice":
            entry["question"], entry["hints"] = coach_text(p)
        out[p["id"]] = entry
    assert len(out) == 288
    json.dump(out, open(dst, "w"), indent=2, ensure_ascii=False)
    print(len(out), "puzzles written", file=sys.stderr)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
