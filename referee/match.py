"""Play one match between two bots from bots.json and open the replay.

  python3 start.py match "Kelly (Python)" "Kelly (C++)"
  python3 start.py match "Kelly (C++)" "Kelly (Julia)" --config params/competition_2000.txt

Two games with roles swapped, same parameters, fresh random draws in each game.
Results go to results/match/ (results.json and replay.html). For many bots at
once, use the dashboard: python3 start.py
"""
import argparse
import sys
import webbrowser

from .runner import ROOT, build, load_bots, play_match


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('bot1')
    ap.add_argument('bot2')
    ap.add_argument('--config', default='params/sample.txt')
    ap.add_argument('--clock', type=float, default=120, help='seconds per bot per game')
    ap.add_argument('--registry', default='bots.json')
    ap.add_argument('--output', default='results/match')
    ap.add_argument('--no-browser', action='store_true')
    args = ap.parse_args()
    roster = {b['name']: b for b in load_bots(args.registry)}
    for name in (args.bot1, args.bot2):
        if name not in roster:
            sys.exit(f'Unknown bot {name!r}. In bots.json: {", ".join(roster)}')
        build(roster[name])
    st = play_match(roster[args.bot1], roster[args.bot2], args.config, clock=args.clock, out_dir=ROOT / args.output)
    for g in st['summary']['matches']:
        note = f"  (forfeit: {g['errors']})" if g['errors'] else ''
        print(f"{g['name_A']} (A) ${g['final_capital_A']:,} – {g['name_B']} (B) ${g['final_capital_B']:,}{note}")
    totals = st['summary']['totals']
    print('Totals: ' + ' – '.join(f'{n} ${v:,}' for n, v in totals.items()))
    replay = ROOT / args.output / 'replay.html'
    print(f'Replay: {replay}')
    if not args.no_browser:
        webbrowser.open(replay.as_uri())


if __name__ == '__main__':
    main()
