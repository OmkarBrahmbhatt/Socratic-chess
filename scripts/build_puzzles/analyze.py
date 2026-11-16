"""Stage 1: verify Lichess fork/pin puzzles and extract facts about the key move.

Reads data/fork_pin.csv, writes data/candidates.jsonl. A puzzle is kept only when
the solver's FIRST move is itself the fork or the pin, so that a one-move answer
check in the app is meaningful.
"""
import csv
import json
import sys

import chess

V = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3, chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 99}
NAME = {chess.PAWN: "pawn", chess.KNIGHT: "knight", chess.BISHOP: "bishop",
        chess.ROOK: "rook", chess.QUEEN: "queen", chess.KING: "king"}


def is_hanging(board, square):
    piece = board.piece_at(square)
    return not board.attackers(piece.color, square)


def in_bad_spot(board, square):
    """The piece on `square` can be taken for free or by something cheaper."""
    piece = board.piece_at(square)
    attackers = board.attackers(not piece.color, square)
    if not attackers:
        return False
    if is_hanging(board, square):
        return True
    return any(V[board.piece_at(a).piece_type] < V[piece.piece_type] for a in attackers)


def fork_facts(after, move, pov):
    """`after` is the board after the solver's move."""
    mover = after.piece_at(move.to_square)
    if mover.piece_type == chess.KING or in_bad_spot(after, move.to_square):
        return None
    targets = []
    for sq in after.attacks(move.to_square):
        piece = after.piece_at(sq)
        if not piece or piece.color == pov or piece.piece_type == chess.PAWN:
            continue
        higher = V[piece.piece_type] > V[mover.piece_type]
        hanging = is_hanging(after, sq) and sq not in after.attackers(not pov, move.to_square)
        if higher or hanging:
            targets.append({"piece": NAME[piece.piece_type], "square": chess.square_name(sq),
                            "why": "king" if piece.piece_type == chess.KING else "higher" if higher else "hanging"})
    if len(targets) < 2:
        return None
    targets.sort(key=lambda t: -V[chess.PIECE_NAMES.index(t["piece"])])
    return {"targets": targets}


def pin_facts(before, after, move, pov):
    """Return how the first move uses an absolute pin, or None."""
    them = not pov
    mover = after.piece_at(move.to_square)
    king_sq = after.king(them)
    for sq, piece in after.piece_map().items():
        if piece.color != them or piece.piece_type == chess.KING:
            continue
        pin_dir = after.pin(them, sq)
        if pin_dir == chess.BB_ALL:
            continue
        pinner_sq = next((a for a in chess.SquareSet(pin_dir)
                          if (p := after.piece_at(a)) and p.color == pov
                          and p.piece_type in (chess.BISHOP, chess.ROOK, chess.QUEEN)
                          and sq in chess.SquareSet(chess.between(a, king_sq))), None)
        if pinner_sq is None:
            continue
        base = {"pinned": NAME[piece.piece_type], "pinned_square": chess.square_name(sq),
                "pinner": NAME[after.piece_at(pinner_sq).piece_type],
                "pinner_square": chess.square_name(pinner_sq),
                "king_square": chess.square_name(king_sq),
                "pin_existed": before.pin(them, sq) != chess.BB_ALL}
        # (a) The moved piece is the pinner and wins the pinned piece (worth more, or loose).
        if pinner_sq == move.to_square and piece.piece_type != chess.PAWN and (
                V[piece.piece_type] > V[mover.piece_type] or is_hanging(after, sq)) \
                and not in_bad_spot_ignoring(after, move.to_square, sq):
            return {**base, "kind": "pin_and_win"}
        # (b) The moved piece attacks an already-pinned, more valuable piece.
        if base["pin_existed"] and move.to_square != pinner_sq and sq in after.attacks(move.to_square) \
                and V[piece.piece_type] > V[mover.piece_type] and not in_bad_spot_ignoring(after, move.to_square, sq):
            return {**base, "kind": "attack_pinned"}
        # (c) The moved piece stands on a square the pinned piece only appears to guard.
        if move.to_square in after.attacks(sq) and move.to_square not in pin_dir:
            others = [a for a in after.attackers(them, move.to_square) if a != sq and after.pin(them, a) == chess.BB_ALL]
            cheaper = [a for a in others if V[after.piece_at(a).piece_type] < V[mover.piece_type]]
            defended = bool(after.attackers(pov, move.to_square))
            if not others or (defended and not cheaper):
                captured = before.piece_at(move.to_square)
                return {**base, "kind": "pinned_cannot_capture",
                        "captured": NAME[captured.piece_type] if captured else None}
    return None


