"""Interactive Farkle CLI.

Modes:
  play      Play through turns yourself; the advisor shows the optimal move.
  vs        Play against Rusty, a friendly practice bot.
  advise    Analyse a single roll you type in and print the best action.
  sim       Monte-Carlo a strategy or run a strategy tournament.

Pass --hold to enable the "hold" house rule, where you may set aside
non-scoring dice to build toward a combo on a later roll.
"""

from __future__ import annotations

import argparse
import random
from typing import List, Optional, Tuple

from .advisor import Advisor, Decision, farkle_probability
from .game import Turn
from .scoring import DEFAULT_RULES, ScoreRules, counts_from_dice, legal_keeps
from . import strategies
from .simulate import evaluate_strategy, tournament


# --- pretty printing -------------------------------------------------------

def _fmt_dice(dice) -> str:
    return " ".join(f"[{d}]" for d in sorted(dice)) if dice else "—"


def _print_decision_table(decisions: List[Decision], hold: bool,
                          top: int = 8) -> None:
    if hold:
        print(f"  {'lock':<16}{'hold':<12}{'this':>6}{'turn':>7}"
              f"{'bank EV':>9}{'roll EV':>9}  advice")
        print("  " + "-" * 74)
        for d in decisions[:top]:
            advice = f"ROLL {d.reroll_count}" if d.roll_again else "BANK"
            print(
                f"  {_fmt_dice(d.keep.dice):<16}{_fmt_dice(d.hold):<12}"
                f"{d.keep.score:>6}{d.turn_total_after:>7}"
                f"{d.ev_if_bank:>9.0f}{d.ev_if_roll:>9.0f}  {advice}"
            )
    else:
        print(f"  {'keep':<22}{'this':>7}{'turn':>7}{'bank EV':>10}"
              f"{'roll EV':>10}  advice")
        print("  " + "-" * 70)
        for d in decisions[:top]:
            advice = "ROLL ON" if d.roll_again else "BANK"
            print(
                f"  {_fmt_dice(d.keep.dice):<22}{d.keep.score:>7}"
                f"{d.turn_total_after:>7}{d.ev_if_bank:>10.0f}"
                f"{d.ev_if_roll:>10.0f}  {advice}"
            )


def _report(advisor: Advisor, dice, turn_total: int,
            held=()) -> Optional[Decision]:
    hold_note = f"   holding: {_fmt_dice(held)}" if held else ""
    print(f"\nRoll: {_fmt_dice(dice)}   (turn total: {turn_total}){hold_note}")
    decisions = advisor.all_options(dice, turn_total, held)
    if not decisions:
        print("  >>> FARKLE! No new score. Turn over, you lose "
              f"{turn_total} points.")
        return None
    _print_decision_table(decisions, hold=advisor.allow_hold)
    best = decisions[0]
    action = f"ROLL the {best.reroll_count} remaining" if best.roll_again \
        else "BANK NOW"
    hold_txt = f", hold {_fmt_dice(best.hold)}" if best.hold else ""
    print(f"\n  ==> Best play: lock {_fmt_dice(best.keep.dice)} "
          f"(+{best.keep.score}){hold_txt}, then {action}.")
    print(f"      Expected final turn score with optimal play: {best.ev:.0f}")
    return best


# --- shared interactive turn -----------------------------------------------

def _prompt_move(turn: Turn, advisor: Advisor):
    """Ask the human for their move.  Returns ``(lock, hold)`` or ``None`` to
    quit.  Syntax: face values to lock, optionally ``hold`` then more faces,
    e.g. ``5 hold 6 6``.  ``best`` plays the advisor's pick."""
    prompt = ("  Your move ('5', or '5 hold 6 6', 'best', '?', 'q'): "
              if advisor.allow_hold
              else "  Your keep ('1 5', 'best', '?', 'q'): ")
    while True:
        raw = input(prompt).strip().lower()
        if raw in ("q", "quit", "exit"):
            return None
        if raw == "?":
            keeps = turn.legal_keeps()
            faces = sorted({f for k in keeps for f in k.dice})
            print(f"    Hint: dice that can score now: {_fmt_dice(faces)}. "
                  f"Best single lock is worth {keeps[0].score}.")
            continue
        if raw in ("", "best", "b"):
            d = advisor.recommend(turn.state.current_roll,
                                  turn.state.turn_total, held=turn.state.held)
            if d is None:
                return ([], [])
            return (list(d.keep.dice), list(d.hold))
        lock, hold = _parse_move(raw)
        if lock is None:
            print("  ! Enter faces to lock, optionally 'hold' more, or 'best'.")
            continue
        try:
            turn._validate_keep(lock, hold)
        except ValueError as e:
            print(f"  ! {e}")
            continue
        return (lock, hold)


def _parse_move(raw: str) -> Tuple[Optional[List[int]], List[int]]:
    parts = raw.replace(",", " ").split("hold")
    try:
        lock = [int(x) for x in parts[0].split()]
        hold = [int(x) for x in parts[1].split()] if len(parts) > 1 else []
    except ValueError:
        return None, []
    return lock, hold


