"""Game rules, independent of networking and display."""
import math
import re
from pathlib import Path


def load_config(path):
    """A parameter file: A's starting money, B's starting money, then the probability
    that A wins each round (any number of them, spread over any lines).
    Lines starting with # are comments. The number of rounds is how many probabilities there are."""
    lines = [s.split('#')[0].strip() for s in Path(path).read_text(encoding='utf-8-sig').splitlines()]
    lines = [s for s in lines if s]
    if len(lines) < 3:
        raise ValueError('Expected capital A, capital B, then the probabilities.')
    a, b = int(lines[0]), int(lines[1])
    p = [float(s) for s in re.split(r'[,\s]+', ' '.join(lines[2:])) if s]
    if p and p[0] > 1 and p[0] == int(p[0]):     # older files also listed the number of rounds
        n, p = int(p[0]), p[1:]
        if n != len(p):
            raise ValueError(f'The file says {n} rounds but has {len(p)} probabilities.')
    if a <= 0 or b <= 0 or not p:
        raise ValueError('Capitals must be positive and there must be at least one probability.')
    if any(not math.isfinite(q) or not 0 <= q <= 1 for q in p):
        raise ValueError('Probabilities must be finite numbers between 0 and 1.')
    return a, b, p


MAX_BET_PERCENT = 20      # a player may bet at most this percent of their current money


def max_bet(capital):
    """The largest legal bet: MAX_BET_PERCENT of capital, rounded down."""
    return capital * MAX_BET_PERCENT // 100


def validate_bet(bet, capital):
    if type(bet) is not int or not 0 <= bet <= max_bet(capital):
        raise ValueError(f'Bet must be an integer from 0 to {MAX_BET_PERCENT}% of capital, rounded down.')
    return bet


def adjust_bet(bet, capital):
    """Lower an over-limit integer bet to the maximum; reject anything else illegal."""
    if type(bet) is int and bet > max_bet(capital):
        return max_bet(capital)
    return validate_bet(bet, capital)


def resolve_round(a, b, bet_a, bet_b, probability, draw):
    validate_bet(bet_a, a)
    validate_bet(bet_b, b)
    winner = 'A' if draw <= probability else 'B'
    stake = bet_a + bet_b
    transfer = min(stake, b if winner == 'A' else a)
    if winner == 'A':
        return a + transfer, b - transfer, winner, transfer
    return a - transfer, b + transfer, winner, transfer
