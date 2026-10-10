"""Tests for the rules, the bot runner and the bot templates.

Run from the repository root:  python3 -m unittest discover -s tests -v
"""
import json
import random
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from referee.engine import load_config, validate_bet, adjust_bet, resolve_round  # noqa: E402
from referee.runner import build, load_bots, play_match, play_game  # noqa: E402

TEMPLATES = ROOT / 'bots' / 'templates'


class Rules(unittest.TestCase):
    def test_sum_of_bets_and_boundary(self):
        self.assertEqual(resolve_round(1000, 1500, 100, 150, .6, .6), (1250, 1250, 'A', 250))
        self.assertEqual(resolve_round(1000, 1500, 100, 150, .6, .7), (750, 1750, 'B', 250))

    def test_bankruptcy_cap(self):
        self.assertEqual(resolve_round(5, 1000, 0, 100, 0, .2), (0, 1005, 'B', 5))

    def test_integer_limits(self):
        for bad in [-1, 201, 1.0, True, '5', None]:
            with self.assertRaises(ValueError):
                validate_bet(bad, 1000)
        self.assertEqual(validate_bet(0, 9), 0)

    def test_over_limit_bets_are_lowered(self):
        self.assertEqual(adjust_bet(250, 1000), 200)
        self.assertEqual(adjust_bet(10**9, 55), 11)
        self.assertEqual(adjust_bet(200, 1000), 200)
        self.assertEqual(validate_bet(200, 1000), 200)
        for bad in [-1, 1.0, True, '5', None]:
            with self.assertRaises(ValueError):
                adjust_bet(bad, 1000)

    def test_conservation(self):
        r = random.Random(5)
        a, b = 1000, 8000
        for _ in range(2000):
            a, b, _, _ = resolve_round(a, b, r.randint(0, a//5), r.randint(0,b//5), .55, r.random())
            self.assertEqual(a+b, 9000)
            self.assertGreaterEqual(min(a,b), 0)

    def test_config_without_round_count(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)/'c.txt'
            p.write_text('1000\n1500\n0.5 0.6\n0.7\n', encoding='utf-8')
            self.assertEqual(load_config(p), (1000, 1500, [0.5, 0.6, 0.7]))
            p.write_text('1000\n1500\n3\n0.5 0.6 0.7\n', encoding='utf-8')   # old style still works
            self.assertEqual(load_config(p), (1000, 1500, [0.5, 0.6, 0.7]))

    def test_config_rejects_invalid(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)/'bad.txt'
            for text in ['1000\n1500\n2\n.5', '1000\n1500\nnan', '-1\n1500\n.5', '1000\n1500\n1.5']:
                p.write_text(text, encoding='utf-8')
                with self.assertRaises(ValueError):
                    load_config(p)


class Runner(unittest.TestCase):
    """Matches between small Python bots made from the template."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def bot(self, name, body, header=''):
        # Copy the Python template and replace its EDIT ONLY THIS SECTION with a test strategy.
        folder = self.dir / name
        shutil.copytree(TEMPLATES / 'python', folder)
        path = folder / 'bot.py'
        text = path.read_text(encoding='utf-8')
        start = text.index('# ================== EDIT ONLY THIS SECTION')
        end = text.index('# ============================================================', start)
        mine = header + 'def choose_bet(s):\n' + body + '\n\n'
        path.write_text(text[:start] + mine + text[end:], encoding='utf-8')
        return {'name': name, 'cwd': str(folder), 'command': [sys.executable, 'bot.py']}

    def config(self, text='1000\n1500\n0.52 0.60 0.53 0.38 0.67 0.55 0.49 0.62 0.58 0.44'):
        path = self.dir / 'cfg.txt'
        path.write_text(text, encoding='utf-8')
        return path

    def kelly(self, name='Kelly'):
        return self.bot(name, '    p = s.probs[s.round]\n    q = p if s.role == "A" else 1 - p\n'
                              '    return max(0, min(s.my_capital // 5, int((2*q-1)*s.my_capital)))')

    def test_full_match_role_swap_and_conservation(self):
        a, b = self.kelly('One'), self.bot('Two', '    return s.my_capital // 5')
        st = play_match(a, b, self.config(), seed=1)
        m = st['summary']['matches']
        self.assertEqual((m[0]['name_A'], m[1]['name_A']), ('One', 'Two'))
        self.assertEqual(sum(st['summary']['totals'].values()), 5000)
        self.assertEqual(st['summary']['totals']['One'], m[0]['final_capital_A'] + m[1]['final_capital_B'])
        for row in st['history']:
            self.assertEqual(sum(row['capital']), 2500)

    def test_fresh_draws_in_each_game(self):
        one, two = self.kelly('One'), self.kelly('Two')
        st = play_match(one, two, self.config(), seed=9)
        d1 = [r['draw'] for r in st['history'] if r['match'] == 1 and 'draw' in r]
        d2 = [r['draw'] for r in st['history'] if r['match'] == 2 and 'draw' in r]
        self.assertNotEqual(d1, d2)
        again = play_match(one, two, self.config(), seed=9)
        self.assertEqual(st['history'], again['history'])        # same seed replays the same match

    def test_state_and_history_reach_the_bot(self):
        # The bot fails (illegal bet) unless it gets exactly: role, round, probs, both amounts.
        spy = self.bot('Spy', '    seen = set(vars(s)) - {"time_used"}\n'
                              '    ok = seen == {"role", "round", "probs", "my_capital", "opp_capital"}\n'
                              '    ok = ok and s.my_capital + s.opp_capital > 0 and 0 <= s.round < len(s.probs)\n'
                              '    return 1 if ok else -1')
        st = play_match(spy, self.bot('Seven', '    return min(7, s.my_capital // 5)'), self.config(), seed=2)
        self.assertFalse(any(g['errors'] for g in st['summary']['matches']))

    def test_over_limit_bet_is_lowered(self):
        st = play_match(self.bot('Big', '    return 10**6'), self.kelly(), self.config(), seed=3)
        rows = [r for r in st['history'] if 'bet_A' in r]
        self.assertTrue(all('adjusted_from' in r for r in rows))
        self.assertFalse(any(g['errors'] for g in st['summary']['matches']))

    def test_illegal_bet_forfeits(self):
        st = play_match(self.bot('Bad', '    return -5'), self.kelly(), self.config(), seed=4)
        self.assertEqual(st['summary']['totals'], {'Bad': 0, 'Kelly': 5000})

    def test_crash_forfeits(self):
        st = play_match(self.bot('Crash', '    raise SystemExit(1)'), self.kelly(), self.config(), seed=4)
        self.assertEqual(st['summary']['totals'], {'Crash': 0, 'Kelly': 5000})

    def test_timeout_forfeits(self):
        slow = self.bot('Slow', '    time.sleep(0.4)\n    return 0', header='import time\n')
        st = play_match(slow, self.kelly(), self.config(), seed=4, clock=0.3)
        self.assertEqual(st['summary']['totals'], {'Slow': 0, 'Kelly': 5000})
        self.assertIn('time', json.dumps(st['summary']['matches']))

    def test_startup_is_not_charged(self):
        late = self.bot('Late', '    return 0', header='import time\ntime.sleep(0.6)\n')
        st = play_match(late, self.kelly(), self.config(), seed=4, clock=0.5)
        self.assertFalse(any(g['errors'] for g in st['summary']['matches']))

    def test_replay_files_written(self):
        out = self.dir / 'out'
        play_match(self.kelly('One'), self.kelly('Two'), self.config(), seed=5, out_dir=out)
        self.assertTrue((out / 'results.json').is_file())
        self.assertIn('Game 1', (out / 'replay.html').read_text(encoding='utf-8'))

    def test_long_config(self):
        st = play_match(self.kelly('One'), self.kelly('Two'), ROOT / 'params' / 'competition_2000.txt', seed=6)
        self.assertEqual(sum(st['summary']['totals'].values()), 18000)


class Templates(unittest.TestCase):
    """The sample bots in bots.json, built from the templates."""

    def setUp(self):
        self.bots = {b['name']: b for b in load_bots('bots.json')}

    def test_cpp_template_plays(self):
        if not (shutil.which('c++') or shutil.which('g++') or shutil.which('clang++')):
            self.skipTest('no C++ compiler')
        build(self.bots['Kelly (C++)'])
        st = play_match(self.bots['Kelly (C++)'], self.bots['Kelly (Python)'], 'params/sample.txt', seed=7)
        self.assertFalse(any(g['errors'] for g in st['summary']['matches']))
        # Same strategy in another language: exactly the same bets and money as Python vs Python.
        py = play_match(self.bots['Kelly (Python)'], self.bots['Kelly (Python)'], 'params/sample.txt', seed=7)
        self.assertEqual([r['capital'] for r in st['history']], [r['capital'] for r in py['history']])

    def test_julia_template_plays(self):
        if not shutil.which('julia'):
            self.skipTest('julia not installed')
        st = play_match(self.bots['Kelly (Julia)'], self.bots['Kelly (Python)'], 'params/sample.txt', seed=7)
        self.assertFalse(any(g['errors'] for g in st['summary']['matches']))
        py = play_match(self.bots['Kelly (Python)'], self.bots['Kelly (Python)'], 'params/sample.txt', seed=7)
        self.assertEqual([r['capital'] for r in st['history']], [r['capital'] for r in py['history']])


if __name__ == '__main__':
    unittest.main()