def _ask_roll_again(turn: Turn) -> bool:
    while True:
        raw = input(f"  Roll the remaining {turn.state.dice_in_hand} dice? "
                    "([y]es / [n]o=bank): ").strip().lower()
        if raw in ("", "y", "yes"):
            return True
        if raw in ("n", "no", "bank"):
            return False
        print("  ! Please answer y or n.")


def _human_turn(advisor: Advisor, rules, hot_dice: bool, rng) -> Optional[int]:
    """Run one interactive turn for the human.  Returns points banked, or None
    if the player quit."""
    turn = Turn(rules=rules, hot_dice=hot_dice, rng=rng)
    while not turn.state.over:
        turn.roll()
        if turn.state.farkled:
            held = turn.state.history  # already logged
            print(f"\nRoll: {_fmt_dice(turn.state.current_roll)}")
            print("  >>> FARKLE! No new score. You lose this turn's points.")
            return 0
        _report(advisor, turn.state.current_roll, turn.state.turn_total,
                held=turn.state.held)
        move = _prompt_move(turn, advisor)
        if move is None:
            return None
        lock, hold = move
        turn.keep(lock, hold)
        if turn.state.last_hot_dice:
            print("  *** HOT DICE! All six scored — pick them all back up "
                  "and keep the streak going. ***")
        if turn.state.dice_in_hand == 0:
            print("  Nothing left to roll — banking automatically.")
            return turn.bank()
        if not _ask_roll_again(turn):
            return turn.bank()
    return turn.state.turn_total


# --- play mode -------------------------------------------------------------

def play(args) -> None:
    rules = DEFAULT_RULES
    hot_dice = not args.no_hot_dice
    rng = random.Random(args.seed) if args.seed is not None else random.Random()
    advisor = Advisor(rules=rules, hot_dice=hot_dice, allow_hold=args.hold)

    print("=" * 74)
    print("  FARKLE — interactive play")
    print(f"  Hot-dice: {'ON' if hot_dice else 'OFF'}   "
          f"Hold rule: {'ON' if args.hold else 'OFF'}   "
          f"(reach {args.target} to win)")
    print("=" * 74)

    total_score = 0
    while total_score < args.target:
        print(f"\n--- New turn (game score: {total_score}) ---")
        banked = _human_turn(advisor, rules, hot_dice, rng)
        if banked is None:
            print("\nThanks for playing!")
            return
        total_score += banked
        print(f"  Banked {banked}. Game score is now {total_score}.")

    print(f"\n*** You reached {total_score} and won! ***")


# --- versus-bot mode -------------------------------------------------------

def _bot_take_turn(name: str, rules, hot_dice: bool, rng) -> int:
    """Play one turn for the practice bot, narrating each decision so the human
    can learn to spot the scoring patterns.  (Rusty does not hold dice.)"""
    turn = Turn(rules=rules, hot_dice=hot_dice, rng=rng)
    print(f"\n  {name}'s turn:")
    while not turn.state.over:
        turn.roll()
        if turn.state.farkled:
            print(f"    rolls {_fmt_dice(turn.state.current_roll)} -> FARKLE! "
                  f"{name} scores 0 this turn.")
            return 0
        full_roll = list(turn.state.current_roll)
        keeps = turn.legal_keeps()
        dice_to_keep, roll_again = strategies.practice_bot(turn.state, keeps)
        score = score_of(dice_to_keep, rules)
        turn.keep(dice_to_keep)
        note = "  (HOT DICE!)" if turn.state.last_hot_dice else ""
        print(f"    rolls {_fmt_dice(full_roll)}"
              f" -> keeps {_fmt_dice(dice_to_keep)} (+{score}), "
              f"turn total {turn.state.turn_total}{note}")
        if not roll_again or turn.state.dice_in_hand == 0:
            return turn.bank()
    return turn.state.turn_total


def score_of(dice, rules):
    from .scoring import score_selection
    return score_selection(counts_from_dice(dice), rules)


def versus(args) -> None:
    rules = DEFAULT_RULES
    hot_dice = not args.no_hot_dice
    rng = random.Random(args.seed) if args.seed is not None else random.Random()
    advisor = Advisor(rules=rules, hot_dice=hot_dice, allow_hold=args.hold)
    bot_name = "Rusty"

    print("=" * 74)
    print(f"  FARKLE — you vs {bot_name} (a friendly practice bot)")
    print(f"  Hot-dice: {'ON' if hot_dice else 'OFF'}   "
          f"Hold rule: {'ON' if args.hold else 'OFF'}   "
          f"first to {args.target} wins")
    print(f"  Tip: watch {bot_name}'s keeps to learn the scoring patterns. "
          f"Use '?' for a hint.")
    print("=" * 74)

    you, bot = 0, 0
    while you < args.target and bot < args.target:
        print(f"\n===== YOUR TURN (you {you} — {bot_name} {bot}) =====")
        banked = _human_turn(advisor, rules, hot_dice, rng)
        if banked is None:
            print("\nThanks for playing!")
            return
        you += banked
        print(f"  You now have {you}.")
        if you >= args.target:
            break
        bot += _bot_take_turn(bot_name, rules, hot_dice, rng)
        print(f"  {bot_name} now has {bot}.")

    print("\n" + "=" * 74)
    if you >= args.target and you > bot:
        print(f"  You win {you} to {bot}! ")
    elif bot >= args.target and bot > you:
        print(f"  {bot_name} wins {bot} to {you}. Better luck next time!")
    else:
        print(f"  Final score — you {you}, {bot_name} {bot}.")
    print("=" * 74)


