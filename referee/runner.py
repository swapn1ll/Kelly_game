"""Runs Kelly matches between bots. The referee starts each bot itself.

How a bot is run (same idea as the No Tipping architecture):
  * Every game starts a fresh process for each bot, from its folder in bots.json.
  * Startup is free: the bot gets a "start" message and replies {"ready": true}
    before any clock runs (up to STARTUP_LIMIT seconds).
  * Each round A, then B, gets a "bet" message and replies {"bet": <int>}
    (chess clock: only the bot being asked has its clock running; B is not
    told A's bet until the round is over). 120 s per bot per game.
  * Over-limit bets are lowered to max_bet (20% of capital, rounded down). A negative, non-integer
    or missing bet, a crash, invalid JSON, too much output or running out of
    time forfeits that game: all of that game's money goes to the opponent.

Messages are one JSON object per line. See README "Writing a bot".
"""
import json
import os
import queue
import random
import secrets
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .engine import MAX_BET_PERCENT, adjust_bet, load_config, max_bet, resolve_round

ROOT = Path(__file__).resolve().parent.parent      # the repository folder
PROTOCOL_VERSION = 1
STARTUP_LIMIT = 30.0        # seconds a bot may take to start (not on its clock)
OUTPUT_LIMIT = 65536        # bytes a bot may print per reply (stdout or stderr)


class BotError(Exception):
    """A bot broke the protocol: crash, bad JSON, too much output, or timeout."""


def _resolve(arg, cwd):
    """{python} -> this Python; ./prog -> full path to prog in the bot folder (prog.exe on Windows)."""
    if arg == '{python}':
        return sys.executable
    if arg.startswith(('./', '.\\')):
        p = Path(cwd) / arg[2:]
        if os.name == 'nt' and not p.suffix:
            p = p.with_suffix('.exe')
        return str(p)
    return arg


def load_bots(path='bots.json'):
    """Read the roster. Each entry: name, cwd, command, optional build."""
    path = (ROOT / path).resolve()
    entries = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(entries, list) or not entries:
        raise ValueError('bots.json must be a list of bots')
    names = set()
    for i, bot in enumerate(entries):
        name = bot.get('name')
        if not isinstance(name, str) or not name.strip() or name in names:
            raise ValueError('Every bot needs a unique, non-empty "name"')
        names.add(name)
        cwd = (path.parent / bot.get('cwd', '.')).resolve()
        if not cwd.is_dir():
            raise ValueError(f'{name}: folder not found: {cwd}')
        for key in ('command', 'build'):
            cmd = bot.get(key)
            if key == 'build' and cmd is None:
                continue
            if not isinstance(cmd, list) or not cmd or not all(isinstance(x, str) for x in cmd):
                raise ValueError(f'{name}: "{key}" must be a non-empty list of strings')
            bot[key] = [_resolve(x, cwd) for x in cmd]
        bot['cwd'] = str(cwd)
    return entries


_built = {}   # bot folder -> fingerprint of its files right after the last successful build


def _fingerprint(folder):
    out = []
    for f in sorted(Path(folder).rglob('*')):
        if f.is_file() and '__pycache__' not in f.parts:
            st = f.stat()
            out.append((str(f), st.st_mtime_ns, st.st_size))
    return hash(tuple(out))


