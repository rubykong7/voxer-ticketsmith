#!/usr/bin/env python3
"""voxer-ticketsmith dashboard and scheduler. Stdlib only.

Serves one card per Linear master (progress, Needs-you items, draft replies, a thread per card) and the
headless session list. Runs `claude -p` one at a time: `sync` every interval_min, `post` on each Post
click, `reply` on each "Send now". Clicks go to $HOME/inbox.jsonl; only Claude writes state.json.

Usage: server.py            serve on 127.0.0.1:<port>
       server.py --test     self-check against a temp home (no claude runs)
"""
import html, json, os, queue, re, shutil, subprocess, sys, tempfile, threading, time, tomllib, uuid
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse
sys.path.insert(0, str(Path(__file__).resolve().parent)); import explain as X; import check_draft as CD

SKILL = Path(__file__).resolve().parent.parent
HOME = Path(os.environ.get('TICKETSMITH_HOME', '~/.voxer-ticketsmith')).expanduser()
CLAUDE = os.environ.get('TICKETSMITH_CLAUDE') or shutil.which('claude') or 'claude'
L, S, V = 'mcp__claude_ai_Linear__', 'mcp__claude_ai_Slack__', 'mcp__voxer__'
DEFAULTS = {
    'port': 8790, 'interval_min': 60, 'model': 'sonnet', 'run_timeout_min': 30,
    'inputs': ['slack', 'voxer'], 'slack_channels': [], 'product_teams': ['PROD'],
    'read_tools': [L + t for t in ('list_issues', 'get_issue', 'list_comments', 'get_user', 'list_issue_statuses')]
                  + [S + t for t in ('slack_search_public_and_private', 'slack_read_thread', 'slack_read_channel', 'slack_read_user_profile')]
                  + [V + t for t in ('list_threads', 'list_recent_messages', 'get_message', 'search_messages', 'get_thread')]
                  + ['mcp__claude_ai_Notion__notion-fetch'],
    'write_tools': [L + 'save_comment', L + 'save_issue'],
    # custom thread commands: [[commands]] match (regex on the owner's post), skill, tools, deny, cwd, timeout_min
    'commands': [],
}
def st_badge(m):
    k = m.get('statusType') or STATUS_TYPE.get(m.get('status'), 'other')
    return f'<span class="st {e(k)}">{e(m.get("status"))}</span>'

STATUS_TYPE = {'In Progress': 'started', 'In Review': 'started', 'In Testing': 'started', 'Todo': 'unstarted', 'Triage': 'triage', 'Backlog': 'backlog'}
ACTIONS = {'edit', 'post', 'resolve', 'reject', 'answer'}
CARD_RE = re.compile(r'^(inbox|[A-Z][A-Z0-9]*-\d+)$')
PAGE_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]*\.html$')
POST_RE = re.compile(r'^## (you|agent) · (.+)$', re.M)
e = lambda s: html.escape(str(s if s is not None else ''), quote=True)

def config():
    c = dict(DEFAULTS)
    try: u = tomllib.loads((HOME / 'config.toml').read_text())
    except FileNotFoundError: u = {}
    c.update(u)
    return c

def command_for(text):
    for k in config()['commands']:
        if re.match(k.get('match', '$^'), text, re.I): return k
    return None

def now_iso(): return datetime.now().astimezone().isoformat(timespec='seconds')   # local, with offset: thread stamps match the owner's

def ts(iso):
    try: return datetime.fromisoformat(iso.replace('Z', '+00:00')).timestamp()
    except Exception: return 0

def ago(t):
    s = int(time.time() - t)
    return 'just now' if s < 60 else f'{s // 60}m ago' if s < 3600 else f'{s // 3600}h ago' if s < 86400 else f'{s // 86400}d ago'

# ---------- state (read-only here) ----------
_last_good = {}
def load_state():
    """state.json; the last good copy when Claude is mid-write."""
    global _last_good
    try: _last_good = json.loads((HOME / 'state.json').read_text())
    except FileNotFoundError: _last_good = {}
    except ValueError: pass
    return _last_good

def inbox():
    try: lines = (HOME / 'inbox.jsonl').read_text().splitlines()
    except FileNotFoundError: return []
    out = []
    for l in lines:
        try: out.append(json.loads(l))
        except ValueError: pass
    return out

def view():
    """state plus clicks Claude hasn't applied yet, so the page reflects them at once."""
    st = load_state()
    items = {i['id']: dict(i) for i in st.get('items', []) if i.get('id')}
    for a in inbox():
        i = items.get(a.get('item'))
        if not i: continue
        k = a.get('action')
        if k == 'edit': i['draft'] = a.get('text', '')
        elif k == 'resolve': i['status'] = 'resolved'
        elif k == 'reject': i['status'] = 'rejected'
        elif k == 'post': i['draft'], i['pending'] = a.get('text', ''), 'posting to Linear…'
        elif k == 'answer': i['pending'] = f'answered: {a.get("text", "")} (applies on the next run)'
    return st, items

def add_inbox(item, action, text=''):
    st = load_state()
    if action not in ACTIONS or item not in {i.get('id') for i in st.get('items', [])}: return False
    with (HOME / 'inbox.jsonl').open('a') as f:
        f.write(json.dumps({'at': now_iso(), 'item': item, 'action': action, 'text': text}) + '\n')
    return True

def thread_posts(card):
    try: parts = POST_RE.split((HOME / 'threads' / f'{card}.md').read_text())
    except FileNotFoundError: return []
    return [(parts[i], parts[i + 1].strip(), parts[i + 2].strip()) for i in range(1, len(parts) - 2, 3)]

