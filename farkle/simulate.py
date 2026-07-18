"""Monte Carlo tools to measure and compare strategies."""

from __future__ import annotations

import random
import statistics
from dataclasses import dataclass
from typing import Callable, Dict, List

from .game import Player, Strategy, play_game, play_turn
from .scoring import ScoreRules, DEFAULT_RULES


@dataclass
class TurnStats:
    strategy: str
    trials: int
    mean: float
    stdev: float
    farkle_rate: float
    best: int


def evaluate_strategy(
    strategy: Strategy,
    trials: int = 20000,
    rules: ScoreRules = DEFAULT_RULES,
    hot_dice: bool = True,
    seed: int = 0,
) -> TurnStats:
    """Estimate the per-turn scoring distribution of a strategy."""
    rng = random.Random(seed)
    scores: List[int] = []
    farkles = 0
    for _ in range(trials):
        s = play_turn(strategy, rules, hot_dice, rng)
        scores.append(s)
        if s == 0:
            farkles += 1
    name = getattr(strategy, "__name__", "strategy")
    return TurnStats(
        strategy=name,
        trials=trials,
        mean=statistics.fmean(scores),
        stdev=statistics.pstdev(scores),
        farkle_rate=farkles / trials,
        best=max(scores),
    )


def tournament(
    strategies: Dict[str, Strategy],
    games: int = 2000,
    target: int = 10000,
    rules: ScoreRules = DEFAULT_RULES,
    hot_dice: bool = True,
    seed: int = 0,
) -> Dict[str, int]:
    """Round-robin-ish: every strategy plays in each game; count wins."""
    rng = random.Random(seed)
    wins: Dict[str, int] = {name: 0 for name in strategies}
    for _ in range(games):
        players = [Player(name=n, strategy=s) for n, s in strategies.items()]
        rng.shuffle(players)
        winner = play_game(players, target, rules, hot_dice, rng)
        wins[winner.name] += 1
    return wins
