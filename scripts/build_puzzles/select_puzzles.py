"""Stage 2: pick 16 forks + 16 pins per rating category and split them into sets."""
import collections
import json
import random
import statistics
import sys

# (category label, app rating lower bound, app upper bound, puzzle rating range used)
BANDS = [
    ("Below 400", 0, 399, (399, 550)),      # Lichess has no puzzles under 399: use the easiest
    ("400-800", 400, 799, (550, 800)),
    ("800-1000", 800, 999, (800, 1000)),
    ("1000-1200", 1000, 1199, (1000, 1200)),
    ("1200-1400", 1200, 1399, (1200, 1400)),
    ("1400-1600", 1400, 1599, (1400, 1600)),
    ("1600-1800", 1600, 1799, (1600, 1800)),
    ("1800-2000", 1800, 1999, (1800, 2000)),
    ("2000+", 2000, 10000, (2000, 2400)),
]
TIERS = [(80, 92, 3000), (85, 88, 1500), (90, 85, 800), (95, 80, 400), (110, 70, 100)]  # rd<=, pop>=, plays>=
FORK_QUOTA = [("knight", 5), ("queen", 4), ("bishop", 3), ("rook", 2), ("pawn", 2)]
PIN_QUOTA = [("pin_and_win", 8), ("pinned_cannot_capture", 6), ("attack_pinned", 2)]
SETS = {"warmup": 5, "practice": 6, "final": 5}


def dest(san):
    return san.rstrip("+#").split("=")[0][-2:]


def cashes_in(p):
    if p["n_moves"] != 4:
        return False
    follow = p["line"][2]
    if p["theme"] == "Forks":
        return p["gain"] >= 2 and "x" in follow and dest(follow) in {t["square"] for t in p["targets"]}
    if p["kind"] == "pinned_cannot_capture":
        return p["gain"] >= 1 and p["captured"] is not None
    return p["gain"] >= 1 and "x" in follow


def tier(p):
    for index, (rd, pop, plays) in enumerate(TIERS):
        if p["rd"] <= rd and p["popularity"] >= pop and p["plays"] >= plays:
            return index
    return None


def choose(pool, quota, lo, hi, rng):
    """Fill the quota with the best-quality puzzles, spread across the rating range."""
    key = "mover" if pool and pool[0]["theme"] == "Forks" else "kind"
    groups = collections.defaultdict(list)
    for p in pool:
        groups[p[key]].append(p)
    for items in groups.values():
        rng.shuffle(items)
        items.sort(key=lambda p: (p["tier"], -p["popularity"], -p["plays"]))
    quartile = lambda p: min(3, int((p["rating"] - lo) / (hi - lo) * 4))
    used_q, picked, seen = collections.Counter(), [], set()
    want = sum(n for _, n in quota)

    def take(group):
        best = None
        for p in groups.get(group, []):
            if p["id"] in seen or p["fen"].split()[0] in seen:
                continue
            score = (used_q[quartile(p)], p["tier"])
            if best is None or score < best[0]:
                best = (score, p)
                if score == (min(used_q[q] for q in range(4)), 0):
                    break
        if best is None:
            return False
        p = best[1]
        picked.append(p); seen.update((p["id"], p["fen"].split()[0])); used_q[quartile(p)] += 1
        return True

    for group, n in quota:
        for _ in range(n):
            take(group)
    names = [g for g, _ in quota]
    while len(picked) < want:  # top up from whichever groups still have puzzles
        if not any(take(g) for g in names):
            break
    return picked


def split(puzzles, rng):
    """Assign warm-up / practice / final so average ratings (and tactic types) match."""
    key = "mover" if puzzles[0]["theme"] == "Forks" else "kind"
    labels = [s for s, n in SETS.items() for _ in range(n)]
    best = None
    for _ in range(4000):
        rng.shuffle(labels)
        means, kinds = {}, {}
        for s in SETS:
            members = [p for p, l in zip(puzzles, labels) if l == s]
            means[s] = statistics.mean(p["rating"] for p in members)
            kinds[s] = len({p[key] for p in members})
        cost = (max(means.values()) - min(means.values())) - 3 * sum(kinds.values()) \
            + 2 * abs(means["warmup"] - means["final"])
        if best is None or cost < best[0]:
            best = (cost, list(labels))
    for p, label in zip(puzzles, best[1]):
        p["set"] = label


def main(src, dst):
    rng = random.Random(20261116)
    by_band = collections.defaultdict(list)
    for line in open(src):
        p = json.loads(line)
        p["tier"] = tier(p)
        if p["tier"] is None or not cashes_in(p):
            continue
        for label, _lo, _hi, (rlo, rhi) in BANDS:
            if rlo <= p["rating"] < rhi:
                by_band[(label, p["theme"])].append(p)
    out = []
    for label, lo, hi, (rlo, rhi) in BANDS:
        for theme, quota in (("Forks", FORK_QUOTA), ("Pins", PIN_QUOTA)):
            pool = by_band[(label, theme)]
            picked = choose(pool, quota, rlo, rhi, rng)
            assert len(picked) == 16, (label, theme, len(picked), len(pool))
            split(picked, rng)
            for p in picked:
                p.update(rating_band=label, rating_min=lo, rating_max=hi)
            out.extend(picked)
            key = "mover" if theme == "Forks" else "kind"
            mix = collections.Counter(p[key] for p in picked)
            means = {s: round(statistics.mean(p["rating"] for p in picked if p["set"] == s)) for s in SETS}
            print(f"{label:10} {theme:5} pool={len(pool):6} tiers={sorted(collections.Counter(p['tier'] for p in picked).items())} "
                  f"ratings={min(p['rating'] for p in picked)}-{max(p['rating'] for p in picked)} means={means} mix={dict(mix)}",
                  file=sys.stderr)
    json.dump(out, open(dst, "w"), indent=1)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
