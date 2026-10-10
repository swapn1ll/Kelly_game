"""Round-robin tournament from the command line (the dashboard uses the same code).

  python3 start.py tournament                                    # every pair, rotate through parameter files
  python3 start.py tournament --config params/sample.txt         # one parameter file for every pairing
  python3 start.py tournament --bots "Kelly (Python)" "Kelly (C++)"

Each pairing is one match: two games with roles swapped, the same parameters
and fresh random draws in each game. A pairing's winner is the bot with more money from
its two games together.
"""
import argparse
import itertools
import json
import secrets
import sys
import time
from pathlib import Path

from .engine import load_config
from .runner import ROOT, build, load_bots, play_match

PARAM_FOLDERS = ('params',)  # parameter files are read from here


def list_params(folders=PARAM_FOLDERS):
    """Every .txt parameter file in the given folders, with its capitals and round count."""
    if isinstance(folders, (str, Path)):
        folders = [folders]
    out = []
    paths = [p for f in folders for p in sorted((ROOT / f).glob('*.txt'))]
    for path in paths:
        rel = path.resolve().relative_to(ROOT).as_posix()
        entry = {'file': rel, 'name': rel[:-4]}
        try:
            a, b, probs = load_config(path)
            entry.update(capital_A=a, capital_B=b, rounds=len(probs),
                         mean_p=round(sum(probs) / len(probs), 3))
        except (OSError, ValueError) as exc:
            entry['error'] = str(exc)
        out.append(entry)
    return out


def pairing_result(state, config):
    """The fields the results table needs from one finished match."""
    a, b, _ = load_config(ROOT / config)
    return {'totals': state['summary']['totals'], 'matches': state['summary']['matches'],
            'capital_A': a, 'capital_B': b}


def build_all(bots):
    """Compile bots that need it, before any clock runs. Returns {name: error or None}."""
    problems = {}
    for b in bots:
        try:
            build(b)
            problems[b['name']] = None
        except Exception as exc:  # the bot will then fail to start and forfeit its games
            problems[b['name']] = str(exc)
    return problems


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--bots', nargs='+', help='bot names from bots.json (default: all)')
    ap.add_argument('--registry', default='bots.json')
    ap.add_argument('--config', help='use this one parameter file for every pairing')
    ap.add_argument('--clock', type=float, default=120, help='seconds per bot per game')
    ap.add_argument('--output', default='results/tournament')
    args = ap.parse_args()

    roster = {b['name']: b for b in load_bots(args.registry)}
    names = args.bots or list(roster)
    missing = [n for n in names if n not in roster]
    if len(names) < 2 or missing:
        raise ValueError(f'Pick at least two bots from: {", ".join(roster)}')
    files = [args.config] if args.config else [p['file'] for p in list_params() if 'error' not in p]
    if not files:
        raise ValueError('No valid parameter files in params/')
    out = ROOT / args.output / time.strftime('%Y%m%d-%H%M%S')

    for name, err in build_all([roster[n] for n in names]).items():
        if err:
            print(f'! {name}: {err}')
    pairs = list(itertools.combinations(names, 2))
    print(f'{len(names)} bots, {len(pairs)} pairings\n')
    pairings = []
    for i, (a, b) in enumerate(pairs):
        config = files[i % len(files)]
        entry = {'bots': [a, b], 'config': config}
        print(f'[{i + 1}/{len(pairs)}] {a} vs {b} ({Path(config).name}) ... ', end='', flush=True)
        seed = secrets.randbelow(2**31)                   # fresh secret luck for every pairing
        state = play_match(roster[a], roster[b], config, seed, args.clock, out / f'{i + 1:02d}')
        entry.update(pairing_result(state, config), seed=seed)
        print(f"${entry['totals'][a]:,} – ${entry['totals'][b]:,}")
        pairings.append(entry)
        (out / 'results.json').write_text(json.dumps(pairings, indent=2), encoding='utf-8')

    print(f'\nResults: {out.relative_to(ROOT)}/')


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('\nStopped. Finished pairings are saved.')
    except (OSError, ValueError) as exc:
        sys.exit(f'Error: {exc}')
