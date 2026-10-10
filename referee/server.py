"""Tournament dashboard: pick bots, pairings and parameter files in the browser.

  python3 start.py            # then open http://127.0.0.1:8090

Bots come from bots.json. Parameter files come from params/: paste in
as many as you like and press "Rescan folder" on the page. Standard library only.
"""
import argparse
import json
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .runner import ROOT, load_bots, play_match
from .tournament import build_all, list_params, pairing_result

SAVED = ROOT / 'results' / 'all_results.json'   # every finished pairing, kept across restarts


class Tournament:
    """One tournament at a time, run on a background thread."""

    def __init__(self, registry, params):
        self.registry = registry
        self.params_dirs = params.split(',')
        self.lock = threading.Lock()
        self.stop_flag = threading.Event()
        self.thread = None
        try:
            self.done = json.loads(SAVED.read_text(encoding='utf-8'))     # finished pairings so far
        except (OSError, ValueError):
            self.done = []
        self.state = {'status': 'idle', 'message': 'Choose bots and pairings, then start.',
                      'pairings': list(self.done), 'current': None,
                      'run_from': len(self.done)}
        self.match = None                           # full state of the match being played (for /live)
        self.clock = {}                             # live clocks of that match, ticking while a bot thinks

    def save(self):
        SAVED.parent.mkdir(parents=True, exist_ok=True)
        SAVED.write_text(json.dumps(self.done, indent=1), encoding='utf-8')

    def clear(self):
        if self.thread and self.thread.is_alive():
            raise ValueError('Stop the tournament before clearing the results.')
        if SAVED.exists():                          # keep a backup, just in case
            SAVED.rename(SAVED.with_name(f'all_results-cleared-{time.strftime("%Y%m%d-%H%M%S")}.json'))
        with self.lock:
            self.done = []
            self.state.update(pairings=[], current=None, run_from=0,
                              status='idle', message='Results cleared.')

    def setup(self):
        bots = load_bots(self.registry)
        return {'bots': [{'key': b['name'], 'name': b['name']}
                         for b in bots],
                'params': list_params(self.params_dirs),
                'params_dir': ' and '.join(d + '/' for d in self.params_dirs)}

    def snapshot(self):
        with self.lock:
            return json.loads(json.dumps(self.state))

    def live(self):
        m = self.match
        if not m:
            return {'status': 'No match yet. Start a tournament.', 'names': [], 'history': []}
        out = None
        for _ in range(5):                          # the match thread may be adding a row right now
            try:
                out = json.loads(json.dumps(m))
                break
            except RuntimeError:
                time.sleep(0.01)
        if out is None:
            out = {'status': m.get('status', ''), 'names': m['names'], 'history': list(m['history'])}
        if out.get('status') != 'Finished':
            out.pop('seed', None)                   # never show the luck of a match still being played
        c = self.clock
        if out.get('status') != 'Finished' and 'order' in c and 'clocks' in c:
            now, left, thinking = time.monotonic(), [0.0, 0.0], [False, False]
            for role, team in enumerate(c['order']):
                since = c['since'][role]
                left[team] = max(0.0, c['clocks'][role] - (now - since if since else 0))
                thinking[team] = since is not None
            out['live_clocks'], out['thinking'] = [round(x, 2) for x in left], thinking
            if any(thinking) and out.get('history'):
                last = out['history'][-1]
                who = ('both bots are' if all(thinking) else out['names'][thinking.index(True)] + ' is')
                out['status'] = f"Game {last['match']} · round {last['round'] + 1}: {who} thinking"
        return out

    def start(self, req):
        if self.thread and self.thread.is_alive():
            raise ValueError('A tournament is already running. Stop it first.')
        roster = {b['name']: b for b in load_bots(self.registry)}
        valid = {p['file'] for p in list_params(self.params_dirs) if 'error' not in p}
        plan = []
        for p in req.get('pairings', []):
            a, b, cfg = p.get('a'), p.get('b'), p.get('config')
            if a not in roster or b not in roster or a == b:
                raise ValueError('Each pairing needs two different bots from bots.json.')
            if cfg not in valid:
                raise ValueError(f'Unknown or invalid parameter file: {cfg}')
            plan.append((a, b, cfg))
        if not plan:
            raise ValueError('Add at least one pairing.')
        budget = 120.0                              # seconds per bot per game
        names = sorted({n for a, b, _ in plan for n in (a, b)})
        out = ROOT / 'results' / 'tournament' / time.strftime('%Y%m%d-%H%M%S')
        self.stop_flag.clear()
        with self.lock:
            first = len(self.done)                  # earlier results stay in the results table
            pairings = list(self.done) + [{'bots': [a, b], 'config': cfg, 'dir': f'{i + 1:02d}'}
                                          for i, (a, b, cfg) in enumerate(plan)]
            self.state = {'status': 'running', 'message': 'Preparing bots (compiling C++ if needed)...',
                          'time_budget': budget, 'output': str(out.relative_to(ROOT)),
                          'pairings': pairings, 'run_from': first,
                          'current': None}
            self.match = None
        self.thread = threading.Thread(target=self.run, args=(roster, plan, first, budget, out),
                                       daemon=True)
        self.thread.start()

    def run(self, roster, plan, first, budget, out):
        out.mkdir(parents=True, exist_ok=True)
        build_all([roster[n] for n in sorted({n for a, b, _ in plan for n in (a, b)})])  # before any clock
        for i, (a, b, cfg) in enumerate(plan):
            if self.stop_flag.is_set():
                break
            with self.lock:
                entry = self.state['pairings'][first + i]
                self.state['current'] = first + i
                self.state['message'] = f'Pairing {i + 1} of {len(plan)}: {a} vs {b}'
                self.match = {'status': f'Starting {a} vs {b}...', 'names': [a, b], 'history': [],
                              'time_budget': budget}
                self.clock = {}

            def progress(st):
                self.match = st                     # copied only when the page asks (see live)

            try:
                # A fresh secret seed per pairing (both games of the pairing share it), so files
                # from earlier pairings say nothing about the luck in this one.
                seed = secrets.randbelow(2**31)
                st = play_match(roster[a], roster[b], cfg, seed, budget, out / entry['dir'],
                                on_progress=progress, stop=self.stop_flag, live=self.clock)
                self.match = st
                result = pairing_result(st, cfg)
                result['seed'] = seed                   # revealed only once the pairing is over
                result['replay'] = '/' + (out / entry['dir'] / 'replay.html').relative_to(ROOT).as_posix()
                if self.stop_flag.is_set():
                    result = {'error': 'stopped'}
            except Exception as exc:
                result = {'error': str(exc)}
            with self.lock:
                entry.update(result)
                if 'totals' in entry:               # finished: keep it in the results for good
                    self.done.append(dict(entry))
                    self.save()
                (out / 'results.json').write_text(json.dumps(self.state['pairings'][first:], indent=2),
                                                  encoding='utf-8')
        with self.lock:
            self.state['current'] = None
            self.state['status'] = 'stopped' if self.stop_flag.is_set() else 'finished'
            self.state['message'] = ('Stopped. Finished pairings are kept.' if self.stop_flag.is_set()
                                     else f'Finished. Results saved in {self.state["output"]}/')

    def stop(self):
        self.stop_flag.set()


