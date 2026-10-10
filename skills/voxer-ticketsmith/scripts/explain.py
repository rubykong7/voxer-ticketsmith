"""Explain-page pieces for the ticket page: a sheet of lettered panels, paper theme, light and dark.

The layout idea (one screen, lettered panels, verdict first, tree and callout components) is borrowed from
answer-me-with-html by QingYunA (MIT, https://github.com/QingYunA/answer-me-with-html), re-done here in
plain Python so the dashboard needs no node CLI.
"""
import html, re

e = lambda s: html.escape(str(s if s is not None else ''), quote=True)

CSS = """
:root{--font-sans:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Hiragino Sans GB",Roboto,"Helvetica Neue",Arial,sans-serif;
--font-mono:ui-monospace,SFMono-Regular,"JetBrains Mono",Menlo,Consolas,monospace;
--font-serif:"Iowan Old Style","Palatino Linotype",Palatino,Georgia,"Songti SC","Noto Serif CJK SC",serif;--radius:6px;
--bg:#f5f2ea;--paper:#fdfbf6;--ink:#1f1c17;--ink-2:#57514a;--ink-3:#8c867b;--line:#cbc3b4;--line-2:#e5dfd3;--fill:#f3eee4;
--accent:#1f5fbf;--accent-bg:#e8eef9;--ok:#2e6a3b;--ok-bg:#e4efe5;--err:#a3251b;--err-bg:#f7e3e0;--warn:#7f5300;--warn-bg:#f6ecd6;--head-bg:#1f1c17;--head-fg:#fdfbf6}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#15130f;--paper:#1c1a15;--ink:#ebe5d8;--ink-2:#b5ad9e;--ink-3:#7b7467;--line:#4a443a;--line-2:#2d2a24;--fill:#242119;
--accent:#8ab4ff;--accent-bg:#1f2a3d;--ok:#8cc79a;--ok-bg:#1c3122;--err:#f0928a;--err-bg:#3a1d1a;--warn:#e3b866;--warn-bg:#352a13;--head-bg:#ebe5d8;--head-fg:#15130f}}
:root[data-theme=dark]{--bg:#15130f;--paper:#1c1a15;--ink:#ebe5d8;--ink-2:#b5ad9e;--ink-3:#7b7467;--line:#4a443a;--line-2:#2d2a24;--fill:#242119;
--accent:#8ab4ff;--accent-bg:#1f2a3d;--ok:#8cc79a;--ok-bg:#1c3122;--err:#f0928a;--err-bg:#3a1d1a;--warn:#e3b866;--warn-bg:#352a13;--head-bg:#ebe5d8;--head-fg:#15130f}
.sheet{display:grid;grid-template-columns:1fr 2fr;gap:16px;align-items:start}@media (max-width:720px){.sheet{grid-template-columns:1fr}}
.panel{background:var(--paper);border:1px solid var(--line);border-radius:var(--radius);overflow:hidden;min-width:0}
.panel.wide{grid-column:1/-1}.panel .ph{display:flex;align-items:stretch;border-bottom:1px solid var(--line);min-height:34px}
.panel .ph .id{display:flex;align-items:center;justify-content:center;min-width:34px;padding:0 8px;background:var(--head-bg);color:var(--head-fg);font-weight:600;font-size:14px}
.panel .ph b{flex:1;display:flex;align-items:center;padding:7px 12px;font:600 15px var(--font-sans)}
.panel .ph .meta{align-self:center;padding:0 12px;font-size:13px;color:var(--ink-2);text-align:right}
.panel .pb{padding:14px 16px 16px}.panel .pb>*+*{margin-top:12px}
.callout{border:1px solid var(--line-2);border-left:3px solid var(--accent);background:var(--accent-bg);padding:10px 14px;border-radius:var(--radius);font:16px/1.6 var(--font-sans)}
.callout.c-warn{border-left-color:var(--warn);background:var(--warn-bg)}.callout.c-ok{border-left-color:var(--ok);background:var(--ok-bg)}
.kv{display:grid;grid-template-columns:max-content 1fr;gap:4px 14px;margin:0}.kv dt{color:var(--ink-2)}.kv dd{margin:0}
.tree{list-style:none;margin:0;padding:0;font-size:14px}.tree li+li{border-top:1px solid var(--line-2)}
.node{display:flex;gap:10px;align-items:baseline;padding:7px 10px;border-left:3px solid var(--ink-3)}
.node.done{border-left-color:var(--ok)}.node.started{border-left-color:var(--accent)}.node.blocked{border-left-color:var(--err)}
.node a{white-space:nowrap;font:13px var(--font-mono);font-weight:600}.node .t{flex:1;min-width:12em}.node.done .t{color:var(--ink-3);text-decoration:line-through}
.node .who{color:var(--ink-2);font-size:13px;white-space:nowrap}.node .chip{font-size:11px;color:var(--err);white-space:nowrap}
.how{font:14px/1.7 var(--font-sans)}.how h3{font-size:12px;font-weight:600;margin:12px 0 4px;color:var(--ink-2);text-transform:uppercase;letter-spacing:.06em}.how h3:first-child{margin-top:0}
.how ul,.how ol{margin:0;padding-left:20px}.how li{margin:2px 0}.how li.done{color:var(--ink-3);text-decoration:line-through}.how p{margin:0}
"""

