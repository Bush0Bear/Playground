"""Farkle scoring engine.

The scoring rules in Farkle vary a lot from household to household, so every
value lives in a :class:`ScoreRules` config object that you can tweak.  The
defaults below match the most common commercially published rule set.

The core primitive is :func:`score_selection`: given a multiset of dice a
player wants to *keep*, it returns the maximum score achievable while using
**every** kept die in some scoring combination (or ``None`` if some die cannot
score, which would make the selection illegal).

We always compute the *best* partition of the selection.  For example four 1s
can score as a four-of-a-kind (1000) or as three-of-a-kind (1000) plus a loose
1 (100); we take the higher 1100.  This mirrors how players actually pick the
most valuable interpretation of their dice.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from typing import Dict, List, Optional, Tuple

# A "counts" tuple has 7 slots (index 0 unused) so counts[face] is the number
# of dice showing that face.  Using a plain tuple keeps everything hashable and
# cheap to memoize.
Counts = Tuple[int, int, int, int, int, int, int]


def counts_from_dice(dice) -> Counts:
    """Turn an iterable of face values (1-6) into a Counts tuple."""
    c = [0] * 7
    for d in dice:
        if not 1 <= d <= 6:
            raise ValueError(f"die value {d!r} is not between 1 and 6")
        c[d] += 1
    return tuple(c)  # type: ignore[return-value]


def dice_from_counts(counts: Counts) -> List[int]:
    """Expand a Counts tuple back into a sorted list of face values."""
    dice: List[int] = []
    for face in range(1, 7):
        dice.extend([face] * counts[face])
    return dice


@dataclass(frozen=True)
class ScoreRules:
    """All the tunable numbers that define a Farkle scoring variant.

    Only ``single`` and ``three_of_a_kind`` are always active.  Every other
    field is optional: leave it ``None`` to disable that combination.  This lets
    the default rules be the *most basic* model (just 1s, 5s, and three of a
    kind) while a richer variant can switch the extras on.
    """

    single: Dict[int, int] = field(
        default_factory=lambda: {1: 100, 5: 50}
    )
    # Three-of-a-kind values keyed by face.
    three_of_a_kind: Dict[int, int] = field(
        default_factory=lambda: {1: 1000, 2: 200, 3: 300, 4: 400, 5: 500, 6: 600}
    )
    four_of_a_kind: Optional[int] = None
    five_of_a_kind: Optional[int] = None
    six_of_a_kind: Optional[int] = None
    straight: Optional[int] = None          # 1-2-3-4-5-6
    three_pairs: Optional[int] = None
    two_triplets: Optional[int] = None
    four_plus_pair: Optional[int] = None    # four-of-a-kind + a pair

    def n_of_a_kind(self, face: int, n: int) -> Optional[int]:
        """Score for exactly ``n`` dice of ``face`` (n in 3..6), or None when
        that group size is not a scoring combination in this variant."""
        if n == 3:
            return self.three_of_a_kind[face]
        if n == 4:
            return self.four_of_a_kind
        if n == 5:
            return self.five_of_a_kind
        if n == 6:
            return self.six_of_a_kind
        return None


# The most basic model: single 1s and 5s, plus three-of-a-kind.  No
# four/five/six-of-a-kind bonuses, straights, pairs, or two-triplet combos.
BASIC_RULES = ScoreRules()

# A fuller, commonly published variant with the extra combinations switched on.
STANDARD_RULES = ScoreRules(
    four_of_a_kind=1000,
    five_of_a_kind=2000,
    six_of_a_kind=3000,
    straight=1500,
    three_pairs=1500,
    two_triplets=2500,
    four_plus_pair=1500,
)

# The default used everywhere unless a caller passes their own rules.
DEFAULT_RULES = BASIC_RULES


# --- core partition scorer -------------------------------------------------

@lru_cache(maxsize=None)
def _best_partition(counts: Counts, rules_id: int) -> Optional[int]:
    """Max score using *every* die in ``counts`` via singles + N-of-a-kind +
    straight.  Returns None when the dice cannot all be consumed.

    ``rules_id`` is ``id(rules)``; the actual rules object is fetched from a
    registry so the function stays hashable/cacheable.
    """
    rules = _RULES_REGISTRY[rules_id]

    if sum(counts) == 0:
        return 0

    best: Optional[int] = None

    def consider(points: int, remaining: Counts) -> None:
        nonlocal best
        sub = _best_partition(remaining, rules_id)
        if sub is not None:
            total = points + sub
            if best is None or total > best:
                best = total

    # Straight 1-6 (consumes exactly one of each face).
    if rules.straight is not None and all(counts[f] >= 1 for f in range(1, 7)):
        rem = list(counts)
        for f in range(1, 7):
            rem[f] -= 1
        consider(rules.straight, tuple(rem))  # type: ignore[arg-type]

    # N-of-a-kind for each face, trying every group size we can take so the
    # recursion finds the highest-scoring split.
    for face in range(1, 7):
        c = counts[face]
        for take in range(3, min(c, 6) + 1):
            val = rules.n_of_a_kind(face, take)
            if val is None:
                continue
            rem = list(counts)
            rem[face] -= take
            consider(val, tuple(rem))  # type: ignore[arg-type]

    # Loose single 1s and 5s.
    for face, val in rules.single.items():
        if counts[face] >= 1:
            rem = list(counts)
            rem[face] -= 1
            consider(val, tuple(rem))  # type: ignore[arg-type]

    return best


_RULES_REGISTRY: Dict[int, ScoreRules] = {id(DEFAULT_RULES): DEFAULT_RULES}


def _register(rules: ScoreRules) -> int:
    _RULES_REGISTRY[id(rules)] = rules
    return id(rules)


def _is_three_pairs(counts: Counts) -> bool:
    if sum(counts) != 6:
        return False
    pairs = 0
    for face in range(1, 7):
        c = counts[face]
        if c == 2:
            pairs += 1
        elif c == 4:
            pairs += 2          # four of a kind counts as two pairs
        elif c == 6:
            pairs += 3
        elif c != 0:
            return False
    return pairs == 3


def _is_two_triplets(counts: Counts) -> bool:
    if sum(counts) != 6:
        return False
    triplets = sum(1 for face in range(1, 7) if counts[face] == 3)
    return triplets == 2


def _is_four_plus_pair(counts: Counts) -> bool:
    if sum(counts) != 6:
        return False
    has_four = any(counts[f] == 4 for f in range(1, 7))
    has_pair = any(counts[f] == 2 for f in range(1, 7))
    return has_four and has_pair


def score_selection(counts: Counts, rules: ScoreRules = DEFAULT_RULES) -> Optional[int]:
    """Best score for keeping exactly the dice in ``counts``.

    Returns ``None`` if the selection is illegal (contains a die that cannot
    take part in any scoring combination).
    """
    rules_id = _register(rules)
    candidates: List[int] = []

    base = _best_partition(counts, rules_id)
    if base is not None:
        candidates.append(base)

    # Whole-hand combos only apply to a full set of six kept dice, and only
    # when the variant enables them.
    if sum(counts) == 6:
        if rules.three_pairs is not None and _is_three_pairs(counts):
            candidates.append(rules.three_pairs)
        if rules.two_triplets is not None and _is_two_triplets(counts):
            candidates.append(rules.two_triplets)
        if rules.four_plus_pair is not None and _is_four_plus_pair(counts):
            candidates.append(rules.four_plus_pair)

    return max(candidates) if candidates else None


def score_dice(dice, rules: ScoreRules = DEFAULT_RULES) -> Optional[int]:
    """Convenience wrapper: score a list/iterable of face values."""
    return score_selection(counts_from_dice(dice), rules)


# --- enumerating legal keeps ----------------------------------------------

@dataclass(frozen=True)
class Keep:
    """One legal way to set dice aside from a roll."""

    dice: Tuple[int, ...]      # the face values kept, sorted
    score: int                 # points earned for this keep
    remaining: int             # dice left to (optionally) reroll

    def describe(self) -> str:
        faces = ", ".join(str(d) for d in self.dice)
        return f"keep [{faces}] for {self.score} pts ({self.remaining} dice left)"


def _sub_counts(counts: Counts):
    """Yield every sub-multiset of ``counts`` (including the empty one)."""
    ranges = [range(counts[f] + 1) for f in range(1, 7)]

    def rec(face: int, acc: List[int]):
        if face > 6:
            yield tuple([0] + acc)
            return
        for take in ranges[face - 1]:
            yield from rec(face + 1, acc + [take])

    yield from rec(1, [])


_KEEPS_CACHE: Dict[Tuple[Counts, int], List["Keep"]] = {}


def legal_keeps(counts: Counts, rules: ScoreRules = DEFAULT_RULES) -> List[Keep]:
    """All legal, non-empty keeps from a roll described by ``counts``.

    Each returned keep uses only fully-scoring dice.  We de-duplicate by the
    kept face multiset and, for identical multisets, keep the highest score.
    Results are cached because the advisor asks for the same rolls many times.
    """
    rules_id = _register(rules)
    cache_key = (counts, rules_id)
    cached = _KEEPS_CACHE.get(cache_key)
    if cached is not None:
        return cached

    total = sum(counts)
    best_by_dice: Dict[Tuple[int, ...], Keep] = {}

    for sub in _sub_counts(counts):
        kept = sum(sub)
        if kept == 0:
            continue
        score = score_selection(sub, rules)  # type: ignore[arg-type]
        if score is None:
            continue
        dice = tuple(dice_from_counts(sub))  # type: ignore[arg-type]
        keep = Keep(dice=dice, score=score, remaining=total - kept)
        prev = best_by_dice.get(dice)
        if prev is None or keep.score > prev.score:
            best_by_dice[dice] = keep

    result = sorted(best_by_dice.values(), key=lambda k: (-k.score, k.remaining))
    _KEEPS_CACHE[cache_key] = result
    return result


def has_score(counts: Counts, rules: ScoreRules = DEFAULT_RULES) -> bool:
    """True if the roll has at least one scoring die (i.e. it's not a Farkle)."""
    return bool(legal_keeps(counts, rules))
