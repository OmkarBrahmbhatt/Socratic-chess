"""Stage 3: write the Socratic question and three graded hints for a puzzle."""
import zlib

import chess


def _pick(options, puzzle):
    return options[zlib.crc32(puzzle["id"].encode()) % len(options)]


def _line_type(a, b):
    a, b = chess.parse_square(a), chess.parse_square(b)
    if chess.square_file(a) == chess.square_file(b):
        return "file"
    if chess.square_rank(a) == chess.square_rank(b):
        return "rank"
    return "diagonal"


def _an(word):
    return f"an {word}" if word[0] in "aeiou" else f"a {word}"


def _join(items):
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def fork_text(p, opp):
    targets = p["targets"]
    named = [f"{t['piece']} on {t['square']}" for t in targets]
    lead = f"{opp} just played {p['opponent_move']}."
    king = any(t["piece"] == "king" for t in targets)
    loose = [t for t in targets if t["why"] == "hanging"]
    mover, san = p["mover"], p["solution_notation"]
    landed = next((t for t in targets if t["square"] == p["opponent_to"]), None)
    if p.get("in_check"):
        question = (f"{lead} You are in check. Which way of answering the check also attacks "
                    f"two of {opp}'s pieces at the same time?")
    elif landed and landed["piece"] == "king" and p["check"]:
        question = _pick([
            f"{opp}'s king has just stepped to {landed['square']}. Which checks does that square allow, and what else would the checking piece attack?",
            f"{lead} Is the king safe on its new square? Which check would attack a second piece at the same time?",
        ], p)
    elif landed and p["check"] and king:
        question = _pick([
            f"{opp}'s {landed['piece']} has just landed on {landed['square']}. Is it safe there? Look at your checks: does one of them attack the {landed['piece']} too?",
            f"{lead} What do the {landed['piece']}'s new square and the king's square have in common? Which of your pieces could attack both?",
        ], p)
    elif landed:
        question = _pick([
            f"{opp}'s {landed['piece']} has just landed on {landed['square']}. Which other valuable piece could be attacked together with it, and from which square?",
            f"{lead} Is the {landed['piece']} safe on its new square? Can one of your pieces attack it and something else in the same move?",
        ], p)
    elif p["check"] and king:
        question = _pick([
            f"{lead} Which checks do you have in this position? For each one, what else would the checking piece attack?",
            f"{lead} {opp}'s king has to answer every check. Is there a check that also attacks a second piece?",
            f"{lead} Look at the squares around {opp}'s king. Which of your pieces can give check, and what would it hit at the same moment?",
        ], p)
        hint1 = (f"{opp}'s king on {next(t['square'] for t in targets if t['piece'] == 'king')} can be checked. "
                 f"Find the check that also attacks the {named[1] if targets[0]['piece'] == 'king' else named[0]}.")
        hint2 = (f"Your {mover} on {p['from']} can reach a square that attacks the {_join(named)} together. "
                 f"{opp} must deal with the check first, so the other piece is lost.")
    elif loose:
        question = _pick([
            f"{lead} Which of {opp}'s pieces have no defender right now? Can a single move of yours attack two valuable pieces at once?",
            f"{lead} What did that move leave loose? Is there one square from which a piece of yours attacks two targets?",
            f"{lead} Count the defenders of each of {opp}'s pieces. Which two could you attack with one move?",
        ], p)
        hint1 = f"Look at {opp}'s {_join(named)}. {opp} can only save one of them in a single move."
        hint2 = f"Your {mover} on {p['from']} can move to a square that attacks the {_join(named)} at the same time."
    else:
        question = _pick([
            f"{lead} Which of {opp}'s pieces are worth more than your {mover}? Can your {mover} attack two of them at once?",
            f"{lead} Your {mover} is worth less than several of {opp}'s pieces. Which square lets it threaten two of them together?",
            f"{lead} If your {mover} attacks a more valuable piece, that piece has to move. What happens if it attacks two?",
        ], p)
        hint1 = f"Look at {opp}'s {_join(named)}. Each is worth more than {_an(mover)}, so each has to run when attacked."
        hint2 = f"Your {mover} on {p['from']} can move to a square that attacks the {_join(named)} at the same time."
    # Hints depend only on the kind of fork, not on which question was asked.
    if p["check"] and king:
        hint1 = (f"{opp}'s king on {next(t['square'] for t in targets if t['piece'] == 'king')} can be checked. "
                 f"Find the check that also attacks the {named[1] if targets[0]['piece'] == 'king' else named[0]}.")
        hint2 = (f"Your {mover} on {p['from']} can reach a square that attacks the {_join(named)} together. "
                 f"{opp} must deal with the check first, so the other piece is lost.")
    elif loose:
        hint1 = f"Look at {opp}'s {_join(named)}. {opp} can only save one of them in a single move."
        hint2 = f"Your {mover} on {p['from']} can move to a square that attacks the {_join(named)} at the same time."
    else:
        hint1 = f"Look at {opp}'s {_join(named)}. Each is worth more than {_an(mover)}, so each has to run when attacked."
        hint2 = f"Your {mover} on {p['from']} can move to a square that attacks the {_join(named)} at the same time."
    capture = f", capturing the {p['captured']}," if p["captured"] else ""
    hint3 = (f"Play {san}: move the {mover} from {p['from']} to {p['to']}{capture} "
             f"to fork the {_join([t['piece'] for t in targets])}.")
    return question, [hint1, hint2, hint3]


