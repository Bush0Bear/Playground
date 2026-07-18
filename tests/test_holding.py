"""Tests for the 'hold' house rule: setting aside non-scoring dice to build
toward a combo on a later roll."""

import random

import pytest

from farkle.advisor import Advisor
from farkle.game import Turn
from farkle.scoring import counts_from_dice, max_extract, score_dice


class TestMaxExtract:
    def test_empty(self):
        assert max_extract(counts_from_dice([])) == 0

    def test_two_sixes_score_nothing(self):
        assert max_extract(counts_from_dice([6, 6])) == 0

    def test_three_sixes(self):
        assert max_extract(counts_from_dice([6, 6, 6, 2, 3])) == 600

    def test_partial_use(self):
        # Uses only the scoring dice, unlike score_dice which needs all used.
        assert max_extract(counts_from_dice([5, 5, 2, 3, 4])) == 100
        assert score_dice([5, 5, 2, 3, 4]) is None

    def test_ones_prefer_triple(self):
        assert max_extract(counts_from_dice([1, 1, 1, 1])) == 1100


class TestTurnHolding:
    def test_hold_then_complete_triple(self):
        turn = Turn(hot_dice=True, rng=random.Random(0))
        turn.state.current_roll = [5, 6, 6, 2, 3, 4]
        turn.keep([5], hold=[6, 6])
        assert turn.state.turn_total == 50
        assert turn.state.held == [6, 6]
        assert turn.state.locked_count == 1
        assert turn.state.dice_in_hand == 3    # 6 - 1 locked - 2 held

        # Next roll completes the triple.
        turn.state.current_roll = [6, 2, 3]
        assert turn.legal_keeps()              # not a farkle
        turn.keep([6, 6, 6])
        assert turn.state.turn_total == 650    # 50 + 600
        assert turn.state.held == []
        assert turn.state.locked_count == 4

    def test_farkle_while_holding(self):
        turn = Turn(rng=random.Random(1))
        turn.state.locked_count = 1
        turn.state.held = [6, 6]
        turn.state.turn_total = 50
        # Roll adds no new score (no 1/5, no third 6, no triple).
        turn.state.current_roll = [2, 3, 4]
        # Manually run the roll's Farkle check via the engine helper.
        pool = counts_from_dice(turn.state.pool)
        held = counts_from_dice(turn.state.held)
        assert max_extract(pool) <= max_extract(held)   # -> Farkle

    def test_holding_a_five_and_rolling_junk_is_farkle(self):
        # A held (unscored) 5 does not save you: the new dice must add score.
        held = counts_from_dice([5])
        pool = counts_from_dice([5, 2, 3, 4])
        assert max_extract(pool) <= max_extract(held)

    def test_hold_only_move_is_allowed(self):
        # You may hold non-scoring dice and reroll without banking this roll,
        # as long as the roll was valid (a 1 is present here).
        turn = Turn(rng=random.Random(2))
        turn.state.current_roll = [1, 6, 6, 2, 3, 4]
        turn.keep([], hold=[6, 6])             # lock nothing, hold two 6s
        assert turn.state.turn_total == 0       # nothing banked
        assert turn.state.held == [6, 6]
        assert turn.state.locked_count == 0
        assert turn.state.dice_in_hand == 4     # rerolling the other four

    def test_must_set_aside_something(self):
        turn = Turn(rng=random.Random(2))
        turn.state.current_roll = [1, 6, 6, 2, 3, 4]
        with pytest.raises(ValueError):
            turn.keep([], hold=[])             # setting aside nothing is illegal


class TestHoldAdvisor:
    def test_hold_beats_no_hold_ev(self):
        # With holding available, the optimal per-turn EV strictly improves.
        no_hold = Advisor(allow_hold=False).ev_of_rolling(6, 0)
        with_hold = Advisor(allow_hold=True, max_held=2).ev_of_rolling(6, 0)
        assert with_hold > no_hold

    def test_recommends_holding_a_pair_toward_a_triple(self):
        adv = Advisor(allow_hold=True, max_held=2)
        # Fresh roll with a lone 5 and a pair of 6s: holding the 6s wins.
        d = adv.recommend([5, 6, 6, 2, 3, 4], 0)
        assert d is not None
        assert d.keep.dice == (5,)
        assert tuple(sorted(d.hold)) == (6, 6)
        assert d.roll_again

    def test_completing_triple_is_scored(self):
        adv = Advisor(allow_hold=True, max_held=2)
        # Holding two 6s, rolled a completing 6 (plus a 1): best locks them all.
        d = adv.recommend([6, 1, 2], 50, held=[6, 6])
        assert d is not None
        assert 6 in d.keep.dice and d.keep.dice.count(6) == 3

    def test_farkle_returns_none_even_with_holding(self):
        adv = Advisor(allow_hold=True, max_held=2)
        # Holding two 6s, rolled junk -> no new score -> Farkle.
        assert adv.recommend([2, 3, 4], 50, held=[6, 6]) is None

    def test_ev_matches_simulation(self):
        # The computed EV must match Monte-Carlo play of the same policy.
        adv = Advisor(allow_hold=True, max_held=2)
        computed = adv.ev_of_rolling(6, 0)
        rng = random.Random(999)
        n, tot = 8000, 0
        for _ in range(n):
            tot += _play_turn(adv, rng)
        simulated = tot / n
        assert abs(simulated - computed) < 25   # within Monte-Carlo noise


def _play_turn(adv, rng):
    turn = Turn(hot_dice=True, rng=rng)
    while not turn.state.over:
        turn.roll()
        if turn.state.farkled:
            return 0
        d = adv.recommend(turn.state.current_roll, turn.state.turn_total,
                          held=turn.state.held)
        if d is None:
            return 0
        turn.keep(list(d.keep.dice), hold=list(d.hold))
        if turn.state.over:
            break
        if not d.roll_again:
            return turn.bank()
    return turn.state.turn_total
