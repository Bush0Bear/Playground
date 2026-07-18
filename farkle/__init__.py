"""Farkle simulator + expected-value optimal-play advisor.

Public surface:

    from farkle import Advisor, ScoreRules, DEFAULT_RULES
    from farkle import Turn, play_turn, play_game
    from farkle import score_dice, legal_keeps, counts_from_dice

Supports the household "hot dice" rule: when all six dice have scored you may
pick them all back up and keep the streak going.
"""

from .scoring import (
    DEFAULT_RULES,
    Keep,
    ScoreRules,
    counts_from_dice,
    dice_from_counts,
    has_score,
    legal_keeps,
    score_dice,
    score_selection,
)
from .advisor import Advisor, Decision, farkle_probability
from .game import Turn, TurnState, Player, play_turn, play_game
from . import strategies

__version__ = "1.0.0"

__all__ = [
    "DEFAULT_RULES",
    "ScoreRules",
    "Keep",
    "counts_from_dice",
    "dice_from_counts",
    "has_score",
    "legal_keeps",
    "score_dice",
    "score_selection",
    "Advisor",
    "Decision",
    "farkle_probability",
    "Turn",
    "TurnState",
    "Player",
    "play_turn",
    "play_game",
    "strategies",
]
