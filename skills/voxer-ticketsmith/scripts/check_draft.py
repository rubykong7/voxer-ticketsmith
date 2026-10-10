#!/usr/bin/env python3
"""Check a draft against the style file: banned phrases, em dashes, bold, then a small STE pass (long sentences, passive, wordy).

Usage: check_draft.py <file|->   prints one warning per line, or "clean"; exit 1 on warnings.
       check_draft.py --test     self-check.
Style: $TICKETSMITH_HOME/style.md if present, else the skill's style.md ("## Never write" bullets).
"""
import os, re, sys
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent
HOME = Path(os.environ.get('TICKETSMITH_HOME', '~/.voxer-ticketsmith')).expanduser()

def banned(style_text):
    m = re.search(r'^## Never write\s*$(.*?)(?=^## |\Z)', style_text, re.M | re.S)
    return [b.strip().strip('`"') for b in re.findall(r'^- (.+)$', m.group(1), re.M)] if m else []

def style_text():
    p = HOME / 'style.md'
    return (p if p.exists() else SKILL / 'style.md').read_text()

WORDY = {'prior to': 'before', 'utilize': 'use', 'in order to': 'to', 'commence': 'start', 'at this point in time': 'now',
         'in the event that': 'if', 'with regard to': 'about', 'subsequent to': 'after', 'facilitate': 'help', 'leverage': 'use',
         'it should be noted that': '(drop it)', 'please be advised': '(drop it)', 'as per': 'per', 'going forward': '(drop it)'}
PASSIVE = re.compile(r'\b(?:is|are|was|were|be|been|being)\s+(?:\w+ly\s+)?(\w+(?:ed|en|own|ought|uilt|ade|aid|ent|unk|ung|one))\b', re.I)
NOT_PASSIVE = {'need', 'needed', 'used', 'supposed', 'allowed', 'based', 'related', 'interested', 'done', 'gone', 'open', 'own', 'even', 'given'}

def ste(text):
    """Simplified Technical English subset: long sentences, passive voice, wordy phrases. Idea from answer-me-with-html's STE check."""
    out = []
    for n, sent in enumerate(re.split(r'(?<=[.!?])\s+|\n+', text.strip()), 1):
        words = len(sent.split())
        if words > 25: out.append(f'S{n} sentence has {words} words (max 25): "{sent[:40]}…"')
        for m in PASSIVE.finditer(sent):
            if m.group(1).lower() not in NOT_PASSIVE: out.append(f'S{n} passive: "{m.group(0)}" → say who does it')
        low = sent.lower()
        out += [f'S{n} wordy: "{w}" → {r}' for w, r in WORDY.items() if w in low]
    return out

def check(text, phrases):
    out = [f'banned: "{p}"' for p in phrases if p.lower() in text.lower()]
    if '—' in text: out.append('banned: em dash')
    if '**' in text: out.append('banned: bold')
    return out + ste(text)

def test():
    phrases = banned('# x\n## Never write\n\nnote\n\n- Thanks\n- `Let me know if`\n## Other\n- not banned\n')
    assert phrases == ['Thanks', 'Let me know if'], phrases
    assert check('Ship it. Retention stays as is.', phrases) == []
    w = check('Thanks! Let me know if this — works. **Bold**', phrases)
    assert w == ['banned: "Thanks"', 'banned: "Let me know if"', 'banned: em dash', 'banned: bold'], w
    assert banned((SKILL / 'style.md').read_text()), 'skill style.md has no Never write list'
    w = ste('The export was implemented prior to the migration and it is affected by the retention policy that was set up in the previous sprint by the data team last year.')
    assert any('passive' in x for x in w) and any('wordy' in x for x in w) and any('words (max 25)' in x for x in w), w
    assert ste('Keep the 15-day expiry. The old exports are done and need no change.') == []
    print('ok')

if __name__ == '__main__':
    if sys.argv[1:] == ['--test']: test(); sys.exit()
    if len(sys.argv) != 2: sys.exit(__doc__)
    text = sys.stdin.read() if sys.argv[1] == '-' else Path(sys.argv[1]).read_text()
    warnings = check(text, banned(style_text()))
    print('\n'.join(warnings) or 'clean')
    sys.exit(1 if warnings else 0)