def make_handler(t):
    page = ROOT / 'dashboard' / 'index.html'
    replay_page = ROOT / 'dashboard' / 'replay.html'

    class Handler(BaseHTTPRequestHandler):
        def send(self, code, body, mime='application/json'):
            data = body if isinstance(body, bytes) else json.dumps(body).encode()
            self.send_response(code)
            self.send_header('Content-Type', mime)
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            path = self.path.split('?')[0]
            try:
                if path in ('/', '/index.html'):
                    return self.send(200, page.read_bytes(), 'text/html; charset=utf-8')
                if path == '/api/setup':
                    return self.send(200, t.setup())
                if path == '/api/state':
                    return self.send(200, t.snapshot())
                if path == '/live':                 # same page as the replays, following the match live
                    return self.send(200, replay_page.read_bytes(), 'text/html; charset=utf-8')
                if path == '/state':
                    return self.send(200, t.live())
            except (OSError, ValueError) as exc:
                return self.send(400, {'error': str(exc)})
            if path.startswith('/results/') and path.endswith('.html'):
                target = (ROOT / path.lstrip('/')).resolve()
                if (ROOT / 'results').resolve() in target.parents and target.is_file():
                    return self.send(200, target.read_bytes(), 'text/html; charset=utf-8')
            self.send(404, {'error': 'not found'})

        def do_POST(self):
            try:
                n = int(self.headers.get('Content-Length') or 0)
                req = json.loads(self.rfile.read(n) or b'{}')
                if self.path == '/api/start':
                    t.start(req)
                elif self.path == '/api/stop':
                    t.stop()
                elif self.path == '/api/clear':
                    t.clear()
                else:
                    return self.send(404, {'error': 'not found'})
                self.send(200, {'ok': True})
            except (ValueError, OSError) as exc:
                self.send(400, {'error': str(exc)})

        def log_message(self, *unused):
            pass

    return Handler


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--port', type=int, default=8090)
    ap.add_argument('--registry', default='bots.json')
    ap.add_argument('--params', default='params', help='folder(s) of parameter files, comma-separated')
    args = ap.parse_args()
    (ROOT / 'params').mkdir(exist_ok=True)
    t = Tournament(args.registry, args.params)
    t.setup()                                       # fail early if bots.json is broken
    server = ThreadingHTTPServer(('127.0.0.1', args.port), make_handler(t))
    print(f'Tournament dashboard: http://127.0.0.1:{server.server_port}  (Ctrl+C to stop)', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        t.stop()
        print('\nStopped.')


if __name__ == '__main__':
    main()
