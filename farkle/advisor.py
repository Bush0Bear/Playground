"""Expected-value advisor for Farkle.

Given the dice currently showing and the points banked so far this turn, the
advisor works out the *optimal* action: which dice to set aside and whether to
bank the turn or roll again.  "Optimal" here means maximising the expected
final score of the turn, correctly accounting for the risk of Farkling (rolling
no scoring dice and losing everything banked this turn).

The engine is a memoised value-iteration over states ``(dice_to_roll,
turn_total)``.  It fully models the household "hot dice" rule: whenever all six
dice have scored, you may pick them all back up and keep the streak going.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from math import factorial
from typing import Dict, List, Optional, Tuple

from .scoring import (
    Counts,
    Keep,
    ScoreRules,
    DEFAULT_RULES,
    counts_from_dice,
    legal_keeps,
)


# --- roll enumeration ------------------------------------------------------

@lru_cache(maxsize=None)
def _outcomes(n: int) -> List[Tuple[Counts, int]]:
    """Every distinct roll of ``n`` dice with its multiplicity (number of
    ordered ways to roll it).  Probabilities are ``multiplicity / 6**n``.
    """
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


# --- value iteration -------------------------------------------------------

@dataclass(frozen=True)
class Decision:
    """The advisor's recommendation for a concrete roll."""

    keep: Keep                 # which dice to set aside
    roll_again: bool           # True = reroll, False = bank the turn now
    ev_if_bank: float          # expected turn score if you bank after this keep
    ev_if_roll: float          # expected turn score if you roll on after this keep
    turn_total_after: int      # banked points this turn after taking this keep

    @property
    def ev(self) -> float:
        return max(self.ev_if_bank, self.ev_if_roll)


class Advisor:
    """Optimal-play calculator for a fixed rule set.

    ``hot_dice`` toggles the household rule.  ``turn_cap`` bounds the recursion:
    once the turn total is this high the advisor assumes you simply bank (a very
    large turn is never worth risking), which keeps the hot-dice recursion
    finite.  It is high enough that it never affects realistic decisions.
    """

    def __init__(
        self,
        rules: ScoreRules = DEFAULT_RULES,
        hot_dice: bool = True,
        turn_cap: int = 10000,
    ) -> None:
        self.rules = rules
        self.hot_dice = hot_dice
        self.turn_cap = turn_cap
        # Memo keyed on (dice_to_roll, turn_total) -> expected final turn score.
        self._ev_cache: Dict[Tuple[int, int], float] = {}

    # -- public API ---------------------------------------------------------

    def ev_of_rolling(self, dice_to_roll: int, turn_total: int) -> float:
        """Expected final turn score if you *roll* ``dice_to_roll`` dice now
        with ``turn_total`` already banked this turn (playing optimally after).
        """
        if dice_to_roll == 0:  # hot dice: pick all six back up
            dice_to_roll = 6
        turn_total = min(turn_total, self.turn_cap)
        return self._ev_roll(dice_to_roll, turn_total)

    def recommend(self, dice, turn_total: int) -> Optional[Decision]:
        """Best action for the given roll.  Returns ``None`` on a Farkle
        (no scoring dice — the turn is over and ``turn_total`` is lost)."""
        counts = counts_from_dice(dice)
        keeps = legal_keeps(counts, self.rules)
        if not keeps:
            return None

        best: Optional[Decision] = None
        for keep in keeps:
            new_total = turn_total + keep.score
            remaining = keep.remaining
            if remaining == 0:
                remaining = 6 if self.hot_dice else 0

            ev_bank = float(new_total)
            if remaining == 0:
                # No hot-dice rule and no dice left: you must bank.
                ev_roll = float("-inf")
            else:
                ev_roll = self.ev_of_rolling(remaining, new_total)

            decision = Decision(
                keep=keep,
                roll_again=ev_roll > ev_bank,
                ev_if_bank=ev_bank,
                ev_if_roll=ev_roll if ev_roll != float("-inf") else ev_bank,
                turn_total_after=new_total,
            )
            if best is None or decision.ev > best.ev:
                best = decision
        return best

    def all_options(self, dice, turn_total: int) -> List[Decision]:
        """Every legal keep scored by EV, best first — useful for showing the
        player *why* the top pick wins."""
        counts = counts_from_dice(dice)
        options: List[Decision] = []
        for keep in legal_keeps(counts, self.rules):
            new_total = turn_total + keep.score
            remaining = keep.remaining
            if remaining == 0:
                remaining = 6 if self.hot_dice else 0
            ev_bank = float(new_total)
            ev_roll = (
                self.ev_of_rolling(remaining, new_total)
                if remaining != 0
                else float("-inf")
            )
            options.append(
                Decision(
                    keep=keep,
                    roll_again=ev_roll > ev_bank,
                    ev_if_bank=ev_bank,
                    ev_if_roll=ev_roll if ev_roll != float("-inf") else ev_bank,
                    turn_total_after=new_total,
                )
            )
        return sorted(options, key=lambda d: d.ev, reverse=True)

    # -- internals ----------------------------------------------------------

    def _ev_roll(self, n: int, turn_total: int) -> float:
        key = (n, turn_total)
        cached = self._ev_cache.get(key)
        if cached is not None:
            return cached

        # Guard against unbounded hot-dice recursion.  Above the cap we assume
        # the player banks, so rolling's value collapses to the current total.
        if turn_total >= self.turn_cap:
            self._ev_cache[key] = float(turn_total)
            return float(turn_total)

        total_ways = 6 ** n
        expected = 0.0
        for counts, mult in _outcomes(n):
            prob = mult / total_ways
            expected += prob * self._best_value_for_roll(counts, turn_total)

        self._ev_cache[key] = expected
        return expected

    def _best_value_for_roll(self, counts: Counts, turn_total: int) -> float:
        keeps = legal_keeps(counts, self.rules)
        if not keeps:
            return 0.0  # Farkle: lose the whole turn total.

        best = 0.0
        for keep in keeps:
            new_total = turn_total + keep.score
            remaining = keep.remaining
            if remaining == 0:
                remaining = 6 if self.hot_dice else 0

            value = float(new_total)  # option: bank now
            if remaining != 0:
                value = max(value, self._ev_roll(remaining, new_total))
            if value > best:
                best = value
        return best
