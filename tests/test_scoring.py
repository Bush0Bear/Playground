import pytest

from farkle.scoring import (
    DEFAULT_RULES,
    counts_from_dice,
    legal_keeps,
    score_dice,
    score_selection,
)


def s(dice):
    return score_dice(dice)


class TestSingles:
    def test_single_one(self):
        assert s([1]) == 100

    def test_single_five(self):
        assert s([5]) == 50

    def test_two_ones_two_fives(self):
        assert s([1, 1, 5, 5]) == 300

    def test_non_scoring_single_is_illegal(self):
        # A lone 2 cannot be kept.
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


class TestBestPartition:
    def test_four_ones_prefer_triple_plus_single(self):
        # three 1s (1000) + single 1 (100) = 1100 beats four-of-a-kind (1000)
        assert s([1, 1, 1, 1]) == 1100

    def test_four_sixes_must_use_four_of_a_kind(self):
        # a leftover 6 cannot score, so four-of-a-kind (1000) is the only legal
        # full-use partition
        assert s([6, 6, 6, 6]) == 1000

    def test_five_ones(self):
        # five-of-a-kind (2000) + nothing, vs 2000 partitions; 2000 wins... but
        # 2000 + 0. Actually take5=2000; take3(1000)+2 singles(200)=1200. -> 2000
        assert s([1, 1, 1, 1, 1]) == 2000

    def test_six_fives(self):
        assert s([5, 5, 5, 5, 5, 5]) == 3000


class TestSixDiceCombos:
    def test_straight(self):
        assert s([1, 2, 3, 4, 5, 6]) == 1500

    def test_three_pairs(self):
        assert s([2, 2, 3, 3, 4, 4]) == 1500

    def test_two_triplets(self):
        # 2500 beats 300+400=700
        assert s([3, 3, 3, 4, 4, 4]) == 2500

    def test_three_pairs_with_scoring_faces_prefers_higher(self):
        # 1s and 5s pairs: three pairs = 1500 vs 1+1+5+5 scoring = 300; but
        # 1,1,1 triple? no. [1,1,5,5,2,2] -> three pairs 1500
        assert s([1, 1, 5, 5, 2, 2]) == 1500

    def test_four_plus_pair(self):
        # four 2s + pair of 3s: four_plus_pair=1500 vs four-of-a-kind(1000)+? 3,3 unused
        assert s([2, 2, 2, 2, 3, 3]) == 1500


class TestLegalKeeps:
    def test_keeps_enumerated(self):
        keeps = legal_keeps(counts_from_dice([1, 5, 2, 3, 4, 6]))
        # It's a straight, so one keep is all six for 1500; also single 1, single
        # 5, and 1+5.
        scores = {k.dice: k.score for k in keeps}
        assert (1, 2, 3, 4, 5, 6) in scores
        assert scores[(1, 2, 3, 4, 5, 6)] == 1500
        assert (1,) in scores and scores[(1,)] == 100
        assert (5,) in scores and scores[(5,)] == 50

    def test_farkle_has_no_keeps(self):
        assert legal_keeps(counts_from_dice([2, 3, 4, 6, 6, 2])) == []

    def test_keep_remaining_count(self):
        keeps = legal_keeps(counts_from_dice([1, 1, 2, 3, 4, 6]))
        by_dice = {k.dice: k for k in keeps}
        assert by_dice[(1,)].remaining == 5
        assert by_dice[(1, 1)].remaining == 4