def add_post(card, text):
    (HOME / 'threads').mkdir(exist_ok=True)
    with (HOME / 'threads' / f'{card}.md').open('a') as f:
        f.write(f'## you · {time.strftime("%Y-%m-%d %H:%M")}\n{text.strip()}\n\n')

# ---------- runs: one claude -p at a time ----------
Q, RUNNING, LAST_TRY = queue.Queue(), {}, {'sync': 0.0}

def prompt(cmd): return f'Use the voxer-ticketsmith skill. Command: {cmd}. Home: {HOME}. Now: {now_iso()} (use this for every timestamp and cursor; never guess the time).'

def enqueue(name, cmd, write=False, custom=None):
    if name == RUNNING.get('name') or any(n == name for n, *_ in list(Q.queue)): return 'already queued'
    Q.put((name, cmd, write, custom))
    return 'queued' if RUNNING else 'started'

def lock_busy():
    """A run started outside this server (a session) holds run.lock."""
    try: return time.time() - ts(json.loads((HOME / 'run.lock').read_text()).get('started', '')) < 1800
    except (FileNotFoundError, ValueError): return False

def run(name, cmd, write, custom=None):
    c = config()
    tools = ['Skill', 'Read', 'Glob', 'Grep'] + c['read_tools'] + (c['write_tools'] if write else [])
    deny, cwd, timeout, p_text = ['AskUserQuestion'], HOME, c['run_timeout_min'] * 60, prompt(cmd)
    if custom:   # a [[commands]] entry: its own skill, tools, folder and time budget
        tools += custom.get('tools', []); deny += custom.get('deny', [])
        cwd = Path(custom.get('cwd', str(HOME))).expanduser(); timeout = custom.get('timeout_min', c['run_timeout_min']) * 60
        p_text = f'Use the {custom["skill"]} skill. Card: {cmd.split()[1]}. Home: {HOME}. Now: {now_iso()}.'
    sid = str(uuid.uuid4())
    args = [CLAUDE, '-p', p_text, '--session-id', sid, '-n', f'ticketsmith {name}', '--model', c['model'],
            '--permission-mode', 'acceptEdits', '--disallowedTools', *deny, '--allowedTools', *tools]
    env = {k: v for k, v in os.environ.items() if k != 'ANTHROPIC_API_KEY'}   # use the plan, not an API key
    (HOME / 'logs').mkdir(exist_ok=True)
    with (HOME / 'logs' / f'{time.strftime("%Y-%m-%d")}.log').open('a') as log:
        log.write(f'\n== {time.strftime("%H:%M:%S")} {name} session {sid}\n'); log.flush()
        p = subprocess.Popen(args, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
        try: rc = p.wait(timeout=timeout)
        except subprocess.TimeoutExpired: p.kill(); rc = 'timeout'
        log.write(f'== {time.strftime("%H:%M:%S")} {name} exit {rc}\n')

def worker():
    while True:
        name, cmd, write, custom = Q.get()
        while lock_busy(): time.sleep(30)
        RUNNING.update(name=name, started=time.time())
        if name == 'sync': LAST_TRY['sync'] = time.time()
        try: run(name, cmd, write, custom)
        except Exception as x: print(f'run {name} failed: {x}', file=sys.stderr)
        finally: RUNNING.clear(); (HOME / 'run.lock').unlink(missing_ok=True)

def timer():
    while True:
        last = max(ts(load_state().get('synced_at', '')), LAST_TRY['sync'])
        if time.time() - last > config()['interval_min'] * 60: enqueue('sync', 'sync')
        time.sleep(60)

# ---------- pages ----------
CSS = """
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.6 var(--font-sans);-webkit-font-smoothing:antialiased}
main{max-width:1680px;margin:0 auto;padding:28px 28px 40px}a{color:var(--accent);text-decoration:none}a:hover{text-decoration:underline}
header{display:flex;flex-wrap:wrap;gap:8px 16px;align-items:center;margin-bottom:16px}header h1{margin:0 auto 0 0}
h1{margin:0 0 20px;font:600 24px/1.25 var(--font-sans)}h1 a{font-family:var(--font-mono);font-size:18px}
.mut{color:var(--ink-2)}.card{background:var(--paper);border:1px solid var(--line);border-radius:var(--radius);padding:14px 16px;margin:0 0 16px}
.card h2{margin:0 0 6px;font:600 15px var(--font-sans)}.lead{font:16px/1.6 var(--font-sans);margin:4px 0 16px;max-width:80ch}
table{border-collapse:collapse;width:100%;margin:6px 0;font-size:14px}td{padding:7px 10px;border-bottom:1px solid var(--line-2);vertical-align:top}td a:first-child{font-family:var(--font-mono);font-weight:600}td a.t{color:var(--ink)}td:not(:first-child){white-space:nowrap;width:1%}
.st{font-size:12px;font-weight:600;padding:2px 8px;border-radius:10px;white-space:nowrap;color:var(--ink-2);background:var(--fill)}.st.started{color:var(--accent);background:var(--accent-bg)}.st.completed{color:var(--ok);background:var(--ok-bg)}.st.unstarted,.st.triage{color:var(--warn);background:var(--warn-bg)}.st.canceled{color:var(--err);background:var(--err-bg)}
.item{border:1px solid var(--line-2);border-left:3px solid var(--warn);background:var(--warn-bg);border-radius:var(--radius);padding:10px 14px}.item+.item{margin-top:12px}
.item.question{border-left-color:var(--accent);background:var(--accent-bg)}.item.drift{border-left-color:var(--err);background:var(--err-bg)}.item.change{border-left-color:var(--ok);background:var(--ok-bg)}
.item b{font:600 15px var(--font-sans)}.kind{font-size:12px;font-weight:600;text-transform:uppercase;letter-spacing:.06em;color:var(--ink-2)}
blockquote{margin:8px 0;padding:4px 12px;border-left:2px solid var(--line);color:var(--ink-2);white-space:pre-wrap}
textarea,input[type=text]{width:100%;font:15px/1.5 var(--font-sans);color:var(--ink);background:var(--paper);border:1px solid var(--line-2);border-radius:var(--radius);padding:8px 10px;resize:vertical;margin-top:8px}
button{font:inherit;font-size:14px;padding:4px 12px;border:1px solid var(--line);border-radius:var(--radius);background:var(--paper);color:var(--ink-2);cursor:pointer;margin:8px 6px 0 0}
button:hover{color:var(--ink);border-color:var(--ink-3)}button.pri{background:var(--head-bg);border-color:var(--head-bg);color:var(--head-fg)}.warn{color:var(--warn);font-size:12px;margin-top:6px}
.post{margin:0 0 8px;padding:8px 12px;border:1px solid var(--line-2);border-radius:var(--radius);background:var(--fill);white-space:pre-wrap}.post.agent{border-left:3px solid var(--accent)}
.am-root{--font-serif:var(--font-sans);font-family:var(--font-sans);background:transparent}.am-root svg{max-width:100%;height:auto}.post .mut{font-size:12px}details summary{cursor:pointer}.chip{font-size:11px;color:var(--err);white-space:nowrap}.rows{list-style:none;margin:0;padding:0}.rows li{display:flex;gap:16px;align-items:flex-start;padding:8px 0;border-bottom:1px solid var(--line-2)}.rows li:last-child{border:0}.rows li>div{flex:1}.rows .go{white-space:nowrap}pre{white-space:pre-wrap;word-break:break-word;font:12px/1.5 var(--font-mono)}
.msg{margin:8px 0;padding:8px 12px;border:1px solid var(--line-2);border-radius:var(--radius);background:var(--paper);white-space:pre-wrap}
header button{margin-top:0}
"""
JS = """
const H={'Content-Type':'application/json','X-Dash':'1'};
try{const t=localStorage.getItem('theme');if(t)document.documentElement.dataset.theme=t}catch(e){}
function theme(){const d=document.documentElement.dataset,dark=matchMedia('(prefers-color-scheme:dark)').matches;const cur=d.theme||(dark?'dark':'light');d.theme=cur==='dark'?'light':'dark';try{localStorage.setItem('theme',d.theme)}catch(e){};amMode()}
function amMode(){const t=document.documentElement.dataset.theme||'auto';document.querySelectorAll('.am-root').forEach(r=>r.dataset.mode=t)}
amMode()
async function api(path,body,el){const r=await fetch(path,{method:'POST',headers:H,body:JSON.stringify(body)});
 const t=await r.text();if(el)el.textContent=t;if(r.ok&&!el)location.reload();return r.ok}
function val(id){return document.getElementById(id).value}
function act(item,action,textId,el){return api('/api/action',{item,action,text:textId?val(textId):''},el)}
function post(item,el){if(el.dataset.armed){act(item,'post','d-'+item)}else{el.dataset.armed=1;el.textContent='Click again to post to Linear'}}
function cp(id,b){navigator.clipboard.writeText(val(id));b.textContent='copied'}
function dirty(){return [...document.querySelectorAll('textarea,input[type=text]')].some(t=>t.value!==t.defaultValue)||['TEXTAREA','INPUT'].includes(document.activeElement.tagName)}
let sig=null;setInterval(async()=>{try{const s=await(await fetch('/api/sig')).text();if(sig&&s!==sig&&!dirty())location.reload();sig=s}catch(e){}},10000);
"""

def page(title, body, extra_css=''):
    return (f'<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{e(title)}</title><style>{X.CSS}{CSS}</style>{f"<style>{extra_css}</style>" if extra_css else ""}</head><body><main>{body}</main>'
            f'<script>{JS}</script></body></html>')

def item_html(i):
    iid, t = e(i['id']), i.get('target') or {}
    src = i.get('source') or {}
    h = [f'<div class="item {e(i.get("kind"))}" id="{iid}"><div class="kind">{e(i.get("kind"))}'
         + (f' · <a href="{e(src.get("url"))}">{e(src.get("label") or "source")}</a>' if src.get('url') or src.get('label') else '') + '</div>',
         f'<b>{e(i.get("title"))}</b>' + (f'<div class="mut">{e(i.get("why"))}</div>' if i.get('why') else '')]
    if i.get('quote'): h.append(f'<blockquote>{e(i["quote"])}</blockquote>')
    if i.get('details'): h.append(X.kv([(k, e(v)) for k, v in i['details'].items()]))   # free-form label → text, from any command
    if i.get('command'): h.append(f'<textarea id="w-{iid}" rows="1" readonly>{e(i["command"])}</textarea><button onclick="cp(\'w-{iid}\',this)">Copy command</button>')
    if i.get('page') and PAGE_RE.match(i['page']): h.append(f'<p><a class="go" href="/p/{e(i["page"])}">explain page →</a></p>')   # an HTML file in pages/, from any command
    if i.get('pending'): h.append(f'<div class="warn">{e(i["pending"])}</div>')
    elif i.get('draft') is not None:
        if t.get('type') == 'linear_issue':
            h.append(f'<div class="mut">{"Update " + e(t.get("id")) if t.get("id") else "Create a new issue"} with: <code>{e(json.dumps(t.get("fields", {})))}</code>. Description:</div>')
        h.append(f'<textarea id="d-{iid}" rows="{min(12, 2 + i["draft"].count(chr(10)) + len(i["draft"]) // 90)}">{e(i["draft"])}</textarea>')
        h += [f'<div class="warn">⚠ {e(w)}</div>' for w in CD.check(i['draft'], CD.banned(CD.style_text()))]
        h.append(f'<button onclick="act(\'{iid}\',\'edit\',\'d-{iid}\',this)">Save edit</button>')
        if t.get('type') in ('linear_comment', 'linear_issue'):
            where = t.get('issue') or t.get('id') or 'Linear'
            h.append(f'<button class="pri" onclick="post(\'{iid}\',this)">Post to {e(where)}</button>')
        else:
            h.append(f'<button onclick="cp(\'d-{iid}\',this)">Copy</button>')
    if i.get('options') and not i.get('pending'):
        h.append('<div>' + ''.join(f'<button onclick="api(\'/api/action\',{{item:\'{iid}\',action:\'answer\',text:this.textContent}})">{e(o)}</button>'
                                   for o in i['options']) + '</div>')
        h.append(f'<input type="text" id="a-{iid}" placeholder="Or your own answer"><button onclick="act(\'{iid}\',\'answer\',\'a-{iid}\')">Answer</button>')
    if not i.get('pending'):
        h.append(f'<div><button onclick="act(\'{iid}\',\'resolve\')">Resolve</button>'
                 f'<input type="text" id="r-{iid}" placeholder="Reason to reject (it won\'t be suggested again)" style="width:60%">'
                 f'<button onclick="act(\'{iid}\',\'reject\',\'r-{iid}\')">Reject</button></div>')
    return ''.join(h) + '</div>'

def thread_html(card):
    ps = thread_posts(card)
    posts = ''.join(f'<div class="post {"agent" if who == "agent" else ""}"><div class="mut">{"agent" if who == "agent" else "you"} · {e(at)}</div>{e(txt)}</div>'
                    for who, at, txt in ps)
    c = e(card)
    return (f'{posts or "<p class=mut>No posts yet.</p>"}<textarea id="t-{c}" rows="2" placeholder="e.g. shorten the draft, drop step 2, add a sub-issue for X"></textarea>'
            f'<button onclick="api(\'/api/reply\',{{card:\'{c}\',text:val(\'t-{c}\'),now:true}})">Send now</button>'
            f'<button onclick="api(\'/api/reply\',{{card:\'{c}\',text:val(\'t-{c}\'),now:false}})">Save for next sync</button>')

def kind_of(m): return m.get('statusType') or STATUS_TYPE.get(m.get('status'), 'other')

def progress(m):
    subs = [x for x in m.get('subs') or [] if x.get('statusType') != 'canceled']
    return sum(x.get('statusType') == 'completed' for x in subs), len(subs)

def lead(m, items):
    """One sentence that says where the ticket stands."""
    done, n = progress(m)
    parts = [f'{len(items)} thing{"s" if len(items) != 1 else ""} need{"s" if len(items) == 1 else ""} you.'] if items else []
    parts.append(f'{done} of {n} sub-issues done.' if n else f'{m.get("status") or "No status"}, no sub-issues.')
    if m.get('next'): parts.append(f'Next: {m["next"]}.')
    return ' '.join(parts)

AM, NODE = SKILL / 'scripts' / 'am.mjs', shutil.which('node')

def how_page(mid):
    """Render tasks/<mid>.md with the vendored answer-me-with-html into pages/<mid>.html when the md is newer. None without node or a tasks file."""
    md, out = HOME / 'tasks' / f'{mid}.md', HOME / 'pages' / f'{mid}.html'
    if not (NODE and AM.exists() and md.exists()): return None
    if not out.exists() or out.stat().st_mtime < md.stat().st_mtime:
        out.parent.mkdir(exist_ok=True)
        try: subprocess.run([NODE, str(AM), 'render', str(md), '-o', str(out), '--no-open', '--theme', 'paper', '--mode', 'auto', '--style', 'off'],
                            capture_output=True, timeout=60)
        except (subprocess.TimeoutExpired, OSError): return None
    return out if out.exists() else None

AM_SEC = re.compile(r'<section class="am-panel[^"]*"[^>]*>(.*?)</section>', re.S)
AM_HEAD = re.compile(r'<header class="am-panel-head">.*?<h2[^>]*>(.*?)</h2>.*?</header>', re.S)
AM_BODY = re.compile(r'<div class="am-panel-body">(.*)', re.S)

def am_panels(path):
    """(css, [(title, body_html)]) from an am page: its panels become ours, its theme vars scoped to .am-root instead of html."""
    h = path.read_text()
    css = ''.join(re.findall(r'<style[^>]*>(.*?)</style>', h, re.S))
    css = re.sub(r'\bhtml(?=[\[\s,{.:])', '.am-root', css); css = re.sub(r'(?<![\w-])body(?=[\s,{.:])', '.am-root', css)
    out = []
    for sec in AM_SEC.findall(h):
        t, b = AM_HEAD.search(sec), AM_BODY.search(sec)
        if b: out.append((re.sub(r'<[^>]+>', '', t.group(1)).strip() if t else '', b.group(1).rsplit('</div>', 1)[0]))
    return css, out

def ticket_page(mid):
    st, items = view()
    ids = {x['id'] for x in st.get('masters') or []}
    m = next((x for x in st.get('masters') or [] if x['id'] == mid), None)
    if not m and mid != 'inbox': return None
    mine = [i for i in items.values() if i.get('status', 'open') == 'open' and (i.get('master') == mid if mid != 'inbox' else i.get('master') not in ids)]
    panels, am_css = [], ''
    if mid == 'inbox':
        head = '<h1>Inbox <span class="mut">no master yet</span></h1>'
        panels.append(X.panel('A', 'Where things stand', X.callout(f'{len(mine)} item{"s" if len(mine) != 1 else ""} waiting for a home.'), wide=True))
    else:
        pr = m.get('product') or {}
        head = f'<h1><a href="{e(m.get("url"))}">{e(m["id"])}</a> {e(m.get("title"))}</h1>'
        panels.append(X.panel('A', 'Where things stand', X.callout(lead(m, mine), 'warn' if mine else ''), meta=st_badge(m)))   # shares the row with B
        panels.append(X.panel('B', 'Goal', (f'<p>{e(m["goal"])}</p>' if m.get('goal') and not m['goal'].startswith('(') else '<p class="mut">Not read yet. The next sync reads the description and writes the goal here.</p>')
                              + X.kv([('Product ticket', f'<a href="{e(pr.get("url"))}">{e(pr.get("id"))}</a>' if pr.get('id') else '')])))
        try: md = (HOME / 'tasks' / f'{mid}.md').read_text()
        except FileNotFoundError: md = ''
        am_css, am = am_panels(pg) if (pg := how_page(mid)) else ('', [])
        if am:   # the tasks file's own panels, diagrams included, as native panels
            for title, body in am:
                panels.append(X.panel(chr(ord('A') + len(panels)), title or 'How (local)', f'<div class="am-root" data-theme="paper" data-mode="auto">{body}</div>',
                                      wide='<figure' in body or '<table' in body))   # diagrams and tables get the row; lists pack two per row
        else: panels.append(X.panel('C', 'How (local)', X.how(md), meta='steps, decisions, questions'))
        done, n = progress(m)
        if n: panels.append(X.panel(chr(ord('A') + len(panels)), 'Sub-issues', X.tree(m), meta=f'{done}/{n} done', wide=True))
    if mine: panels.append(X.panel(chr(ord('A') + len(panels)), 'Needs you', ''.join(item_html(i) for i in mine), meta=f'{len(mine)}', wide=True))
    panels.append(X.panel(chr(ord('A') + len(panels)), 'Thread', thread_html(mid), meta='tell the agent what to change', wide=True))
    return page(mid, f'<header><a href="/">← home</a><span style="margin-left:auto"></span><button onclick="theme()" title="light / dark">◐ theme</button></header>{head}<div class="sheet">{"".join(panels)}</div>', am_css)

def blocked(m):
    subs = [x for x in m.get('subs') or [] if x.get('statusType') not in ('completed', 'canceled')]
    return bool(subs) and all(x.get('blockedBy') for x in subs)

def row(m, items):
    done, n = progress(m)
    return (f'<tr><td><a href="{e(m.get("url"))}" title="open in Linear">{e(m["id"])}</a> <a class="t" href="/t/{e(m["id"])}">{e(m.get("title"))}</a></td>'
            f'<td>{st_badge(m)}{" <span class=chip>⛔ blocked</span>" if blocked(m) else ""}</td><td class="mut">{f"{done}/{n} sub-issues" if n else ""}</td>'
            + '<td class="warn">' + (f'<a href="/t/{e(m["id"])}#{e(items[0]["id"])}">{e(items[0].get("title"))}</a>' if items and items[0].get('kind') == 'work'
                                     else 'needs you: ' + e(items[0].get('title')) if items else e(m.get('next') or '')) + '</td></tr>')

def section(title, ms, by, note=''):
    return f'<section class="card"><h2>{e(title)} <span class="mut">{note or len(ms)}</span></h2><table>{"".join(row(m, by(m["id"])) for m in ms)}</table></section>' if ms else ''

def home(everything=False):
    st, items = view()
    c = config()
    all_open = [i for i in items.values() if i.get('status', 'open') == 'open']
    open_items = [i for i in all_open if i.get('kind') != 'work']   # work items are reviews: they go under Ready, not Needs you
    masters = st.get('masters') or []
    ids = {m['id'] for m in masters}
    by = lambda mid: [i for i in open_items if i.get('master') == mid]
    stray = [i for i in open_items if i.get('master') not in ids]
    synced = ts(st.get('synced_at', ''))
    run = f'running {e(RUNNING["name"])}' if RUNNING else f'{Q.qsize()} queued' if Q.qsize() else ''
    head = (f'<header><h1>voxer-ticketsmith</h1><span class="mut">synced {ago(synced) if synced else "never"} {run}</span>'
            f'<button onclick="api(\'/api/sync\',{{}},this)">Sync now</button><a href="/sessions">Sessions</a><button onclick="theme()" title="light / dark">◐ theme</button></header>')
    started = [m for m in masters if kind_of(m) == 'started']
    if not st: return page('ticketsmith', head + '<p class="lead">No sync yet. The first one starts within a minute; this page refreshes when it lands.</p>')
    active = [m for m in masters if kind_of(m) in ('started', 'unstarted')]
    work = {i['master']: i for i in all_open if i.get('kind') == 'work' and i.get('master') in ids}
    ready = [m for m in masters if m['id'] in work or m.get('status') == 'In Review']   # ready for review: a branch to look at, or Linear says so; any status
    summary = (f'{len(open_items)} thing{"s" if len(open_items) != 1 else ""} need{"s" if len(open_items) == 1 else ""} you. ' if open_items else 'Nothing needs you. ') \
              + f'{len(ready)} ready for review, {len(started)} in progress.'
    body = [head, f'<p class="lead">{summary}</p>']
    if open_items:
        urls = {m['id']: m.get('url') for m in masters}
        def needs_row(i):
            card = i.get('master') if i.get('master') in urls else 'inbox'
            idlink = f'<a href="{e(urls[card])}" title="open in Linear">{e(card)}</a>' if card != 'inbox' else '<span class="mut">inbox</span>'
            return (f'<li><div>{idlink} {e(i.get("title"))}' + (f'<div class="mut">{e(i.get("why"))}</div>' if i.get('why') else '')
                    + f'</div><a class="go" href="/t/{e(card)}#{e(i["id"])}">open →</a></li>')
        li = ''.join(needs_row(i) for i in open_items)
        body.append(f'<section class="card needs"><h2>Needs you</h2><ul class="rows">{li}</ul></section>')
    order = {'started': 0, 'unstarted': 1}
    rest_active = sorted((m for m in active if m not in ready), key=lambda m: (order.get(kind_of(m), 2), not blocked(m)))
    body.append(section('Ready for review', ready, lambda mid: [work[mid]] if mid in work else []))
    body.append(section('In progress / Todo / blocked', rest_active, by))
    rest = sorted((m for m in masters if m not in active and m not in ready), key=lambda m: {'triage': 0, 'backlog': 1}.get(kind_of(m), 2))
    if rest:
        body.append(f'<details class="card"{" open" if everything else ""}><summary>Everything else / backlog <span class="mut">{len(rest)}</span></summary>'
                    f'<table>{"".join(row(m, by(m["id"])) for m in rest)}</table></details>')
    ign = st.get('ignored') or [] if st.get('ignored_day') == time.strftime('%Y-%m-%d') else []
    if ign:
        body.append(f'<details class="card"><summary class="mut">Ignored today ({len(ign)})</summary><ul>'
                    + ''.join(f'<li><a href="{e(x.get("url"))}">{e(x.get("source"))}</a> {e(x.get("snippet"))}</li>' for x in ign) + '</ul></details>')
    return page('ticketsmith', ''.join(body))

# ---------- sessions (headless runs, resumable) ----------
def sessions_dir(): return Path.home() / '.claude/projects' / re.sub(r'[^A-Za-z0-9]', '-', str(HOME))

def session_title(f):
    for line in f.open(errors='ignore'):
        if '"custom-title"' in line:
            try: return json.loads(line).get('customTitle', '')
            except ValueError: pass
    return f.stem

def sessions_page():
    fs = sorted(sessions_dir().glob('*.jsonl'), key=lambda p: -p.stat().st_mtime)[:40]
    rows = ''.join(f'<tr><td><a href="/s/{e(f.stem)}">{e(session_title(f))}</a></td><td class="mut">{ago(f.stat().st_mtime)}</td>'
                   f'<td><code>cd {e(HOME)} &amp;&amp; claude --resume {e(f.stem)}</code></td></tr>' for f in fs)
    return page('sessions', f'<header><h1><a href="/">ticketsmith</a> · sessions</h1></header><table>{rows or "<tr><td class=mut>none yet</td></tr>"}</table>')

def transcript_page(sid):
    f = sessions_dir() / f'{sid}.jsonl'
    if not re.fullmatch(r'[0-9a-f-]{36}', sid) or not f.exists(): return None
    out = []
    for line in f.open(errors='ignore'):
        try: j = json.loads(line)
        except ValueError: continue
        if j.get('type') not in ('user', 'assistant'): continue
        c = j.get('message', {}).get('content')
        for b in [{'type': 'text', 'text': c}] if isinstance(c, str) else c or []:
            if not isinstance(b, dict): continue
            if b.get('type') == 'text' and b.get('text', '').strip():
                out.append(f'<div class="msg"><div class="mut">{"prompt" if j["type"] == "user" else "Claude"} · {e((j.get("timestamp") or "")[11:16])}</div>{e(b["text"])}</div>')
            elif b.get('type') == 'tool_use':
                out.append(f'<details><summary class="mut">⚙ {e(b.get("name"))}</summary><pre>{e(json.dumps(b.get("input", {}), indent=1)[:8000])}</pre></details>')
            elif b.get('type') == 'tool_result':
                r = b.get('content')
                r = r if isinstance(r, str) else '\n'.join(x.get('text', '') for x in r or [] if isinstance(x, dict))
                out.append(f'<details><summary class="mut">↳ result ({len(r)} chars)</summary><pre>{e(r[:8000])}</pre></details>')
    return page(session_title(f), f'<header><h1><a href="/sessions">sessions</a> · {e(session_title(f))}</h1></header>'
                f'<p><code>cd {e(HOME)} &amp;&amp; claude --resume {e(sid)}</code></p>{"".join(out)}')

def sig():
    parts = [str(RUNNING.get('name')), str(Q.qsize())]
    for n in ('state.json', 'inbox.jsonl', 'threads'):
        p = HOME / n
        parts.append(str(max([p.stat().st_mtime] + [x.stat().st_mtime for x in p.glob('*')] if p.is_dir() else [p.stat().st_mtime])) if p.exists() else '0')
    return '|'.join(parts)

# ---------- http ----------
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def send(self, code, body, ctype='text/html; charset=utf-8'):
        b = body.encode()
        self.send_response(code); self.send_header('Content-Type', ctype); self.send_header('Content-Length', str(len(b)))
        self.end_headers(); self.wfile.write(b)

    def do_GET(self):
        path = unquote(urlparse(self.path).path)
        if path == '/': return self.send(200, home())
        if path == '/sessions': return self.send(200, sessions_page())
        if path == '/all': return self.send(200, home(everything=True))
        if path.startswith('/t/') and CARD_RE.match(path[3:]) and (p := ticket_page(path[3:])): return self.send(200, p)
        if path == '/api/sig': return self.send(200, sig(), 'text/plain')
        if path.startswith('/s/') and (p := transcript_page(path[3:])): return self.send(200, p)
        if path.startswith('/p/') and PAGE_RE.match(path[3:]) and (f := HOME / 'pages' / path[3:]).is_file(): return self.send(200, f.read_text())
        self.send(404, 'not found', 'text/plain')

    def do_POST(self):
        if self.headers.get('X-Dash') != '1': return self.send(403, 'forbidden', 'text/plain')   # blocks cross-site form posts
        try: d = json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0))) or b'{}')
        except ValueError: return self.send(400, 'bad json', 'text/plain')
        path, text = urlparse(self.path).path, str(d.get('text') or '').strip()
        if path == '/api/sync': return self.send(200, enqueue('sync', 'sync'), 'text/plain')
        if path == '/api/action':
            item, action = str(d.get('item', '')), d.get('action')
            if action in ('post', 'answer') and not text: return self.send(400, 'empty text', 'text/plain')
            if not add_inbox(item, action, text): return self.send(400, 'unknown item or action', 'text/plain')
            if action == 'post': enqueue(f'post {item}', f'post {item}', write=True)
            return self.send(200, 'saved' if action == 'edit' else 'ok', 'text/plain')
        if path == '/api/reply':
            card = str(d.get('card', ''))
            if not CARD_RE.match(card) or not text: return self.send(400, 'bad card or empty text', 'text/plain')
            add_post(card, text)
            if (k := command_for(text)): return self.send(200, enqueue(f'{k["skill"]} {card}', f'{k["skill"]} {card}', custom=k), 'text/plain')
            return self.send(200, enqueue(f'reply {card}', f'reply {card}') if d.get('now') else 'saved for next sync', 'text/plain')
        self.send(404, 'not found', 'text/plain')