def pin_text(p, opp):
    lead = f"{opp} just played {p['opponent_move']}."
    line = _line_type(p["pinned_square"], p["king_square"])
    pinned, psq, ksq = p["pinned"], p["pinned_square"], p["king_square"]
    mover, san, kind = p["mover"], p["solution_notation"], p["kind"]
    capture = f", capturing the {p['captured']}" if p["captured"] else ""
    slides = pinned == "queen" or (pinned == "rook" and line != "diagonal") or (pinned == "bishop" and line == "diagonal")
    stuck = (f"the {pinned} may slide along the {line} but can never leave it" if slides
             else f"the {pinned} cannot move at all")
    landed = p["opponent_to"] in (psq, ksq)
    if kind == "pin_and_win":
        if p["pin_existed"]:
            question = _pick([
                f"{lead} One of {opp}'s pieces cannot leave its line without exposing the king. Which piece is it, and how can you win it?",
                f"{lead} Which of {opp}'s pieces is tied to a line in front of its king? What can you do to a piece that cannot get away?",
            ], p)
            hint1 = f"{opp}'s {pinned} on {psq} is pinned: it stands on the same {line} as the king on {ksq} and cannot leave it."
            hint2 = f"A pinned piece cannot escape. Use your {mover} on that {line} to attack the {pinned}."
        else:
            if landed:
                who = pinned if p["opponent_to"] == psq else "king"
                question = _pick([
                    f"{opp}'s {who} has just moved to {p['opponent_to']}. What else of {opp}'s stands on that {line}, and why could that be a problem?",
                    f"{lead} Look along the {line} that the {who} now stands on. Which two of {opp}'s pieces are lined up, and which of your pieces can use that line?",
                ], p)
            else:
                question = _pick([
                    f"{lead} Which of {opp}'s pieces stands on the same {line} as its own king? What happens to a piece that is not allowed to leave that {line}?",
                    f"{lead} Look at the {line}s leading to {opp}'s king. Is a valuable piece standing in front of the king on one of them?",
                    f"{lead} A piece standing in front of its king can be pinned. Which of {opp}'s pieces could you pin, and with which of your pieces?",
                ], p)
            hint1 = f"{opp}'s {pinned} on {psq} and king on {ksq} are on the same {line}, with nothing between them."
            hint2 = (f"If your {mover} attacks the {pinned} along that {line}, {stuck}, "
                     f"because leaving the {line} would put its own king in check.")
        hint3 = (f"Play {san}: move the {mover} from {p['from']} to {p['to']}{capture}. "
                 f"The {pinned} on {psq} is pinned to the king, so you win material.")
    elif kind == "attack_pinned":
        pline = _line_type(p["pinned_square"], p["king_square"])
        question = _pick([
            f"{lead} One of {opp}'s pieces is pinned to its king and cannot get away. Which piece is it, and what is the cheapest piece you can attack it with?",
            f"{lead} Which of {opp}'s pieces is pinned in front of its king? A piece that cannot get away can be attacked again. With what?",
        ], p)
        hint1 = (f"Your {p['pinner']} on {p['pinner_square']} pins the {pinned} on {psq} to the king on {ksq}. "
                 f"The {pinned} cannot leave that {pline}.")
        hint2 = f"Attack the pinned {pinned} with your {mover}. It is worth more than {_an(mover)} and it cannot get off the {pline}."
        hint3 = f"Play {san}: move the {mover} from {p['from']} to {p['to']}{capture}. The pinned {pinned} cannot escape."
    else:  # pinned_cannot_capture
        question = _pick([
            f"{lead} Which of {opp}'s pieces is pinned to its king? What is that piece supposed to be defending?",
            f"{lead} Some of {opp}'s defenders are not free to move. Which piece only looks like it is protecting something?",
            f"{lead} Before trusting a defender, check whether it is allowed to move. Which of {opp}'s pieces is tied to its king?",
        ], p)
        hint1 = (f"Your {p['pinner']} on {p['pinner_square']} pins the {pinned} on {psq} to the king on {ksq}. "
                 f"The {pinned} cannot leave that {line}.")
        if not p["pin_existed"]:
            question = _pick([
                f"{lead} Your {p['pinner']} and {opp}'s king stand on the same {line}. What happens to the pieces between them if your own piece moves off that {line}?",
                f"{lead} Which of {opp}'s pieces would be pinned to its king if one of your own pieces stepped off the {line}? What is that piece supposed to be defending?",
            ], p)
            hint1 = (f"Your {p['pinner']} on {p['pinner_square']} and {opp}'s king on {ksq} are on the same {line}. "
                     f"When your {mover} leaves that {line}, the {pinned} on {psq} becomes pinned.")
        if p["captured"]:
            hint2 = (f"The {pinned} looks like it defends the {p['captured']} on {p['to']}, "
                     f"but capturing there would expose its king, so it is not a real defender.")
        else:
            hint2 = f"The {pinned} looks like it guards {p['to']}, but it cannot legally capture there."
        hint3 = (f"Play {san}: move the {mover} from {p['from']} to {p['to']}{capture}. "
                 f"The pinned {pinned} cannot take back.")
    return question, [hint1, hint2, hint3]


def coach_text(p):
    opp = "Black" if p["side"] == "white" else "White"
    return fork_text(p, opp) if p["theme"] == "Forks" else pin_text(p, opp)
