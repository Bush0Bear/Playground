"""Expected-value advisor for Farkle.

Given the dice showing, any dice you are already holding, and the points banked
so far this turn, the advisor works out the *optimal* action: which dice to lock
in, which non-scoring dice (if any) to hold toward a future combo, and whether
to bank the turn or roll again.  "Optimal" means maximising the expected final
score of the turn, correctly accounting for the risk of Farkling.

The engine is a memoised value-iteration over states ``(locked, held,
turn_total)``:

* ``locked``      — how many dice have already scored and been set aside (0..6);
* ``held``        — the multiset of non-scored dice you are carrying forward;
* ``turn_total``  — points banked so far this turn (lost on a Farkle).

It models both household rules:

* **hot dice** — locking the sixth die resets you to a fresh six.
* **holding**  — you may carry non-scoring dice forward to build a combo, but a
  roll Farkles unless it adds a *new* score.  To keep the search finite and fast
  the advisor considers holding at most ``max_held`` dice at once (default 2,
  which covers "hold a pair toward a triple"); the game itself allows more.

Advisor assumption: it evaluates plays that **bank at least one scoring die each
roll** (alongside any dice you hold).  The game rules also permit a "hold only"
move — carry dice and reroll without banking anything this roll — but that makes
the turn a cyclic decision process the exact EV solver can't price, so the
advisor doesn't score it.  Its hold advice (whether/what to hold) is unaffected;
it simply always takes an available scoring die too.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from math import factorial
from typing import Dict, List, Optional, Tuple

from .scoring import (
    Counts,
    Keep,
    ScoreRules,
    DEFAULT_RULES,
    counts_from_dice,
    dice_from_counts,
    legal_keeps,
    max_extract,
)

_EMPTY: Counts = (0, 0, 0, 0, 0, 0, 0)


# --- roll enumeration ------------------------------------------------------

@lru_cache(maxsize=None)
def _outcomes(n: int) -> List[Tuple[Counts, int]]:
    """Every distinct roll of ``n`` dice with its multiplicity (number of
    ordered ways to roll it).  Probabilities are ``multiplicity / 6**n``."""
    results: List[Tuple[Counts, int]] = []

    def rec(face: int, left: int, acc: List[int]):
        if face == 6:
            counts = tuple([0] + acc + [left])
            results.append((counts, _multiplicity(counts)))  # type: ignore[arg-type]
            return
        for take in range(left + 1):
            rec(face + 1, left - take, acc + [take])

    rec(1, n, [])
    return results


def _multiplicity(counts: Counts) -> int:
    n = sum(counts)
    m = factorial(n)
    for face in range(1, 7):
        m //= factorial(counts[face])
    return m


def farkle_probability(n: int, rules: ScoreRules = DEFAULT_RULES) -> float:
    """Probability that rolling ``n`` fresh dice scores nothing."""
    total = 6 ** n
    bad = 0
    for counts, mult in _outcomes(n):
        if not legal_keeps(counts, rules):
            bad += mult
    return bad / total


# --- helpers ---------------------------------------------------------------

def _add(a: Counts, b: Counts) -> Counts:
    return tuple(a[i] + b[i] for i in range(7))  # type: ignore[return-value]


def _sub(a: Counts, dice) -> Counts:
    rem = list(a)
    for f in dice:
        rem[f] -= 1
    return tuple(rem)  # type: ignore[return-value]


def _hold_subsets(counts: Counts, max_held: int):
    """Yield candidate hold sets (as Counts) from ``counts``.

    To keep the search fast we only consider holding a group of a *single* face
    (build one combo at a time, e.g. a pair of 6s toward three 6s) plus the
    empty hold.  Holding two different faces at once is almost never optimal and
    is left to the game engine, not the advisor.
    """
    yield _EMPTY  # hold nothing
    if max_held <= 0:
        return
    for face in range(1, 7):
        avail = min(counts[face], max_held)
        for k in range(1, avail + 1):
            c = [0] * 7
            c[face] = k
            yield tuple(c)  # type: ignore[misc]


# --- decisions -------------------------------------------------------------

@dataclass(frozen=True)
class Decision:
    """The advisor's recommendation for a concrete roll."""

    keep: Keep                     # the dice to LOCK (score and set aside)
    roll_again: bool               # True = reroll, False = bank the turn now
    ev_if_bank: float              # expected turn score if you bank after this
    ev_if_roll: float              # expected turn score if you roll on after this
    turn_total_after: int          # banked points this turn after locking
    reroll_count: int              # dice you would roll next if you roll on
    hold: Tuple[int, ...] = ()     # non-scoring dice carried forward

    @property
    def ev(self) -> float:
        return max(self.ev_if_bank, self.ev_if_roll)

    def describe(self) -> str:
        lock = ", ".join(str(d) for d in self.keep.dice)
        s = f"lock [{lock}] (+{self.keep.score})"
        if self.hold:
            s += f", hold [{', '.join(str(d) for d in self.hold)}]"
        s += "; " + ("ROLL ON" if self.roll_again else "BANK")
        return s