def serve():
    HOME.mkdir(parents=True, exist_ok=True)
    port = config()['port']
    for a in inbox():   # posts clicked before a crash or restart
        if a.get('action') == 'post': enqueue(f'post {a["item"]}', f'post {a["item"]}', write=True)
    for f in (worker, timer): threading.Thread(target=f, daemon=True).start()
    print(f'voxer-ticketsmith on http://127.0.0.1:{port}  (home {HOME})', flush=True)
    ThreadingHTTPServer(('127.0.0.1', port), Handler).serve_forever()

def test():
    global HOME
    HOME = Path(tempfile.mkdtemp())
    assert 'No sync yet' in home() and ticket_page('ENG-1') is None
    (HOME / 'state.json').write_text(json.dumps({
        'synced_at': now_iso(), 'ignored_day': time.strftime('%Y-%m-%d'), 'ignored': [{'source': 'Slack #random', 'snippet': 'thanks!', 'url': ''}],
        'masters': [{'id': 'ENG-1', 'title': 'Export', 'url': 'u', 'status': 'In Progress', 'goal': 'Users get their data',
                     'subs': [{'id': 'ENG-2', 'statusType': 'completed', 'status': 'Done'}, {'id': 'ENG-3', 'statusType': 'started', 'blockedBy': ['ENG-2']},
                              {'id': 'ENG-4', 'statusType': 'canceled'}]}],
        'items': [{'id': 'i-1', 'master': 'ENG-1', 'kind': 'reply', 'title': 'Patrick asks <b>', 'draft': 'old', 'status': 'open',
                   'target': {'type': 'linear_comment', 'issue': 'ENG-1'}},
                  {'id': 'i-2', 'master': None, 'kind': 'question', 'title': 'Which project?', 'options': ['A', 'B'], 'status': 'open'},
                  {'id': 'i-4', 'master': 'ENG-1', 'kind': 'reply', 'title': 'style', 'draft': 'Thanks! Let me know if this works.', 'status': 'open', 'target': {'type': 'copy'}},
                  {'id': 'i-3', 'master': 'ENG-1', 'kind': 'reply', 'title': 'done one', 'status': 'posted'}]}))
    st = json.loads((HOME / 'state.json').read_text())
    st['masters'] += [{'id': 'ENG-7', 'title': 'Someday', 'status': 'Backlog'}, {'id': 'ENG-8', 'title': 'Now', 'status': 'In Progress', 'next': 'write the test'},
                      {'id': 'ENG-11', 'title': 'Reviewing', 'status': 'In Review'}, {'id': 'ENG-12', 'title': 'Triaged work', 'status': 'Triage'},
                      {'id': 'ENG-9', 'title': 'Stuck', 'status': 'Todo', 'subs': [{'id': 'ENG-10', 'statusType': 'unstarted', 'blockedBy': ['ENG-2']}]}]
    st['items'] += [{'id': 'i-w', 'master': 'ENG-8', 'kind': 'work', 'title': 'ENG-8: added the test', 'status': 'open'},
                    {'id': 'i-w2', 'master': 'ENG-12', 'kind': 'work', 'title': 'ENG-12: branch', 'status': 'open'}]
    (HOME / 'state.json').write_text(json.dumps(st))
    h = home()
    assert h.index('Needs you') < h.index('Ready') < h.index('In progress / Todo / blocked') < h.index('Everything else'), 'four sections in order'
    ready = h[h.index('Ready for review'):h.index('In progress / Todo')]
    assert 'ENG-8' in ready and 'ENG-11' in ready and '#i-w">ENG-8: added the test' in ready and '>ENG-1</a>' not in ready and '>ENG-9</a>' not in ready, 'ready = work item or In Review'
    assert 'added the test' not in h[:h.index('Ready for review')], 'work items are not Needs you'
    assert '>ENG-12</a>' in ready and '>ENG-12</a>' not in h[h.index('Everything else'):], 'a Triage ticket with a work item is Ready, not backlog'
    assert '⛔ blocked' in h[h.index('In progress / Todo'):h.index('Everything else')] and 'ENG-7' in h[h.index('Everything else'):]
    assert 'Needs you' in h and 'Patrick asks &lt;b&gt;' in h and 'done one' not in h, h
    assert '3 things need you. 3 ready for review, 3 in progress.' in h and '/t/ENG-1' in h and '/t/inbox' in h
    assert '<textarea' not in h, 'home stays calm: no drafts inline'
    t = ticket_page('ENG-1')
    assert '1 of 2 sub-issues done' in t and '⛔ after ENG-2' in t and 'Post to ENG-1' in t and '2 things need you.' in t and t.count('class="panel') == 6, t
    assert '⚠ banned: &quot;Thanks&quot;' in t and '⚠ banned: &quot;Let me know if&quot;' in t, 'drafts are checked at render time'
    assert ticket_page('inbox') and 'Which project?' in ticket_page('inbox') and ticket_page('ENG-99') is None
    assert 'Sub-issues' not in ticket_page('ENG-8') and 'next sync reads' in ticket_page('ENG-8')
    (HOME / 'tasks').mkdir(); (HOME / 'tasks' / 'ENG-8.md').write_text('---\ntitle: ENG-8\n---\n## Steps\n1. [x] read\n\n## Flow\n```flow\nA -> B: x\n```\n')
    if NODE:
        t = ticket_page('ENG-8')
        assert '<iframe' not in t and 'class="am-root"' in t and '<svg' in t and (HOME / 'pages' / 'ENG-8.html').exists(), 'am panels inlined, not framed'
        assert '<b>Steps</b>' in t and '<b>Flow</b>' in t and 'html[data-theme' not in t and '.am-root[data-theme' in t, 'am panels become ours; theme vars scoped'
    else: assert 'class="done">read' in ticket_page('ENG-8')
    assert 'Ignored today (1)' in home(everything=True) and 'Everything else' in home(everything=True)
    assert not add_inbox('i-9', 'edit', 'x') and not add_inbox('i-1', 'delete')
    assert add_inbox('i-1', 'edit', 'new text') and '>new text</textarea>' in ticket_page('ENG-1')
    st = json.loads((HOME / 'state.json').read_text())
    st['items'][0]['page'] = 'ENG-1-review.html'; st['items'][2]['page'] = '../etc/passwd'
    (HOME / 'state.json').write_text(json.dumps(st))
    assert 'href="/p/ENG-1-review.html"' in ticket_page('ENG-1') and 'passwd' not in ticket_page('ENG-1'), 'page link only for safe names'
    add_inbox('i-2', 'resolve')
    assert '2 things need you.' in home()
    add_inbox('i-1', 'post', 'final')
    assert 'posting to Linear' in ticket_page('ENG-1')
    add_post('ENG-1', 'make it shorter')
    (HOME / 'threads' / 'ENG-1.md').open('a').write('## agent · 2026-10-10 10:00\nShortened it.\n\n')
    assert [w for w, _, _ in thread_posts('ENG-1')] == ['you', 'agent'] and 'Shortened it.' in ticket_page('ENG-1')
    assert CARD_RE.match('ENG-12') and CARD_RE.match('inbox') and not CARD_RE.match('../x')
    assert command_for('shorten the draft') is None
    (HOME / 'config.toml').write_text('[[commands]]\nmatch = "^work on (this|it)"\nskill = "my-worker"\ntools = ["Bash"]\ncwd = "~/x"\n')
    k = command_for('Work on this, please')
    assert k and k['skill'] == 'my-worker' and command_for('work: no') is None and config()['interval_min'] == 60
    st = json.loads((HOME / 'state.json').read_text())
    st['items'].append({'id': 'i-5', 'master': 'ENG-1', 'kind': 'result', 'title': 'ENG-3: did it', 'details': {'Where': 'a/b <x>', 'Checked': 'tests ok'}, 'command': 'cd /w && ls', 'status': 'open'})
    (HOME / 'state.json').write_text(json.dumps(st))
    assert 'a/b &lt;x&gt;' in ticket_page('ENG-1') and 'Copy command' in ticket_page('ENG-1') and '>cd /w &amp;&amp; ls</textarea>' in ticket_page('ENG-1')
    (HOME / 'state.json').write_text('{"half')
    assert 'ENG-8' in home(), 'half-written state.json must fall back to the last good copy'
    assert enqueue('sync', 'sync') == 'started' and enqueue('sync', 'sync') == 'already queued'
    print('ok')

if __name__ == '__main__':
    test() if sys.argv[1:] == ['--test'] else serve()
