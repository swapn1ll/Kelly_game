"""Kelly game bot (Python).

Edit ONLY the section marked below. Everything outside it talks to the referee.
Print debug output to stderr, never stdout: stdout is reserved for your bets.
"""
import json
import sys
import time
from types import SimpleNamespace


# Do not edit above this line.
# ================== EDIT ONLY THIS SECTION ==================
# Write your strategy in choose_bet. You may add imports and helper functions here.
#
# s (the game state, updated every round):
#   s.role         'A' or 'B' (you play A in one game and B in the other)
#   s.round        this round, starting at 0
#   s.probs        list: s.probs[k] = probability that A wins round k (all rounds)
#   s.my_capital   your money now
#   s.opp_capital  opponent's money now
#   s.time_used    seconds you have spent in choose_bet so far this game (timed by your bot)
#
# Return a whole number. You may bet at most 20% of your money (rounded down);
# a bigger bet is lowered to that. You have 120 seconds per game.

def choose_bet(s):
    p = s.probs[s.round]
    q = p if s.role == 'A' else 1 - p           # my chance of winning this round
    kelly = int((2 * q - 1) * s.my_capital)      # Kelly: bet the fraction 2q - 1
    limit = s.my_capital * 20 // 100             # the rule: at most 20% of your money
    return max(0, min(limit, kelly))

# ============================================================
# Do not edit below this line.


def main():
    state = None
    for line in sys.stdin:
        msg = json.loads(line)
        if msg['type'] == 'start':
            state = SimpleNamespace(
                role=msg['role'], probs=msg['probs'], round=0,
                my_capital=msg['my_capital'], opp_capital=msg['opp_capital'], time_used=0.0)
            print(json.dumps({'ready': True}), flush=True)
        elif msg['type'] == 'bet':
            state.round = msg['round']
            state.my_capital = msg['my_capital']
            state.opp_capital = msg['opp_capital']
            started = time.monotonic()
            bet = int(choose_bet(state))
            state.time_used += time.monotonic() - started
            print(json.dumps({'bet': bet}), flush=True)


if __name__ == '__main__':
    main()
