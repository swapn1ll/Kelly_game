"""Generate a practice parameter file for the params/ folder.

  python3 start.py params --a 2000 --b 3500 --rounds 100 --low 0.4 --high 0.7 --out params/my_game.txt

Probabilities (the chance that A wins each round) are drawn uniformly between
--low and --high. The spec: capitals between $1000 and $8000, A starts with less
money but has better odds, 10 to 2000 rounds. Use --seed to get the same file again.
"""
import argparse
import random
from pathlib import Path


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--a', type=int, required=True, help="A's starting money")
    ap.add_argument('--b', type=int, required=True, help="B's starting money")
    ap.add_argument('--rounds', type=int, required=True)
    ap.add_argument('--low', type=float, default=0.4)
    ap.add_argument('--high', type=float, default=0.7)
    ap.add_argument('--seed', type=int)
    ap.add_argument('--note', default='', help='a comment written at the top of the file')
    ap.add_argument('--out', required=True)
    args = ap.parse_args()
    if not (args.a > 0 and args.b > 0 and args.rounds > 0 and 0 <= args.low <= args.high <= 1):
        raise SystemExit('Need positive capitals and rounds, and 0 <= low <= high <= 1')
    rng = random.Random(args.seed)
    probs = [round(rng.uniform(args.low, args.high), 3) for _ in range(args.rounds)]
    lines = [f'# {args.note}'] if args.note else []
    lines += [f'# A ${args.a}, B ${args.b}, {args.rounds} rounds, P(A wins) uniform in [{args.low}, {args.high}]',
              str(args.a), str(args.b)]
    lines += [' '.join(map(str, probs[i:i + 20])) for i in range(0, len(probs), 20)]
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(f'Wrote {args.out}: mean P(A) = {sum(probs) / len(probs):.3f}')


if __name__ == '__main__':
    main()
