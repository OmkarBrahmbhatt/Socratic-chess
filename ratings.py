"""Turn whatever rating a participant reports into a puzzle category.

The puzzles are graded on the Lichess puzzle rating scale. Participants can
report a rating from another system (FIDE, US Chess, Chess.com, Lichess games)
or describe their experience if they have no rating. This module converts the
answer to an estimated rating on the puzzle scale, and that estimate picks the
category of puzzles they get.

The conversions are approximate. Everything a researcher may want to tune is
in this file: the comparison table, PUZZLE_SCALE_OFFSET and EXPERIENCE_LEVELS.
"""

# Puzzle categories (and the rating ranges participants choose from): the
# label and the lowest rating in it. The puzzles in puzzle_data.json use the
# same labels.
RATING_BANDS = {
    "Below 400": 0,
    "400-800": 400,
    "800-1000": 800,
    "1000-1200": 1000,
    "1200-1400": 1200,
    "1400-1600": 1400,
    "1600-1800": 1600,
    "1800-2000": 1800,
    "2000+": 2000,
}

# A participant picks a range, not an exact number; the range is converted
# through this representative value.
RANGE_MIDPOINTS = {
    "Below 400": 300,
    "400-800": 600,
    "800-1000": 900,
    "1000-1200": 1100,
    "1200-1400": 1300,
    "1400-1600": 1500,
    "1600-1800": 1700,
    "1800-2000": 1900,
    "2000+": 2100,
}

# Rating systems offered on the start page, in display order:
# key -> (group, label, how to convert it, short name used in "What is your ... rating?").
#   "identity" - already on the puzzle scale, used as is
#   a column name of COMPARISON - converted through the table
RATING_SYSTEMS = {
    "fide": ("Over-the-board", "FIDE", "fide", "FIDE"),
    "uscf": ("Over-the-board", "US Chess (USCF)", "uscf", "US Chess"),
    "national": ("Over-the-board", "Other national federation (e.g. ECF, AICF)", "fide", "national"),
    "chesscom_rapid": ("Chess.com", "Chess.com Rapid", "chesscom_rapid", "Chess.com Rapid"),
    "chesscom_blitz": ("Chess.com", "Chess.com Blitz", "chesscom_blitz", "Chess.com Blitz"),
    "lichess_rapid": ("Lichess", "Lichess Rapid", "lichess_rapid", "Lichess Rapid"),
    "lichess_blitz": ("Lichess", "Lichess Blitz", "lichess_blitz", "Lichess Blitz"),
    "lichess_puzzles": ("Lichess", "Lichess Puzzles", "identity", "Lichess puzzle"),
}
NO_RATING = "none"

# Equivalent ratings from the ChessGoals rating comparison
# (https://chessgoals.com/rating-comparison/, updated July 2026). Each row is
# one Chess.com blitz rating and what active players at that level typically
# have elsewhere. Built from players with accounts in both systems: about
# 10,000 for Chess.com rapid, 1,900 for FIDE, 1,800 for USCF and 1,000-1,900
# for Lichess. None means the source has no FIDE value that low.
COMPARISON_COLUMNS = (
    "chesscom_blitz", "chesscom_rapid", "uscf", "fide", "lichess_blitz", "lichess_rapid",
)
COMPARISON = [
    (500, 815, 925, None, 1090, 1290),
    (600, 905, 1000, None, 1160, 1360),
    (700, 995, 1075, None, 1225, 1425),
    (800, 1085, 1150, None, 1290, 1490),
    (900, 1170, 1220, None, 1360, 1555),
    (1000, 1255, 1285, None, 1425, 1615),
    (1100, 1340, 1350, 1660, 1490, 1680),
    (1200, 1420, 1415, 1670, 1555, 1740),
    (1300, 1500, 1475, 1685, 1620, 1795),
    (1400, 1580, 1540, 1710, 1685, 1850),
    (1500, 1655, 1600, 1740, 1755, 1905),
    (1600, 1730, 1655, 1780, 1820, 1960),
    (1700, 1800, 1715, 1820, 1885, 2015),
    (1800, 1870, 1775, 1865, 1950, 2065),
    (1900, 1935, 1835, 1915, 2015, 2115),
    (2000, 1995, 1890, 1965, 2080, 2165),
    (2100, 2055, 1950, 2020, 2145, 2215),
    (2200, 2110, 2010, 2075, 2210, 2260),
    (2300, 2165, 2070, 2135, 2275, 2310),
    (2400, 2215, 2130, 2190, 2340, 2355),
    (2500, 2260, 2195, 2245, 2410, 2400),
    (2600, 2300, 2255, 2300, 2475, 2445),
    (2700, 2340, 2325, 2350, 2540, 2490),
    (2800, 2375, 2390, 2400, 2610, 2530),
    (2900, 2405, 2460, 2445, 2675, 2575),
    (3000, 2430, 2535, 2485, 2745, 2615),
]

# Game ratings are converted to their Lichess rapid equivalent, which is then
# treated as a puzzle-scale rating plus this offset. Players' puzzle ratings
# usually run higher than their game ratings, but there is no reliable figure
# for how much, so the default is 0. Raising it gives players with game
# ratings harder puzzles. Lichess puzzle ratings are never offset.
PUZZLE_SCALE_OFFSET = 0

# For participants without a rating: key -> (description, estimated
# puzzle-scale rating). These estimates are judgement calls, not data.
EXPERIENCE_LEVELS = {
    "new": ("I'm new to chess and still learning how the pieces move", 300),
    "rules": ("I know the rules but rarely play", 600),
    "casual": ("I play casually, online or with friends", 1100),
    "regular": ("I play regularly and know tactics like forks and pins", 1500),
    "club": ("I play in a club or in tournaments", 1700),
}


def grouped_systems():
    """[(group, [(key, label, short), ...]), ...] in display order, for the start page."""
    groups = {}
    for key, (group, label, _method, short) in RATING_SYSTEMS.items():
        groups.setdefault(group, []).append((key, label, short))
    return list(groups.items())


def _column(name):
    index = COMPARISON_COLUMNS.index(name)
    target = COMPARISON_COLUMNS.index("lichess_rapid")
    return [(row[index], row[target]) for row in COMPARISON if row[index] is not None]


def _interpolate(points, value):
    """Linear interpolation between table rows.

    Outside the table, assume one point here is worth one point there,
    counted from the nearest end of the table.
    """
    if value <= points[0][0]:
        return points[0][1] - (points[0][0] - value)
    if value >= points[-1][0]:
        return points[-1][1] + (value - points[-1][0])
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if x0 <= value <= x1:
            return y0 + (value - x0) * (y1 - y0) / (x1 - x0)
    raise AssertionError("unreachable")


def puzzle_scale_rating(system, rating_band=None, experience=None):
    """Estimated rating on the Lichess puzzle scale (an int, never negative)."""
    if system == NO_RATING:
        return EXPERIENCE_LEVELS[experience][1]
    value = RANGE_MIDPOINTS[rating_band]
    method = RATING_SYSTEMS[system][2]
    if method == "identity":
        estimate = value
    elif method == "lichess_rapid":
        estimate = value + PUZZLE_SCALE_OFFSET
    else:
        estimate = _interpolate(_column(method), value) + PUZZLE_SCALE_OFFSET
    return max(0, round(estimate))


def band_for(rating):
    """The puzzle category a puzzle-scale rating falls in."""
    return max((band for band, low in RATING_BANDS.items() if low <= rating), key=RATING_BANDS.get)