def build(bot):
    """Run a bot's build step (e.g. compiling C++) outside any clock.

    Skipped when nothing in the bot's folder changed since its last build,
    so only the first tournament after an edit waits for the compiler.
    """
    if not bot.get('build'):
        return
    key = str(Path(bot['cwd']).resolve())
    if _built.get(key) == _fingerprint(key):
        return
    r = subprocess.run(bot['build'], cwd=bot['cwd'], capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        raise RuntimeError(f"build failed: {(r.stderr or r.stdout).strip()[-300:]}")
    _built[key] = _fingerprint(key)


class BotSession:
    """One running bot process for one game."""

    def __init__(self, bot):
        self.bot = bot
        self.proc = None
        self.lines = queue.Queue()
        self.stderr_tail = []
        self.stderr_bytes = 0

    def start(self):
        try:
            self.proc = subprocess.Popen(self.bot['command'], cwd=self.bot['cwd'],
                                         stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                         stderr=subprocess.PIPE, text=True, bufsize=1,
                                         encoding='utf-8', errors='replace')
        except OSError as exc:
            raise BotError(f'could not start: {exc}')
        self.readers = [threading.Thread(target=self._read_out, daemon=True),
                        threading.Thread(target=self._read_err, daemon=True)]
        for r in self.readers:
            r.start()

    def _read_out(self):
        for line in self.proc.stdout:
            self.lines.put(line)
        self.lines.put(None)

    def _read_err(self):
        for line in self.proc.stderr:      # keep a short tail for error messages
            self.stderr_bytes += len(line)
            self.stderr_tail = (self.stderr_tail + [line])[-5:]

    def ask(self, msg, timeout):
        """Send one message, wait for one JSON reply. Returns (reply, seconds)."""
        start = time.monotonic()
        before_err = self.stderr_bytes
        try:
            self.proc.stdin.write(json.dumps(msg, separators=(',', ':')) + '\n')
            self.proc.stdin.flush()
        except (OSError, ValueError):
            raise BotError('crashed' + self._err_note())
        try:
            line = self.lines.get(timeout=max(0.001, timeout))
        except queue.Empty:
            raise BotError('time')
        elapsed = time.monotonic() - start
        if line is None:
            raise BotError('crashed' + self._err_note())
        if len(line) > OUTPUT_LIMIT or self.stderr_bytes - before_err > OUTPUT_LIMIT:
            raise BotError('too much output')
        try:
            reply = json.loads(line)
        except ValueError:
            raise BotError(f'invalid JSON: {line.strip()[:60]!r}')
        if not isinstance(reply, dict):
            raise BotError('reply must be a JSON object')
        return reply, elapsed

    def _err_note(self):
        tail = ''.join(self.stderr_tail).strip()
        return f' ({tail[-160:]})' if tail else ''

    def close(self):
        if not self.proc:
            return
        try:
            self.proc.stdin.close()
        except OSError:
            pass
        try:
            self.proc.wait(timeout=1)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait()
        for r in self.readers:
            r.join(timeout=1)
        for stream in (self.proc.stdout, self.proc.stderr):
            try:
                stream.close()
            except OSError:
                pass


def play_game(bots, config, seed, clock, game=1, on_round=None, delay=0, stop=None, live=None,
              budget=None):
    """Play one game. bots = [bot playing A, bot playing B].

    clock is the seconds each bot has left, either one number or [A's, B's].
    Each round both bots are asked at the same moment; each is timed from the moment
    its own message is sent until it answers. Neither is told the other's bet until
    the round is over.
    Returns {'capital': [A, B], 'rows': [...], 'errors': [errA, errB], 'clocks': [...]}.
    live (optional dict) is kept up to date for the dashboard: live['clocks'] and
    live['since'][role] = when that bot started thinking (None when it is not thinking).
    """
    cap_a, cap_b, probs = config
    caps = [cap_a, cap_b]
    clocks = [float(c) for c in clock] if isinstance(clock, (list, tuple)) else [float(clock)] * 2
    if live is not None:
        live['clocks'], live['since'] = clocks, [None, None]
    rng = random.Random(seed * 10 + game)   # fresh random draws for each game
    rows, errors = [], [None, None]
    sessions = [BotSession(b) for b in bots]
    pool = ThreadPoolExecutor(max_workers=2)
    try:
        def start(role):                  # untimed: launch + start message + ready reply
            s = sessions[role]
            s.start()
            reply, _ = s.ask({'type': 'start', 'protocol_version': PROTOCOL_VERSION,
                              'role': 'AB'[role], 'probs': probs,
                              'my_capital': caps[role], 'opp_capital': caps[1 - role]},
                             STARTUP_LIMIT)
            if reply.get('ready') is not True:
                raise BotError('did not reply {"ready": true} to the start message')

        for role, fut in enumerate([pool.submit(start, r) for r in (0, 1)]):
            try:
                fut.result()
            except BotError as exc:
                errors[role] = f'startup: {exc}'

        for k, p in enumerate(probs):
            if any(errors) or min(caps) == 0 or (stop and stop.is_set()):
                break

            def ask(role):
                msg = {'type': 'bet', 'round': k, 'my_capital': caps[role], 'opp_capital': caps[1 - role]}
                if clocks[role] <= 0:                       # used up all its time in an earlier game
                    return None, 'time', None
                if live is not None:
                    live['since'][role] = time.monotonic()
                try:
                    reply, elapsed = sessions[role].ask(msg, clocks[role])
                except BotError as exc:
                    if str(exc) == 'time':
                        clocks[role] = 0.0
                    if live is not None:
                        live['since'][role] = None
                    return None, str(exc), None
                clocks[role] -= elapsed
                if clocks[role] < 0:
                    clocks[role] = 0.0
                if live is not None:
                    live['since'][role] = None
                if clocks[role] == 0.0:
                    return None, 'time', None
                asked = reply.get('bet')
                try:
                    return adjust_bet(asked, caps[role]), None, asked
                except ValueError:
                    return None, f'illegal bet {asked!r}', asked

            # both think at the same time, each on its own clock
            results = [f.result() for f in [pool.submit(ask, r) for r in (0, 1)]]
            errs = [r[1] for r in results]
            if any(errs):
                errors = errs
                if bool(errs[0]) != bool(errs[1]):          # one side failed: it forfeits
                    loser = 0 if errs[0] else 1
                    caps[1 - loser] += caps[loser]
                    caps[loser] = 0
                rows.append({'round': k + 1, 'capital': list(caps), 'errors': errs})
                if on_round:
                    on_round(rows[-1], clocks)
                break
            bet_a, bet_b = results[0][0], results[1][0]
            draw = rng.random()
            a, b, winner, transfer = resolve_round(caps[0], caps[1], bet_a, bet_b, p, draw)
            caps = [a, b]
            row = {'round': k + 1, 'capital': list(caps), 'probability': p, 'draw': draw,
                   'bet_A': bet_a, 'bet_B': bet_b, 'winner_role': winner, 'transfer': transfer,
                   'clocks': [round(c, 3) for c in clocks]}
            adjusted = {'AB'[r]: results[r][2] for r in (0, 1) if results[r][2] != results[r][0]}
            if adjusted:
                row['adjusted_from'] = adjusted
            rows.append(row)
            if on_round:
                on_round(row, clocks)
            if delay and stop is not None:
                stop.wait(delay)
            elif delay:
                time.sleep(delay)
        if any(errors) and not rows:                       # failed before round 1
            if bool(errors[0]) != bool(errors[1]):
                loser = 0 if errors[0] else 1
                caps[1 - loser] += caps[loser]
                caps[loser] = 0
            rows.append({'round': 0, 'capital': list(caps), 'errors': errors})
        return {'capital': caps, 'rows': rows, 'errors': errors, 'clocks': clocks}
    finally:
        for s in sessions:
            s.close()
        pool.shutdown(wait=False)


def play_match(bot1, bot2, config_path, seed=None, clock=120.0, out_dir=None,
               on_progress=None, delay=0, stop=None, live=None):
    """Two games, roles swapped, same parameters, fresh random draws in each game.

    Each bot has `clock` seconds per game; the clock starts fresh for game 2.

    Writes results.json and replay.html to out_dir (if given) and returns the
    replay state: names, history rows, summary with each team's total.
    """
    a0, b0, probs = load_config(ROOT / config_path)
    seed = seed if seed is not None else secrets.randbelow(2**31)
    names = [bot1['name'], bot2['name']]
    state = {'status': 'Starting', 'names': names, 'history': [], 'seed': seed, 'time_budget': clock,
             'probs': probs, 'initial_capital_A': a0, 'initial_capital_B': b0, 'config': str(config_path)}
    totals = [0, 0]
    matches = []
    team_clocks = [float(clock), float(clock)]
    for game in (1, 2):
        order = [0, 1] if game == 1 else [1, 0]      # team index playing A, then B
        players = [(bot1, bot2)[order[0]], (bot1, bot2)[order[1]]]

        def team_caps(role_caps):
            t = [0, 0]
            for role, team in enumerate(order):
                t[team] = role_caps[role]
            return t

        def snapshot(row, clocks):
            tc = team_caps(row['capital'])
            entry = {'match': game, 'round': row['round'], 'capital': tc,
                     'totals': [totals[i] + tc[i] for i in range(2)]}
            if 'errors' in row:
                entry['errors'] = row['errors']
            else:
                entry.update(probability=row['probability'], draw=row['draw'], bet_A=row['bet_A'],
                             bet_B=row['bet_B'], transfer=row['transfer'],
                             winner=names[order['AB'.index(row['winner_role'])]])
                if 'adjusted_from' in row:
                    entry['adjusted_from'] = row['adjusted_from']
            entry['clocks'] = team_caps([round(c, 2) for c in clocks])
            state['history'].append(entry)
            state['status'] = f'Game {game} · round {row["round"]}'
            if on_progress:
                on_progress(state)

        team_clocks = [float(clock), float(clock)]   # fresh 120 s for every game
        start_caps = [a0, b0]
        state['history'].append({'match': game, 'round': 0, 'capital': team_caps(start_caps),
                                 'totals': [totals[i] + team_caps(start_caps)[i] for i in range(2)],
                                 'clocks': [round(c, 2) for c in team_clocks]})
        state['status'] = f'Game {game} · starting the bots'
        if on_progress:                              # show the starting money before round 1
            on_progress(state)
        if live is not None:
            live.clear()
            live['order'] = order
        result = play_game(players, (a0, b0, probs), seed, [team_clocks[t] for t in order], game,
                           on_round=snapshot, delay=delay, stop=stop, live=live, budget=clock)
        for role, team in enumerate(order):
            team_clocks[team] = result['clocks'][role]
        fa, fb = result['capital']
        for role, team in enumerate(order):
            totals[team] += result['capital'][role]
        matches.append({'type': 'game_over', 'name_A': players[0]['name'], 'name_B': players[1]['name'],
                        'final_capital_A': fa, 'final_capital_B': fb,
                        'errors': result['errors'] if any(result['errors']) else None})
        if stop and stop.is_set():
            break
    state['status'] = 'Finished'
    state['summary'] = {'type': 'match_over', 'totals': dict(zip(names, totals)), 'matches': matches}
    if out_dir:
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(state, indent=1)
        (out / 'results.json').write_text(payload, encoding='utf-8')
        html = (ROOT / 'dashboard' / 'replay.html').read_text(encoding='utf-8')
        (out / 'replay.html').write_text(html.replace('/* REPLAY_DATA */ null', payload.replace('<', '\\u003c')),
                                         encoding='utf-8')
    return state
