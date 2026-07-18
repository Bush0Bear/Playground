# Playground — Farkle Simulator + Optimal-Play Advisor

> Part of the Playground repo (space for learning).

A Farkle simulator you can play through by hand, with an **expected-value
advisor** that tells you the *best possible action* on any given roll — which
dice to set aside, and whether to bank your points or push your luck and roll
again.

It also implements the **house "hot dice" rule** we play in my family: whenever
all six dice have scored, you pick them **all** back up and keep the same streak
going, rolling the accumulated total forward.

```
$ python -m farkle advise 1 2 3 4 5 6

Roll: [1] [2] [3] [4] [5] [6]   (turn total so far: 0)
  keep                     this   turn   bank EV   roll EV  advice
  ----------------------------------------------------------------------
  [1] [2] [3] [4] [5] [6]   1500   1500      1500      1955  ROLL ON
  [1]                       100    100       100       404  ROLL ON
  [5]                        50     50        50       369  ROLL ON
  [1] [5]                   150    150       150       311  ROLL ON

  ==> Best play: keep [1] [2] [3] [4] [5] [6] (+1500), then ROLL AGAIN.
      Expected final turn score with optimal play: 1955
```

> Even a 1500 straight is worth rolling on here — because of the hot-dice rule,
> setting all six aside earns 1500 *and* hands you six fresh dice, so the
> expected final score of the turn (1955) beats banking (1500).

## Install

No third-party dependencies for the core. From the repo root:

```bash
python -m farkle --help            # run straight from source, or
pip install -e .                   # install the `farkle` command
pip install -e '.[test]'           # ...with pytest for the test suite
```

## Usage

### Play through hands

```bash
python -m farkle play                 # play to 10000, hot dice on
python -m farkle play --seed 42       # reproducible dice
python -m farkle --no-hot-dice play   # standard rules, no streak
```

On every roll you see the full option table and the advisor's pick. At the
prompt, type the face values to keep (e.g. `1 5`), or just press Enter / type
`best` to take the optimal move, or `q` to quit.

### Analyse a single roll

```bash
python -m farkle advise 1 1 3 4 5 6
python -m farkle advise 5 2 3 4 6 2 --turn-total 2000   # with points at risk
```

The `--turn-total` matters: the more you have banked this turn, the more a
Farkle costs you, so the advisor gets more conservative about rolling on.

### Simulate / compare strategies

```bash
python -m farkle sim                       # per-turn value of each strategy
python -m farkle sim --tournament          # head-to-head win rates
python -m farkle --no-hot-dice sim         # measure the rule's impact
```

Typical output (hot dice on):

```
  strategy            mean   stdev  farkle%    best
  --------------------------------------------------
  optimal            600.0   618.5   21.6%    5750
  greedy             429.1   457.1    2.0%    3000
  bank_at_300        496.9   452.4   20.0%    2500
  ...
Farkle probability by dice remaining:
  1 dice: 66.7%   2 dice: 44.4%   3 dice: 27.8%
  4 dice: 15.7%   5 dice:  7.7%   6 dice:  2.3%
```

## How the advisor works

The advisor solves the turn as a small Markov decision process. Let
`V(n, T)` be the expected final score of a turn where you are about to roll `n`
dice with `T` points banked so far. For each possible roll it considers every
legal way to set dice aside, and for each of those the choice to **bank** (`T`
becomes final) or **roll on** (recurse into `V`), always taking the option with
the highest expected value:

```
V(n, T) = Σ  P(roll) · max over legal keeps of
                 max( T + keep,                 # bank now
                      V(dice_left, T + keep) )  # roll on
```

A Farkle (no scoring dice) contributes `0` — you lose everything banked that
turn. Hot dice are modelled by resetting `dice_left` to 6 whenever a keep uses
the last die. The recursion is memoised on `(n, T)` and terminates because a
large enough turn total is never worth risking (banking dominates), which also
keeps the hot-dice streak finite.

This is why the advisor sometimes recommends keeping **fewer** dice than the
maximum-scoring selection: holding back dice with re-roll potential can be worth
more than a few extra points banked now.

## Scoring rules

Farkle scoring differs between households, so every value lives in a
configurable [`ScoreRules`](farkle/scoring.py) object. The defaults match the
common commercially published set:

| Combination            | Points                                   |
| ---------------------- | ---------------------------------------- |
| Each `1`               | 100                                      |
| Each `5`               | 50                                       |
| Three `1`s             | 1000                                     |
| Three of a kind (2–6)  | face × 100 (e.g. three `4`s = 400)       |
| Four of a kind         | 1000                                     |
| Five of a kind         | 2000                                     |
| Six of a kind          | 3000                                     |
| Straight `1-2-3-4-5-6` | 1500                                     |
| Three pairs            | 1500                                     |
| Two triplets           | 2500                                     |
| Four of a kind + pair  | 1500                                     |

The scorer always chooses the **highest-value legal partition** of the dice you
keep (for instance four `1`s score as three-of-a-kind + a loose `1` = 1100,
rather than a flat four-of-a-kind 1000). To use your family's exact numbers,
construct a custom `ScoreRules` and pass it to `Advisor`, `Turn`, and the
scoring functions.

### Hot dice

When every one of the six dice has been set aside as part of a scoring
combination, you get **hot dice**: pick all six back up and keep rolling with
your turn total carried forward. A Farkle at any point still wipes the turn.
Turn it off with `--no-hot-dice` (or `hot_dice=False` in the API) to play the
standard game.

## Library API

```python
from farkle import Advisor, Turn, score_dice, legal_keeps, counts_from_dice

score_dice([1, 1, 1, 5])          # -> 1050

advisor = Advisor(hot_dice=True)
d = advisor.recommend([1, 5, 2, 3, 4, 6], turn_total=0)
d.keep.dice        # dice to set aside
d.roll_again       # True = roll on, False = bank
d.ev               # expected final turn score under optimal play

# Drive a full turn with your own decisions:
turn = Turn(hot_dice=True)
turn.roll()
turn.keep([1, 5])
turn.bank()
```

See [`farkle/strategies.py`](farkle/strategies.py) for ready-made strategies
(`optimal`, `greedy_max_points`, `bank_at(n)`) usable with the simulator.

## Project layout

```
farkle/
  scoring.py      scoring rules + max-partition scorer + legal-keep enumeration
  advisor.py      expected-value optimal-play engine
  game.py         turn/game state, hot-dice rule, referee
  strategies.py   plug-in strategies for the simulator
  simulate.py     Monte-Carlo per-turn stats and tournaments
  cli.py          the `play` / `advise` / `sim` command line
tests/            pytest suite for scoring and the advisor
```

## Tests

```bash
python -m pytest
```