class Advisor:
    """Optimal-play calculator for a fixed rule set.

    Parameters
    ----------
    rules      scoring rules (default: the basic model).
    hot_dice   enable the pick-up-all-six streak rule.
    allow_hold enable the hold rule (carry non-scoring dice toward a combo).
    max_held   most dice the advisor will consider holding at once.
    turn_cap   turn total above which the advisor assumes you just bank (bounds
               the hot-dice recursion; high enough not to affect real play).
    """

    def __init__(
        self,
        rules: ScoreRules = DEFAULT_RULES,
        hot_dice: bool = True,
        allow_hold: bool = False,
        max_held: int = 2,
        turn_cap: int = 10000,
    ) -> None:
        self.rules = rules
        self.hot_dice = hot_dice
        self.allow_hold = allow_hold
        self.max_held = max_held if allow_hold else 0
        self.turn_cap = turn_cap
        self._ev_cache: Dict[Tuple[int, Counts, int], float] = {}
        # Cache of (keep, hold_counts) decisions for a given pool — independent
        # of turn total, so computed once per distinct pool.
        self._pool_cache: Dict[Counts, List[Tuple[Keep, Counts]]] = {}

    # -- public API ---------------------------------------------------------

    def ev_of_rolling(self, dice_to_roll: int, turn_total: int,
                      held: Counts = _EMPTY) -> float:
        """Expected final turn score if you *roll* now with ``dice_to_roll``
        dice to throw, carrying ``held``, and ``turn_total`` banked."""
        if dice_to_roll == 0:            # hot dice: pick all six back up
            return self._ev(0, _EMPTY, min(turn_total, self.turn_cap))
        locked = 6 - dice_to_roll - sum(held)
        return self._ev(locked, held, min(turn_total, self.turn_cap))

    def recommend(self, dice, turn_total: int, held=()) -> Optional[Decision]:
        """Best action for the given roll (with any dice you're already
        holding).  Returns ``None`` on a Farkle."""
        options = self.all_options(dice, turn_total, held)
        return options[0] if options else None

    def all_options(self, dice, turn_total: int, held=()) -> List[Decision]:
        """Every candidate action scored by EV, best first."""
        held_counts = counts_from_dice(held)
        rolled_counts = counts_from_dice(dice)
        pool = _add(held_counts, rolled_counts)
        locked = 6 - sum(pool)

        # Farkle: the new roll adds no score beyond what holding already gave.
        if max_extract(pool, self.rules) <= max_extract(held_counts, self.rules):
            return []

        decisions: List[Decision] = []
        for keep, hold in self._pool_decisions(pool):
            new_locked = locked + len(keep.dice)
            new_total = turn_total + keep.score
            ev_bank, ev_roll, reroll = self._decision_values(
                new_locked, hold, new_total)
            decisions.append(Decision(
                keep=keep,
                hold=tuple(dice_from_counts(hold)),
                roll_again=ev_roll > ev_bank,
                ev_if_bank=ev_bank,
                ev_if_roll=ev_roll if ev_roll != float("-inf") else ev_bank,
                turn_total_after=new_total,
                reroll_count=reroll,
            ))
        decisions.sort(key=lambda d: d.ev, reverse=True)
        return decisions

    # -- internals ----------------------------------------------------------

    def _pool_decisions(self, pool: Counts) -> List[Tuple[Keep, Counts]]:
        """All (lock, hold) pairs for a pool, cached (independent of turn total)."""
        cached = self._pool_cache.get(pool)
        if cached is not None:
            return cached
        decisions: List[Tuple[Keep, Counts]] = []
        for keep in legal_keeps(pool, self.rules):
            remaining = _sub(pool, keep.dice)
            for hold in _hold_subsets(remaining, self.max_held):
                decisions.append((keep, hold))
        self._pool_cache[pool] = decisions
        return decisions

    def _decision_values(self, new_locked: int, hold: Counts,
                         new_total: int) -> Tuple[float, float, int]:
        """Return (ev_bank, ev_roll, reroll_count) for a lock+hold choice."""
        ev_bank = float(new_total)
        if new_locked == 6:
            # All six locked -> hot dice (nothing can be held here).
            if self.hot_dice:
                return ev_bank, self._ev(0, _EMPTY, new_total), 6
            return ev_bank, float("-inf"), 0
        reroll = 6 - new_locked - sum(hold)
        if reroll <= 0:
            return ev_bank, float("-inf"), 0
        return ev_bank, self._ev(new_locked, hold, new_total), reroll

    def _ev(self, locked: int, held: Counts, turn_total: int) -> float:
        """Expected final turn score, playing optimally, when about to roll with
        ``locked`` dice already scored and ``held`` carried forward."""
        dice_to_roll = 6 - locked - sum(held)
        if dice_to_roll <= 0:
            return float(turn_total)
        if turn_total >= self.turn_cap:
            return float(turn_total)

        key = (locked, held, turn_total)
        cached = self._ev_cache.get(key)
        if cached is not None:
            return cached

        total_ways = 6 ** dice_to_roll
        held_extract = max_extract(held, self.rules)
        expected = 0.0
        for rolled, mult in _outcomes(dice_to_roll):
            pool = _add(held, rolled)
            expected += (mult / total_ways) * self._best_value(
                pool, locked, held_extract, turn_total)

        self._ev_cache[key] = expected
        return expected

    def _best_value(self, pool: Counts, locked: int, held_extract: int,
                    turn_total: int) -> float:
        # Farkle if the roll added no new score.
        if max_extract(pool, self.rules) <= held_extract:
            return 0.0
        best = 0.0
        for keep, hold in self._pool_decisions(pool):
            new_locked = locked + len(keep.dice)
            new_total = turn_total + keep.score
            ev_bank, ev_roll, _ = self._decision_values(
                new_locked, hold, new_total)
            val = ev_bank if ev_roll == float("-inf") else max(ev_bank, ev_roll)
            if val > best:
                best = val
        return best
