import random

import pytest

from farkle.advisor import Advisor, farkle_probability
from farkle.game import play_turn, Turn
from farkle import strategies


class TestFarkleProbability:
    def test_single_die(self):
        # A single die farkles unless it shows 1 or 5 -> 4/6
        assert farkle_probability(1) == pytest.approx(4 / 6)

    def test_two_dice(self):
        # Known value: P(farkle with 2 dice) with standard rules.
        p = farkle_probability(2)
        assert 0.4 < p < 0.5

    def test_monotonic_ish(self):
        # More dice -> generally less likely to farkle.
        p6 = farkle_probability(6)
        p1 = farkle_probability(1)
        assert p6 < p1


class TestRecommend:
    def setup_method(self):
        self.advisor = Advisor(hot_dice=True)

    def test_farkle_returns_none(self):
        assert self.advisor.recommend([2, 3, 4, 6, 6, 2], 0) is None

    def test_recommends_a_legal_keep(self):
        d = self.advisor.recommend([1, 5, 2, 3, 4, 6], 0)
        assert d is not None
        # keeping should be legal and score positive
        assert d.keep.score > 0

    def test_high_turn_total_prefers_banking_on_risky_roll(self):
        # With a big turn total and only one scoring die (a 5), risking a single
        # reroll is bad -> should bank.
        d = self.advisor.recommend([5, 2, 3, 4, 6, 2], 5000)
        assert d is not None
        assert d.roll_again is False

    def test_fresh_start_with_good_roll_rolls_on(self):
        # Six dice, small keep available, nothing banked -> rolling on is +EV.
        d = self.advisor.recommend([1, 2, 3, 4, 6, 2], 0)
        assert d is not None
        assert d.roll_again is True

    def test_ev_beats_or_matches_greedy_expectation(self):
        # The optimal single-turn EV from a fresh 6 dice should exceed the mean
        # a greedy "take max, bank now" player achieves.
        ev = self.advisor.ev_of_rolling(6, 0)
        assert ev > 300  # comfortably above greedy's ~ low-hundreds mean


class TestHotDiceEffect:
    def test_hot_dice_raises_ev(self):
        with_hot = Advisor(hot_dice=True).ev_of_rolling(6, 0)
        without = Advisor(hot_dice=False).ev_of_rolling(6, 0)
        assert with_hot > without


class TestPlayTurnIntegration:
    def test_optimal_strategy_runs(self):
        rng = random.Random(1234)
        strat = strategies.optimal(hot_dice=True)
        scores = [play_turn(strat, rng=rng) for _ in range(50)]
        assert all(s >= 0 for s in scores)
        assert any(s > 0 for s in scores)

    def test_turn_hot_dice_reset(self):
        # Force a keep that uses all six dice and confirm the hand resets to 6.
        # (A straight is not a scoring keep under the basic rules, so use two
        # triples of 1s and 5s, which score 1000 + 500 = 1500.)
        turn = Turn(hot_dice=True, rng=random.Random(0))
        turn.state.current_roll = [1, 1, 1, 5, 5, 5]
        turn.keep([1, 1, 1, 5, 5, 5])
        assert turn.state.dice_in_hand == 6
        assert turn.state.turn_total == 1500
        assert not turn.state.over


class TestPracticeBot:
    def test_bot_makes_legal_moves(self):
        rng = random.Random(99)
        scores = [play_turn(strategies.practice_bot, rng=rng) for _ in range(100)]
        assert all(s >= 0 for s in scores)
        assert any(s > 0 for s in scores)

    def test_bot_banks_modest_totals(self):
        # Rusty is conservative: with a decent total and few dice he stops.
        from farkle.scoring import counts_from_dice, legal_keeps
        from farkle.game import TurnState
        state = TurnState(locked_count=4, turn_total=300)
        keeps = legal_keeps(counts_from_dice([5, 5]))
        _, roll_again = strategies.practice_bot(state, keeps)
        assert roll_again is False
