"""Farkle game state: turns, dice, and the hot-dice household rule.

This module is the rules-faithful "referee".  It knows how a turn progresses
but takes no strategic decisions itself — those come from a human (via the CLI)
or from a strategy function (via the simulator).
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Tuple

from .scoring import (
    Counts,
    Keep,
    ScoreRules,
    DEFAULT_RULES,
    counts_from_dice,
    legal_keeps,
    score_selection,
)


def roll_dice(n: int, rng: random.Random) -> List[int]:
    return [rng.randint(1, 6) for _ in range(n)]


@dataclass
class TurnState:
    """Live state of a single turn."""

    dice_in_hand: int              # dice available to roll next
    turn_total: int = 0            # points banked this turn (lost on a Farkle)
    current_roll: List[int] = field(default_factory=list)
    over: bool = False             # turn ended (banked or farkled)
    farkled: bool = False
    banked: bool = False
    history: List[str] = field(default_factory=list)


class Turn:
    """Drives one turn of Farkle, enforcing the rules including hot dice."""

    def __init__(
        self,
        rules: ScoreRules = DEFAULT_RULES,
        hot_dice: bool = True,
        rng: Optional[random.Random] = None,
    ) -> None:
        self.rules = rules
        self.hot_dice = hot_dice
        self.rng = rng or random.Random()
        self.state = TurnState(dice_in_hand=6)

    def roll(self) -> List[int]:
        """Roll the dice currently in hand.  Sets ``farkled`` if nothing scores."""
        if self.state.over:
            raise RuntimeError("turn is already over")
        dice = roll_dice(self.state.dice_in_hand, self.rng)
        self.state.current_roll = dice
        counts = counts_from_dice(dice)
        if not legal_keeps(counts, self.rules):
            self.state.farkled = True
            self.state.over = True
            self.state.turn_total = 0
            self.state.history.append(
                f"rolled {sorted(dice)} -> FARKLE, lost turn"
            )
        else:
            self.state.history.append(f"rolled {sorted(dice)}")
        return dice

    def legal_keeps(self) -> List[Keep]:
        return legal_keeps(counts_from_dice(self.state.current_roll), self.rules)

    def keep(self, dice_to_keep) -> int:
        """Set aside ``dice_to_keep`` (a list of face values from the current
        roll).  Returns points earned.  Applies the hot-dice reset when all six
        dice have scored.
        """
        if self.state.over:
            raise RuntimeError("turn is already over")
        self._validate_keep(dice_to_keep)
        score = score_selection(counts_from_dice(dice_to_keep), self.rules)
        assert score is not None  # validated above
        self.state.turn_total += score
        self.state.dice_in_hand -= len(list(dice_to_keep))

        if self.state.dice_in_hand == 0:
            if self.hot_dice:
                self.state.dice_in_hand = 6
                self.state.history.append(
                    f"kept {sorted(dice_to_keep)} (+{score}) -> HOT DICE, "
                    f"pick up all 6"
                )
            else:
                self.state.history.append(
                    f"kept {sorted(dice_to_keep)} (+{score}) -> all dice used"
                )
        else:
            self.state.history.append(
                f"kept {sorted(dice_to_keep)} (+{score})"
            )
        self.state.current_roll = []
        return score

    def bank(self) -> int:
        """End the turn and keep ``turn_total``."""
        if self.state.over:
            raise RuntimeError("turn is already over")
        self.state.banked = True
        self.state.over = True
        self.state.history.append(f"BANKED {self.state.turn_total}")
        return self.state.turn_total

    # -- helpers ------------------------------------------------------------

    def _validate_keep(self, dice_to_keep) -> None:
        kept = list(dice_to_keep)
        if not kept:
            raise ValueError("must keep at least one die")
        roll = list(self.state.current_roll)
        for face in kept:
            if face in roll:
                roll.remove(face)
            else:
                raise ValueError(
                    f"die {face} is not available in the current roll "
                    f"{sorted(self.state.current_roll)}"
                )
        if score_selection(counts_from_dice(kept), self.rules) is None:
            raise ValueError(
                f"{sorted(kept)} is not a fully-scoring selection"
            )


# --- full game -------------------------------------------------------------

Strategy = Callable[[TurnState, List[Keep]], Tuple[List[int], bool]]
"""A strategy takes the current turn state and the legal keeps for the roll,
and returns ``(dice_to_keep, roll_again)``."""


@dataclass
class Player:
    name: str
    strategy: Strategy
    score: int = 0


def play_turn(
    strategy: Strategy,
    rules: ScoreRules = DEFAULT_RULES,
    hot_dice: bool = True,
    rng: Optional[random.Random] = None,
) -> int:
    """Play one full turn with a strategy function; return points banked."""
    turn = Turn(rules=rules, hot_dice=hot_dice, rng=rng)
    while True:
        turn.roll()
        if turn.state.farkled:
            return 0
        keeps = turn.legal_keeps()
        dice_to_keep, roll_again = strategy(turn.state, keeps)
        turn.keep(dice_to_keep)
        if not roll_again:
            return turn.bank()


def play_game(
    players: List[Player],
    target: int = 10000,
    rules: ScoreRules = DEFAULT_RULES,
    hot_dice: bool = True,
    rng: Optional[random.Random] = None,
) -> Player:
    """Play a full game to ``target`` points; return the winning player.

    Uses the common "final round" rule: once someone reaches the target, every
    other player gets one more turn to try to beat them.
    """
    rng = rng or random.Random()
    final_round = False
    leader: Optional[Player] = None
    idx = 0
    while True:
        player = players[idx % len(players)]
        player.score += play_turn(player.strategy, rules, hot_dice, rng)
        if not final_round and player.score >= target:
            final_round = True
            leader = player
            start_of_final = idx
        if final_round and idx - start_of_final >= len(players) - 1:
            return max(players, key=lambda p: p.score)
        idx += 1