def in_bad_spot_ignoring(board, square, ignore_sq):
    """Like in_bad_spot, but an attacker that is itself the pinned piece on the pin line is handled by value."""
    piece = board.piece_at(square)
    attackers = [a for a in board.attackers(not piece.color, square)]
    if not attackers:
        return False
    if not board.attackers(piece.color, square):
        # Undefended: only fine if the sole attacker is the pinned piece capturing along the pin line
        # and that piece is worth more than ours is not relevant — we simply lose the piece.
        return True
    return any(V[board.piece_at(a).piece_type] < V[piece.piece_type] for a in attackers if a != ignore_sq)


def material(board, color):
    return sum(V[p.piece_type] for p in board.piece_map().values() if p.color == color and p.piece_type != chess.KING)


def analyze(row):
    themes = set(row["Themes"].split())
    is_fork, is_pin = "fork" in themes, "pin" in themes
    if is_fork == is_pin or any(t.startswith("mate") for t in themes):
        return None
    ucis = row["Moves"].split()
    if len(ucis) not in (2, 4, 6):
        return None
    board = chess.Board(row["FEN"])
    opp = chess.Move.from_uci(ucis[0])
    opp_san = board.san(opp)
    board.push(opp)
    pov = board.turn
    shown_fen = board.fen()
    start_diff = material(board, pov) - material(board, not pov)
    key = chess.Move.from_uci(ucis[1])
    if key.promotion and key.promotion != chess.QUEEN:
        return None
    mover = board.piece_at(key.from_square)
    captured = board.piece_at(key.to_square)
    key_san = board.san(key)
    before = board.copy()
    line = [key_san]
    board.push(key)
    after = board.copy()
    facts = fork_facts(after, key, pov) if is_fork else pin_facts(before, after, key, pov)
    if facts is None:
        return None
    for u in ucis[2:]:
        m = chess.Move.from_uci(u)
        line.append(board.san(m))
        board.push(m)
    gain = (material(board, pov) - material(board, not pov)) - start_diff
    return {
        "id": row["PuzzleId"], "theme": "Forks" if is_fork else "Pins",
        "rating": int(row["Rating"]), "rd": int(row["RatingDeviation"]),
        "popularity": int(row["Popularity"]), "plays": int(row["NbPlays"]),
        "themes": sorted(themes), "fen": shown_fen, "opponent_move": opp_san,
        "opponent_uci": opp.uci(), "opponent_to": chess.square_name(opp.to_square),
        "side": "white" if pov else "black",
        "solution": key.uci(), "solution_notation": key_san, "line": line,
        "mover": NAME[mover.piece_type], "from": chess.square_name(key.from_square),
        "to": chess.square_name(key.to_square), "check": after.is_check(),
        "captured": NAME[captured.piece_type] if captured else None,
        "gain": gain, "n_moves": len(ucis), **facts,
    }


def main(src, dst):
    kept = seen = 0
    with open(src) as f, open(dst, "w") as out:
        for row in csv.DictReader(f):
            if int(row["RatingDeviation"]) > 110 or int(row["Popularity"]) < 70 or int(row["NbPlays"]) < 100:
                continue
            seen += 1
            try:
                result = analyze(row)
            except Exception as error:  # malformed row
                print("skip", row["PuzzleId"], error, file=sys.stderr)
                continue
            if result:
                kept += 1
                out.write(json.dumps(result) + "\n")
    print(f"checked {seen}, kept {kept}", file=sys.stderr)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