# --- advise mode -----------------------------------------------------------

def advise(args) -> None:
    hot_dice = not args.no_hot_dice
    advisor = Advisor(rules=DEFAULT_RULES, hot_dice=hot_dice,
                      allow_hold=args.hold)
    dice = args.dice
    if not dice:
        raw = input("Enter the dice you rolled (e.g. 1 1 3 4 5 6): ")
        dice = [int(x) for x in raw.replace(",", " ").split()]
    if args.hold and args.held:
        print("(analysing with dice already held: "
              f"{_fmt_dice(args.held)})")
    _report(advisor, dice, args.turn_total, held=args.held or ())


# --- sim mode --------------------------------------------------------------

def sim(args) -> None:
    hot_dice = not args.no_hot_dice
    rules = DEFAULT_RULES
    catalog = {
        "optimal": strategies.optimal(rules, hot_dice),
        "rusty": strategies.practice_bot,
        "greedy": strategies.greedy_max_points,
        "bank_at_300": strategies.bank_at(300),
        "bank_at_500": strategies.bank_at(500),
        "bank_at_1000": strategies.bank_at(1000),
    }

    if args.tournament:
        print(f"Running {args.games} games (target {args.target}, "
              f"hot dice {'ON' if hot_dice else 'OFF'})...")
        wins = tournament(catalog, games=args.games, target=args.target,
                          rules=rules, hot_dice=hot_dice)
        print("\nWins:")
        for name, w in sorted(wins.items(), key=lambda kv: -kv[1]):
            print(f"  {name:<16}{w:>6}  ({w / args.games:.1%})")
        return

    print(f"Per-turn value over {args.trials} trials "
          f"(hot dice {'ON' if hot_dice else 'OFF'}):\n")
    print(f"  {'strategy':<16}{'mean':>8}{'stdev':>8}{'farkle%':>9}{'best':>8}")
    print("  " + "-" * 50)
    for name, strat in catalog.items():
        stats = evaluate_strategy(strat, trials=args.trials, rules=rules,
                                  hot_dice=hot_dice, seed=args.seed or 0)
        print(f"  {name:<16}{stats.mean:>8.1f}{stats.stdev:>8.1f}"
              f"{stats.farkle_rate:>8.1%}{stats.best:>8}")

    print("\nFarkle probability by dice remaining:")
    for n in range(1, 7):
        print(f"  {n} dice: {farkle_probability(n, rules):.1%}")


# --- entry point -----------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="farkle",
        description="Farkle simulator with an expected-value optimal-play "
                    "advisor (hot-dice and hold house rules supported).",
    )
    p.add_argument("--no-hot-dice", action="store_true",
                   help="disable the 'pick up all six and keep going' rule")
    p.add_argument("--hold", action="store_true",
                   help="enable the hold rule (set aside non-scoring dice to "
                        "build toward a combo)")
    sub = p.add_subparsers(dest="command", required=True)

    pp = sub.add_parser("play", help="play through turns interactively")
    pp.add_argument("--target", type=int, default=10000)
    pp.add_argument("--seed", type=int, default=None)
    pp.set_defaults(func=play)

    pv = sub.add_parser("vs", help="play against Rusty, the practice bot")
    pv.add_argument("--target", type=int, default=4000)
    pv.add_argument("--seed", type=int, default=None)
    pv.set_defaults(func=versus)

    pa = sub.add_parser("advise", help="analyse a single roll")
    pa.add_argument("dice", nargs="*", type=int,
                    help="the face values you rolled, e.g. 1 1 3 4 5 6")
    pa.add_argument("--turn-total", type=int, default=0,
                    help="points already banked this turn")
    pa.add_argument("--held", nargs="*", type=int, default=None,
                    help="dice you are already holding (with --hold)")
    pa.set_defaults(func=advise)

    ps = sub.add_parser("sim", help="Monte-Carlo strategies")
    ps.add_argument("--trials", type=int, default=20000)
    ps.add_argument("--tournament", action="store_true",
                    help="run head-to-head games instead of per-turn stats")
    ps.add_argument("--games", type=int, default=2000)
    ps.add_argument("--target", type=int, default=10000)
    ps.add_argument("--seed", type=int, default=0)
    ps.set_defaults(func=sim)

    return p


def main(argv: Optional[List[str]] = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