def panel(letter, title, body, meta='', wide=False):
    return (f'<section class="panel{" wide" if wide else ""}"><div class="ph"><span class="id">{letter}</span><b>{e(title)}</b>'
            + (f'<span class="meta">{meta}</span>' if meta else '') + f'</div><div class="pb">{body}</div></section>')

def callout(text, kind=''):
    return f'<div class="callout{" c-" + kind if kind else ""}">{e(text)}</div>'   # c- prefix: .warn is the small warning line elsewhere

def kv(pairs):
    return '<dl class="kv">' + ''.join(f'<dt>{e(k)}</dt><dd>{v}</dd>' for k, v in pairs if v) + '</dl>'

def node(s):
    cls = 'done' if s.get('statusType') == 'completed' else 'blocked' if s.get('blockedBy') else 'started' if s.get('statusType') == 'started' else ''
    return (f'<div class="node {cls}"><a href="{e(s.get("url"))}">{e(s.get("id"))}</a><span class="t">{e(s.get("title"))}</span>'
            + (f'<span class="chip">⛔ after {e(", ".join(s["blockedBy"]))}</span>' if s.get('blockedBy') else '')
            + (f'<span class="who">{e(s["assignee"])}</span>' if s.get('assignee') else '')
            + f'<span class="st {e(s.get("statusType") or "")}">{e(s.get("status"))}</span></div>')

def tree(m):
    """One line per sub-issue, in Linear order; colour says done / started / blocked."""
    subs = [s for s in m.get('subs') or [] if s.get('statusType') != 'canceled']
    return '<ul class="tree">' + ''.join(f'<li>{node(s)}</li>' for s in subs) + '</ul>' if subs else '<p class="mut">No sub-issues.</p>'

def how(md):
    """tasks/<master>.md (## Steps / Decisions / Open questions / Sources with - or 1. lists) → html. Lines starting [x] are done."""
    out, lst = [], None
    def close():
        nonlocal lst
        if lst: out.append(f'</{lst}>'); lst = None
    for raw in md.splitlines():
        line = raw.strip()
        if not line: continue
        if line.startswith('#'):
            close(); out.append(f'<h3>{e(line.lstrip("#").strip())}</h3>'); continue
        m = re.match(r'^(?:[-*]|\d+[.)])\s+(\[[ xX]\]\s*)?(.*)$', line)
        if m:
            tag = 'ol' if line[0].isdigit() else 'ul'
            if lst != tag: close(); out.append(f'<{tag}>'); lst = tag
            done = bool(m.group(1) and m.group(1).strip().lower() == '[x]')
            out.append(f'<li class="{"done" if done else ""}">{inline(m.group(2))}</li>'); continue
        close(); out.append(f'<p>{inline(line)}</p>')
    close()
    return f'<div class="how">{"".join(out)}</div>' if out else '<p class="mut">Nothing recorded yet. Steps and decisions land here as the agent works the ticket.</p>'

def inline(t):
    t = e(t)
    t = re.sub(r'`([^`]+)`', r'<code>\1</code>', t)
    t = re.sub(r'\[([^\]]+)\]\((https?://[^)\s]+)\)', r'<a href="\2">\1</a>', t)
    return re.sub(r'(?<!["=])(https?://[^\s<]+)', r'<a href="\1">\1</a>', t)

def test():
    m = {'id': 'ENG-1', 'title': 'Export', 'url': 'u', 'status': 'Todo',
         'subs': [{'id': 'ENG-2', 'title': 'A', 'statusType': 'completed', 'status': 'Done', 'assignee': 'Ruby', 'mine': True},
                  {'id': 'ENG-3', 'title': 'B <x>', 'statusType': 'unstarted', 'status': 'Todo', 'blockedBy': ['ENG-2']},
                  {'id': 'ENG-4', 'title': 'gone', 'statusType': 'canceled'}]}
    t = tree(m)
    assert 'class="node done"' in t and 'blocked' in t and '⛔ after ENG-2' in t and 'B &lt;x&gt;' in t and 'gone' not in t and 'Export' not in t, t
    assert 'No sub-issues' in tree({'id': 'ENG-9'})
    h = how('## Steps\n1. [x] read code\n2. write test\n\n## Decisions\n- keep 15 days, see https://x.y/z\n')
    assert '<ol>' in h and 'class="done">read code' in h and '<h3>Decisions</h3>' in h and '<a href="https://x.y/z">' in h, h
    assert 'Nothing recorded' in how('')
    assert panel('A', 'T', 'b', meta='m', wide=True).startswith('<section class="panel wide">')
    print('ok')

if __name__ == '__main__': test()
