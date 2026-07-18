import pytest

from farkle.scoring import (
    BASIC_RULES,
    DEFAULT_RULES,
    STANDARD_RULES,
    counts_from_dice,
    legal_keeps,
    score_dice,
    score_selection,
)


def s(dice):
    """Score under the default (basic) rules."""
    return score_dice(dice)


def std(dice):
    return score_dice(dice, STANDARD_RULES)


class TestDefaultIsBasic:
    def test_default_rules_are_basic(self):
        assert DEFAULT_RULES is BASIC_RULES


class TestSingles:
    def test_single_one(self):
        assert s([1]) == 100

    def test_single_five(self):
        assert s([5]) == 50

    def test_two_ones_two_fives(self):
        assert s([1, 1, 5, 5]) == 300

    def test_non_scoring_single_is_illegal(self):
        assert s([2]) is None
        assert s([1, 2]) is None  # the 2 has no home


class TestThreeOfAKind:
    def test_three_ones(self):
        assert s([1, 1, 1]) == 1000

    def test_three_fives(self):
        assert s([5, 5, 5]) == 500

    def test_three_twos(self):
        assert s([2, 2, 2]) == 200

    def test_three_sixes(self):
        assert s([6, 6, 6]) == 600

    def test_six_ones_are_two_triples_in_basic(self):
        # No six-of-a-kind bonus in the basic model: 1000 + 1000.
        assert s([1, 1, 1, 1, 1, 1]) == 2000


class TestBasicPartition:
    def test_four_ones_prefer_triple_plus_single(self):
        # three 1s (1000) + a loose 1 (100) = 1100
        assert s([1, 1, 1, 1]) == 1100

    def test_four_sixes_cannot_all_be_kept_in_basic(self):
        # No four-of-a-kind combo: three 6s score, but the fourth 6 cannot, so
        # keeping all four is illegal.  (You would keep three and reroll one.)
        assert s([6, 6, 6, 6]) is None

    def test_five_ones_basic(self):
        # three 1s (1000) + two loose 1s (200) = 1200
        assert s([1, 1, 1, 1, 1]) == 1200

    def test_two_triples_score_separately_in_basic(self):
        # three 3s + three 4s = 300 + 400 (no two-triplet bonus)
        assert s([3, 3, 3, 4, 4, 4]) == 700

    def test_straight_is_not_scoring_in_basic(self):
        assert s([1, 2, 3, 4, 5, 6]) is None

    def test_three_pairs_is_not_scoring_in_basic(self):
        assert s([2, 2, 3, 3, 4, 4]) is None


class TestStandardRulesCombos:
    def test_four_sixes_four_of_a_kind(self):
        assert std([6, 6, 6, 6]) == 1000

    def test_five_ones(self):
        assert std([1, 1, 1, 1, 1]) == 2000

    def test_six_fives(self):
        assert std([5, 5, 5, 5, 5, 5]) == 3000

    def test_straight(self):
        assert std([1, 2, 3, 4, 5, 6]) == 1500

    def test_three_pairs(self):
        assert std([2, 2, 3, 3, 4, 4]) == 1500

    def test_two_triplets(self):
        assert std([3, 3, 3, 4, 4, 4]) == 2500

    def test_four_plus_pair(self):
        assert std([2, 2, 2, 2, 3, 3]) == 1500


class TestLegalKeeps:
    def test_keeps_enumerated_basic(self):
        # A "straight" roll under basic rules only yields 1s and 5s keeps.
        keeps = legal_keeps(counts_from_dice([1, 5, 2, 3, 4, 6]))
        scores = {k.dice: k.score for k in keeps}
        assert (1,) in scores and scores[(1,)] == 100
        assert (5,) in scores and scores[(5,)] == 50
        assert (1, 5) in scores and scores[(1, 5)] == 150
        assert (1, 2, 3, 4, 5, 6) not in scores  # no straight in basic

    def test_keeps_enumerated_standard(self):
        keeps = legal_keeps(counts_from_dice([1, 5, 2, 3, 4, 6]), STANDARD_RULES)
        scores = {k.dice: k.score for k in keeps}
        assert scores[(1, 2, 3, 4, 5, 6)] == 1500

    def test_farkle_has_no_keeps(self):
        assert legal_keeps(counts_from_dice([2, 3, 4, 6, 6, 2])) == []

    def test_keep_remaining_count(self):
        keeps = legal_keeps(counts_from_dice([1, 1, 2, 3, 4, 6]))
        by_dice = {k.dice: k for k in keeps}
        assert by_dice[(1,)].remaining == 5
        assert by_dice[(1, 1)].remaining == 4
