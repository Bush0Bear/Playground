"""Farkle game state: turns, dice, the hot-dice rule, and the hold rule.

This module is the rules-faithful "referee".  It knows how a turn progresses
but takes no strategic decisions itself — those come from a human (via the CLI)
or from a strategy function (via the simulator).

Two household rules are supported:

* **hot dice** — when all six dice have scored, pick them all back up and keep
  the streak going with the turn total carried forward.
* **holding** — you may set aside *non-scoring* dice ("held" dice) to build
  toward a combo on a later roll (e.g. hold two 6s hoping to roll a third).
  Held dice keep their faces and combine with what you roll next.  A roll is a
  Farkle unless it produces at least one *new* score — a freshly rolled 1/5 or
  the completion of a held combo.
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
    max_extract,
    score_selection,
)


def roll_dice(n: int, rng: random.Random) -> List[int]:
    return [rng.randint(1, 6) for _ in range(n)]


@dataclass
class TurnState:
    """Live state of a single turn."""

    locked_count: int = 0          # dice already scored & set aside this turn
    held: List[int] = field(default_factory=list)   # non-scored dice being held
    turn_total: int = 0            # points banked this turn (lost on a Farkle)
    current_roll: List[int] = field(default_factory=list)  # dice just rolled
    over: bool = False             # turn ended (banked or farkled)
    farkled: bool = False
    banked: bool = False
    last_hot_dice: bool = False    # did the most recent keep trigger hot dice?
    history: List[str] = field(default_factory=list)

    @property
    def dice_in_hand(self) -> int:
        """How many dice will be rolled next (the un-locked, un-held dice)."""
        return 6 - self.locked_count - len(self.held)

    @property
    def pool(self) -> List[int]:
        """Everything on the table this roll: held dice plus the current roll."""
        return sorted(self.held + self.current_roll)


class Turn:
    """Drives one turn of Farkle, enforcing hot dice and the hold rule."""

    def __init__(
        self,
        rules: ScoreRules = DEFAULT_RULES,
        hot_dice: bool = True,
        rng: Optional[random.Random] = None,
    ) -> None:
        self.rules = rules
        self.hot_dice = hot_dice
        self.rng = rng or random.Random()
        self.state = TurnState()

    def roll(self) -> List[int]:
        """Roll the dice in hand.  Farkles unless the roll adds a *new* score
        (over and above whatever the held dice already offered)."""
        if self.state.over:
            raise RuntimeError("turn is already over")
        dice = roll_dice(self.state.dice_in_hand, self.rng)
        self.state.current_roll = dice
        pool = counts_from_dice(self.state.pool)
        held_counts = counts_from_dice(self.state.held)
        if max_extract(pool, self.rules) <= max_extract(held_counts, self.rules):
            self.state.farkled = True
            self.state.over = True
            self.state.turn_total = 0
            held_note = (f" (was holding {sorted(self.state.held)})"
                         if self.state.held else "")
            self.state.history.append(
                f"rolled {sorted(dice)}{held_note} -> FARKLE, lost turn"
            )
        else:
            held_note = (f" + holding {sorted(self.state.held)}"
                         if self.state.held else "")
            self.state.history.append(f"rolled {sorted(dice)}{held_note}")
        return dice

    def legal_keeps(self) -> List[Keep]:
        """Scoring keeps available from the current pool (held + rolled)."""
        return legal_keeps(counts_from_dice(self.state.pool), self.rules)

    def keep(self, lock, hold=()) -> int:
        """Set aside dice from the current pool (held + rolled): ``lock`` scores
        and is banked, ``hold`` is carried forward unscored.  ``lock`` may be
        empty — you may hold non-scoring dice and reroll the rest without banking
        this roll, as long as the roll itself was valid (see :meth:`roll`).
        Returns the points scored by ``lock``.  Applies hot dice at six locked.
        """
        if self.state.over:
            raise RuntimeError("turn is already over")
        lock = list(lock)
        hold = list(hold)
        self._validate_keep(lock, hold)
        score = score_selection(counts_from_dice(lock), self.rules) if lock else 0
        assert score is not None  # validated above

        self.state.turn_total += score
        self.state.locked_count += len(lock)
        self.state.held = hold
        self.state.current_roll = []

        hold_note = f", holding {sorted(hold)}" if hold else ""
        self.state.last_hot_dice = False
        if self.state.locked_count == 6:
            if self.hot_dice:
                self.state.locked_count = 0
                self.state.held = []
                self.state.last_hot_dice = True
                self.state.history.append(
                    f"locked {sorted(lock)} (+{score}) -> HOT DICE, pick up all 6"
                )
            else:
                self.state.history.append(
                    f"locked {sorted(lock)} (+{score}) -> all dice used"
                )
        else:
            self.state.history.append(
                f"locked {sorted(lock)} (+{score}){hold_note}"
            )
        return score

    def bank(self) -> int:
        """End the turn and keep ``turn_total``.  Held dice score nothing."""
        if self.state.over:
            raise RuntimeError("turn is already over")
        self.state.banked = True
        self.state.over = True
        self.state.history.append(f"BANKED {self.state.turn_total}")
        return self.state.turn_total

    # -- helpers ------------------------------------------------------------

    def _validate_keep(self, lock, hold) -> None:
        if not lock and not hold:
            raise ValueError("must set aside at least one die (lock or hold)")
        pool = list(self.state.pool)
        for face in list(lock) + list(hold):
            if face in pool:
                pool.remove(face)
            else:
                raise ValueError(
                    f"die {face} is not available in the pool "
                    f"{sorted(self.state.pool)}"
                )
        if lock and score_selection(counts_from_dice(lock), self.rules) is None:
            raise ValueError(f"{sorted(lock)} is not a fully-scoring selection")


# --- full game -------------------------------------------------------------

Strategy = Callable[[TurnState, List[Keep]], Tuple[List[int], bool]]
"""A strategy takes the current turn state and the legal keeps for the roll,
and returns ``(dice_to_lock, roll_again)``.  Simulator strategies do not hold
dice; the hold rule is exercised through the advisor and interactive play."""


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
    idx = 0
    start_of_final = 0
    while True:
        player = players[idx % len(players)]
        player.score += play_turn(player.strategy, rules, hot_dice, rng)
        if not final_round and player.score >= target:
            final_round = True
            start_of_final = idx
        if final_round and idx - start_of_final >= len(players) - 1:
            return max(players, key=lambda p: p.score)
        idx += 1
