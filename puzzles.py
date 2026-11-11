import random


PUZZLES = {
    "glyphs": {
        "K": "♔",
        "Q": "♕",
        "R": "♖",
        "B": "♗",
        "N": "♘",
        "P": "♙",
        "k": "♚",
        "q": "♛",
        "r": "♜",
        "b": "♝",
        "n": "♞",
        "p": "♟",
    },
    "fork-demo": {
        "theme": "Forks",
        "rating_min": 0,
        "rating_max": 10000,
        "fen": "r2q3k/pp4pp/8/4N3/8/8/8/6K1 w - - 0 1",
        "solution": "e5f7",
        "solution_notation": "Nf7+",
        "prompt": "Find the fork that attacks two valuable targets.",
        "hints": [
            "Look for a move that gives check while creating another threat.",
            "A knight can attack two pieces from the same square.",
            "Try moving the knight from e5 to f7.",
        ],
        "demo": True,
    },
    "pin-demo": {
        "theme": "Pins",
        "rating_min": 0,
        "rating_max": 10000,
        "fen": "4k3/8/2n5/1B6/8/8/8/4K3 w - - 0 1",
        "solution": "b5c6",
        "solution_notation": "Bxc6+",
        "prompt": "Find a way to use the pinned piece.",
        "hints": [
            "The black knight is in front of its king on the bishop's diagonal.",
            "A pinned defender may not be able to move safely.",
            "Try capturing the knight with the bishop from b5.",
        ],
        "demo": True,
    },
}


def puzzle_slots(count, rating, shuffle=False):
    eligible = [
        puzzle_id
        for puzzle_id, puzzle in PUZZLES.items()
        if puzzle_id != "glyphs"
        and puzzle["rating_min"] <= rating <= puzzle["rating_max"]
    ]
    if not eligible:
        raise ValueError(f"No demo puzzles are configured for rating {rating}.")
    themes = {PUZZLES[puzzle_id]["theme"] for puzzle_id in eligible}
    if themes != {"Forks", "Pins"}:
        raise ValueError("Both fork and pin puzzles must be configured for each rating range.")
    slots = []
    for theme in ("Forks", "Pins"):
        matching = [puzzle_id for puzzle_id in eligible if PUZZLES[puzzle_id]["theme"] == theme]
        slots.extend(random.choice(matching) for _ in range(count // 2))
    if count % 2:
        slots.append(random.choice(eligible))
    if shuffle:
        random.shuffle(slots)
    return slots
