"""A few ready-made strategies for the simulator.

Each is a :data:`~farkle.game.Strategy`: it receives the turn state and the
legal keeps for the current roll, and returns ``(dice_to_keep, roll_again)``.
"""

from __future__ import annotations

from typing import List, Tuple

from .advisor import Advisor
from .game import TurnState
from .scoring import Keep, ScoreRules, DEFAULT_RULES


def greedy_max_points(state: TurnState, keeps: List[Keep]) -> Tuple[List[int], bool]:
    """Always take the highest-scoring keep, then bank immediately."""
    best = max(keeps, key=lambda k: k.score)
    return list(best.dice), False


def bank_at(threshold: int):
    """Take the max-scoring keep each roll; keep rolling until the turn total
    reaches ``threshold``, then bank.  A classic simple heuristic."""

    def strategy(state: TurnState, keeps: List[Keep]) -> Tuple[List[int], bool]:
        best = max(keeps, key=lambda k: k.score)
        would_be = state.turn_total + best.score
        roll_again = would_be < threshold
        return list(best.dice), roll_again

    strategy.__name__ = f"bank_at_{threshold}"
    return strategy


def optimal(
    rules: ScoreRules = DEFAULT_RULES, hot_dice: bool = True
):
    """Expected-value optimal play, driven by :class:`~farkle.advisor.Advisor`."""
    advisor = Advisor(rules=rules, hot_dice=hot_dice)

    def strategy(state: TurnState, keeps: List[Keep]) -> Tuple[List[int], bool]:
        decision = advisor.recommend(state.current_roll, state.turn_total)
        assert decision is not None  # keeps is non-empty here
        return list(decision.keep.dice), decision.roll_again

    strategy.__name__ = "optimal"
    return strategy
