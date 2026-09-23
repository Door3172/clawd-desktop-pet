#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Claude Pet desktop pet: Clawd (the Claude Code mascot) wanders along the bottom of your screen.
Two skins: pixel sprites and a hand-drawn chibi.

The window technique (borderless + chroma-key transparency + always on top) is based on Mochi Desktop Pet
(MIT, https://github.com/m18023318493-sys/mochi-desktop-pet).
The chibi Clawd drawing and animation system are original; the pixel skin uses sprites from
shigure0110/clawd-pet (MIT, see assets/LICENSE.clawd-pet).

Usage:
  pythonw pet_window.py              start the pet
  python  pet_window.py --gallery    preview all poses (debug)
  python  pet_window.py --force jump start and force an animation (debug)
"""
import ctypes
import json
import math
import os
import random
import sys
import time
import tkinter as tk
from tkinter import simpledialog

DIR = os.environ.get('CLAUDE_PET_DIR') or os.path.join(os.path.expanduser('~'), '.claude', 'pet')
STATE = os.path.join(DIR, 'state.json')
PREFS = os.path.join(DIR, 'prefs.json')
QUIT = os.path.join(DIR, 'quit')
ALIVE = os.path.join(DIR, 'alive')         # heartbeat for /pet doctor
LOG = os.path.join(DIR, 'desktop.log')
HERE = os.path.dirname(os.path.abspath(__file__))

CHROMA = '#010203'
LW, LH = 280, 240          # window size in logical units
GROUND = LH - 10           # ground line inside the window
TICK_MS = 33
FONT = 'Microsoft JhengHei UI'

HUNGER_DECAY_PER_HOUR = 4
MOOD_DECAY_PER_HOUR = 2

SCHEMES = {
    'orange': dict(label='Orange', base='#D97757', hi='#E9A184', line='#8E4128', cheek='#E88F73',
                   blush='#FF8FA0', eye='#2A1A16'),
    'blue': dict(label='Blue', base='#6C9BE0', hi='#9CBDF0', line='#2F4F8A', cheek='#8FB2EE',
                 blush='#FF9DB4', eye='#1B2438'),
    'green': dict(label='Green', base='#6DBB8A', hi='#9DD8B0', line='#2E6B47', cheek='#88CDA0',
                  blush='#FF9DA5', eye='#17281F'),
    'purple': dict(label='Purple', base='#A985D8', hi='#C6AAEE', line='#5A3A8A', cheek='#BC9AE6',
                   blush='#FF9DC0', eye='#251A38'),
}

# ---------------------------------------------------------------- helpers
def E(a):
    return math.radians(a)


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def rnd(i):
    """Reproducible pseudo-random number in [0,1)"""
    return (math.sin(i * 78.233 + 1.7) * 43758.5453) % 1.0


def rot_pts(pts, piv, deg):
    c, s = math.cos(E(deg)), math.sin(E(deg))
    out = []
    for x, y in pts:
        dx, dy = x - piv[0], y - piv[1]
        out.append((piv[0] + dx * c - dy * s, piv[1] + dx * s + dy * c))
    return out


def log(msg):
    try:
        os.makedirs(DIR, exist_ok=True)
        with open(LOG, 'a', encoding='utf-8') as f:
            f.write(time.strftime('%H:%M:%S ') + msg + '\n')
    except Exception:
        pass


# ---------------------------------------------------------------- state file (shared with pet.js)
def now_ms():
    return int(time.time() * 1000)


def write_json(path, obj):
    os.makedirs(DIR, exist_ok=True)
    tmp = '%s.tmp%d' % (path, os.getpid())
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def load_state():
    try:
        with open(STATE, encoding='utf-8') as f:
            st = json.load(f)
    except Exception:
        st = {}
    n = now_ms()
    st.setdefault('name', 'Clawd')
    st.setdefault('color', 'orange')
    st.setdefault('born', n)
    st.setdefault('xp', 0)
    st.setdefault('hunger', 80)
    st.setdefault('mood', 80)
    st.setdefault('lastTick', n)
    st.setdefault('fed', 0)
    st.setdefault('played', 0)
    st.setdefault('activity', {})
    st.setdefault('accessory', 'none')
    st.setdefault('timer', None)
    if not isinstance(st.get('stats'), dict):
        st['stats'] = {}
    if not isinstance(st.get('achievements'), dict):
        st['achievements'] = {}
    if st['color'] not in SCHEMES:
        st['color'] = 'orange'
    return st


# ---------------------------------------------------------------- achievements (shared with pet.js via achievements.json)
def load_achievements():
    try:
        with open(os.path.join(HERE, 'achievements.json'), encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return []


ACHIEVEMENTS = load_achievements()


def bump(st, key, n=1):
    st['stats'][key] = st['stats'].get(key, 0) + n


def stat_of(st, key):
    if key == 'level':
        return level_of(st['xp'])
    if key in ('fed', 'played'):
        return st.get(key, 0)
    return st['stats'].get(key, 0)


def check_achievements(st):
    got = st['achievements']
    new = [a for a in ACHIEVEMENTS if a['id'] not in got and stat_of(st, a['stat']) >= a['goal']]
    for a in new:
        got[a['id']] = now_ms()
    if new:
        st['activity']['achieveAt'] = now_ms()
        st['activity']['achieveIds'] = [a['id'] for a in new]
    return new


def today_stats(st):
    t = st['stats'].get('today') or {}
    return t if t.get('date') == time.strftime('%Y-%m-%d') else {}


# ---------------------------------------------------------------- i18n (strings shared with pet.js via lang.json)
def _load_strings():
    try:
        with open(os.path.join(HERE, 'lang.json'), encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {'en': {}}


STRINGS = _load_strings()
LANG = 'en'


def detect_lang():
    try:
        if os.name == 'nt' and ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0x3FF == 0x04:
            return 'zh-TW'
    except Exception:
        pass
    try:
        import locale
        name = (locale.getlocale()[0] or '').lower()
    except Exception:
        name = ''
    return 'zh-TW' if name.startswith(('zh', 'chinese')) else 'en'


def set_lang(pref):
    global LANG
    LANG = pref if pref in STRINGS else detect_lang()


def T(key, **kw):
    """Look up a UI string in the current language (falls back to English, then the key)."""
    s = STRINGS.get(LANG, {}).get(key)
    if s is None:
        s = STRINGS.get('en', {}).get(key, key)
    return s.format(**kw) if kw and isinstance(s, str) else s


def loc(v):
    """Pick the current language from a {lang: text} dict (plain strings pass through)."""
    return v if isinstance(v, str) else v.get(LANG) or v.get('en', '')


# The tool Claude is using -> (category, label)
def tool_info(name):
    if not name:
        return 'think', T('tool.think')
    if name.startswith('mcp__'):
        return 'web', T('tool.mcp')
    table = {'Read': ('read', 'read'), 'Edit': ('edit', 'edit'), 'MultiEdit': ('edit', 'edit'),
             'NotebookEdit': ('edit', 'notebook'), 'Write': ('edit', 'write'), 'Bash': ('bash', 'bash'),
             'PowerShell': ('bash', 'bash'), 'BashOutput': ('bash', 'output'), 'Grep': ('search', 'grep'),
             'Glob': ('search', 'glob'), 'LS': ('search', 'glob'), 'WebFetch': ('web', 'fetch'),
             'WebSearch': ('web', 'websearch'), 'Task': ('agent', 'agent'), 'Agent': ('agent', 'agent'),
             'TodoWrite': ('edit', 'todo'), 'Skill': ('think', 'skill')}
    if name in table:
        cat, key = table[name]
        return cat, T('tool.' + key)
    return 'think', name[:12]


def fmt_clock(secs):
    secs = max(0, int(secs))
    if secs >= 3600:
        return '%d:%02d:%02d' % (secs // 3600, secs // 60 % 60, secs % 60)
    return '%d:%02d' % (secs // 60, secs % 60)


def level_of(xp):
    return int(math.sqrt(max(0, xp) / 10)) + 1


def tick_state(st):
    n = now_ms()
    hours = max(0.0, (n - st['lastTick']) / 3600000.0)
    st['hunger'] = clamp(st['hunger'] - hours * HUNGER_DECAY_PER_HOUR, 0, 100)
    st['mood'] = clamp(st['mood'] - hours * MOOD_DECAY_PER_HOUR, 0, 100)
    st['lastTick'] = n


def add_xp(st, n):
    before = level_of(st['xp'])
    st['xp'] += n
    after = level_of(st['xp'])
    if after > before:
        st['activity']['levelUpAt'] = now_ms()
        st['activity']['levelUpTo'] = after


def load_prefs():
    try:
        with open(PREFS, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


# ---------------------------------------------------------------- drawing: coordinate transforms
class Painter:
    """Converts character-local coordinates (origin = between the feet, y down) to canvas coordinates."""

    def __init__(self, cv, S):
        self.cv, self.S = cv, S
        self.tf = self.b
        self.u = 1.0
        self.set_body(0, 0, 1, 1, 0, 0)
        self.set_head(0, 0, 0)

    def set_body(self, ox, oy, sx, sy, rot, piv=0.0):
        self.ox, self.oy, self.sx, self.sy, self.piv = ox, oy, sx, sy, piv
        self.rc, self.rs = math.cos(E(rot)), math.sin(E(rot))

    def set_head(self, hx, hy, tilt):
        self.hx, self.hy = hx, hy
        self.hc, self.hs = math.cos(E(tilt)), math.sin(E(tilt))

    @property
    def k(self):
        return self.S * (abs(self.sx) + abs(self.sy)) / 2.0

    def b(self, x, y):
        x *= self.sx * self.u
        y = y * self.sy * self.u - self.piv
        rx = x * self.rc - y * self.rs
        ry = x * self.rs + y * self.rc + self.piv
        return ((self.ox + rx) * self.S, (self.oy + ry) * self.S)

    def h(self, x, y):
        # The head only takes the body's horizontal scale; sy is cancelled so the head stays round when squashed
        dx, dy = x, y + 48.0
        x2 = dx * self.hc - dy * self.hs + self.hx
        y2 = -48.0 + (dx * self.hs + dy * self.hc + self.hy) / self.sy
        return self.b(x2, y2)

    def _flat(self, pts):
        flat = []
        for x, y in pts:
            flat.extend(self.tf(x, y))
        return flat

    def poly(self, pts, fill='', outline='', width=0):
        self.cv.create_polygon(*self._flat(pts), fill=fill, outline=outline,
                               width=max(1, round(width * self.k)) if outline else 0)

    def ell(self, cx, cy, rx, ry, fill='', outline='', width=0, n=28):
        pts = [(cx + rx * math.cos(2 * math.pi * i / n), cy + ry * math.sin(2 * math.pi * i / n))
               for i in range(n)]
        self.poly(pts, fill, outline, width)

    def line(self, pts, color, width, smooth=False):
        self.cv.create_line(*self._flat(pts), fill=color, width=max(1, round(width * self.k)),
                            capstyle='round', joinstyle='round', smooth=smooth)

    # ---- untransformed canvas-space drawing (props, effects)
    def cpoly(self, pts, fill='', outline='', width=0, smooth=False):
        flat = []
        for x, y in pts:
            flat.extend((x * self.S, y * self.S))
        self.cv.create_polygon(*flat, fill=fill, outline=outline, smooth=smooth,
                               width=max(1, round(width * self.S)) if outline else 0)

    def cell(self, cx, cy, rx, ry, fill='', outline='', width=0, n=24):
        self.cpoly([(cx + rx * math.cos(2 * math.pi * i / n), cy + ry * math.sin(2 * math.pi * i / n))
                    for i in range(n)], fill, outline, width)

    def cline(self, pts, color, width, smooth=False):
        flat = []
        for x, y in pts:
            flat.extend((x * self.S, y * self.S))
        self.cv.create_line(*flat, fill=color, width=max(1, round(width * self.S)),
                            capstyle='round', joinstyle='round', smooth=smooth)

    def ctext(self, x, y, s, size, color, bold=False, italic=False):
        style = ' '.join(w for w, on in (('bold', bold), ('italic', italic)) if on)
        return self.cv.create_text(x * self.S, y * self.S, text=s, fill=color,
                                   font=(FONT, -max(6, int(size * self.S)), style) if style
                                   else (FONT, -max(6, int(size * self.S))))


# ---------------------------------------------------------------- drawing: Clawd
def heart_pts(cx, cy, size):
    pts = []
    for i in range(24):
        t = 2 * math.pi * i / 24
        x = 16 * math.sin(t) ** 3
        y = -(13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t))
        pts.append((cx + x * size / 16.0, cy + y * size / 16.0))
    return pts


def star_pts(cx, cy, r):
    return [(cx, cy - r), (cx + r * 0.28, cy - r * 0.28), (cx + r, cy), (cx + r * 0.28, cy + r * 0.28),
            (cx, cy + r), (cx - r * 0.28, cy + r * 0.28), (cx - r, cy), (cx - r * 0.28, cy - r * 0.28)]


def rrect(x0, y0, x1, y1, rt, rb, n=7):
    """Rounded-rectangle vertices; rt = top corner radius, rb = bottom corner radius."""
    pts = []

    def arc(cx, cy, r, a0, a1):
        for i in range(n + 1):
            a = math.radians(a0 + (a1 - a0) * i / n)
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    arc(x1 - rt, y0 + rt, rt, -90, 0)
    arc(x1 - rb, y1 - rb, rb, 0, 90)
    arc(x0 + rb, y1 - rb, rb, 90, 180)
    arc(x0 + rt, y0 + rt, rt, 180, 270)
    return pts


def draw_eye(P, cx, cy, kind, look, C, side):
    ink = C['eye']
    lx, ly = look[0] * 2.4, look[1] * 2.0
    if kind in ('open', 'wide', 'sad', 'half'):
        rx, ry = (6.4, 10.4) if kind == 'wide' else (5.4, 8.8)
        P.poly(rrect(cx - rx, cy - ry, cx + rx, cy + ry, rx, rx), ink)
        hx, hy = cx + lx * 0.6, cy + ly * 0.6
        P.ell(hx - 1.7, hy - 3.8, 2.2, 2.5, '#FFFFFF')
        P.ell(hx + 1.8, hy + 3.6, 1.0, 1.0, '#FFFFFF')
        if kind == 'sad':
            P.line([(cx + side * 7, cy - 10), (cx - side * 5, cy - 15)], ink, 1.9)
        if kind == 'half':
            P.poly(rrect(cx - 8, cy - 12, cx + 8, cy - 1, 1, 1), C['base'])
            P.line([(cx - 6, cy - 1), (cx + 6, cy - 1)], ink, 2.4)
    elif kind == 'closed':
        P.line([(cx - 6.5, cy - 1), (cx - 3, cy + 2.6), (cx + 3, cy + 2.6), (cx + 6.5, cy - 1)], ink, 2.4, True)
    elif kind == 'happy':
        P.line([(cx - 6.5, cy + 3), (cx - 3, cy - 2.8), (cx + 3, cy - 2.8), (cx + 6.5, cy + 3)], ink, 2.6, True)
    elif kind == 'shut':
        P.line([(cx - 6, cy), (cx + 6, cy)], ink, 2.4)
    elif kind == 'dizzy':
        pts = []
        for i in range(26):
            a = i * 0.5
            r = 0.4 + i * 0.28
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
        P.line(pts, ink, 1.7, True)
    elif kind == 'heart':
        P.poly(heart_pts(cx, cy, 9), '#FF5C7E')
    elif kind == 'angry':
        P.poly(rrect(cx - 5, cy - 6, cx + 5, cy + 7, 5, 5), ink)
        P.line([(cx + side * 8, cy - 15), (cx - side * 5, cy - 9)], ink, 2.4)


def draw_shadow(P, ox, sh, sx, lift, half):
    S = P.S
    sh = sh * max(0.35, 1 - lift / 150.0)
    if sh <= 0.01:
        return
    P.cv.create_oval((ox - half * sh * abs(sx)) * S, (GROUND - 5 * sh) * S,
                     (ox + half * sh * abs(sx)) * S, (GROUND + 5 * sh) * S,
                     fill='#000000', outline='', stipple='gray25')


def draw_arms(P, po, C):
    L = po['armlen']
    for s, a in ((-1, po['armL']), (1, po['armR'])):
        x0, y0 = s * 33, -40
        x1 = x0 + s * math.cos(E(a)) * L
        y1 = y0 - math.sin(E(a)) * L
        P.line([(x0, y0), (x1, y1)], C['line'], 15.5)
        P.line([(x0, y0), (x1, y1)], C['base'], 12)


def draw_clawd(P, po, C, d, t):
    """Chibi Clawd: round orange body, two big eyes, two little arms, four short legs."""
    LN, base = C['line'], C['base']
    sx, sy = po['sx'], po['sy']
    ox = LW / 2 + po['ox']
    P.u = 1.15
    draw_shadow(P, ox, po['shadow'], sx, po['lift'], 44)

    P.set_body(ox, GROUND - po['lift'], sx, sy, po['rot'], po['piv'])
    P.tf = P.b

    for x, (dx, dy) in zip((-26, -10, 10, 26), po['legs']):
        P.poly(rrect(x - 5.5 + dx, -18 + dy, x + 5.5 + dx, dy, 4, 5), base, LN, 1.8)
    if not po['arms_front']:
        draw_arms(P, po, C)

    P.poly(rrect(-36, -72, 36, -13, 20, 13), base, LN, 2)
    P.ell(-19, -61, 12, 5.5, C['hi'])
    strong = po['blush'] > 0.3
    for s in (-1, 1):
        P.ell(s * 27, -34, 7 if strong else 5.5, 4.2 if strong else 3.2, C['blush'] if strong else C['cheek'])
    if po['arms_front']:
        draw_arms(P, po, C)

    for s in (-1, 1):
        draw_eye(P, s * 15, -47, po['eyes'], po['look'], C, s)
    ink = C['eye']
    m, mo = po['mouth'], po['mopen']
    if m == 'smile':
        P.line([(-5, -34), (0, -30.5), (5, -34)], ink, 1.9, True)
    elif m == 'frown':
        P.line([(-5, -30.5), (0, -34), (5, -30.5)], ink, 1.9, True)
    elif m == 'flat':
        P.line([(-4, -32), (4, -32)], ink, 1.9)
    elif m == 'o':
        P.ell(0, -32, 3.2, 3.8, '#7A2632', ink, 1.2)
    elif m == 'pout':
        P.line([(-6, -32), (-2.5, -34.5), (1, -31.5), (5, -34)], ink, 1.9, True)
    elif m == 'open':
        ry = 1.8 + 6.5 * mo
        P.ell(0, -33 + ry * 0.35, 6, ry, '#7A2632', ink, 1.4)
        if mo > 0.4:
            P.ell(0, -33 + ry * 0.9, 3.6, ry * 0.4, '#F07A8A')
    if po['glasses']:
        for s in (-1, 1):
            P.ell(s * 15, -47, 11.5, 11.5, '', '#2A2A33', 2.2)
        P.line([(-3.5, -47), (3.5, -47)], '#2A2A33', 2)

    acc = po.get('acc')
    if acc and acc != 'none':
        draw_accessory(Pen(P, lambda x, y: P.b(x, y - 72), P.k), acc, t)

    for pr in po['props']:
        if pr[0] == 'book':
            draw_book(P, ox, t)
        elif pr[0] == 'laptop':
            draw_laptop(P, ox, pr[1], t)
        elif pr[0] == 'laptop_paws':
            draw_typing_paws(P, ox, pr[1], t, C)
        elif pr[0] == 'yarn':
            draw_yarn(P, ox + pr[1], GROUND - 9 - pr[2], 9, pr[3])
        elif pr[0] == 'bowl':
            draw_bowl(P, ox + pr[1], pr[2])
    draw_fx(P, po, C, ox, d, t)


def draw_laptop(P, ox, typing, t):
    g = GROUND
    P.cpoly([(ox - 42, g - 2), (ox + 42, g - 2), (ox + 37, g - 9), (ox - 37, g - 9)], '#A9AEB8', '#5F6672', 1.6)
    P.cpoly([(ox - 37, g - 9), (ox + 37, g - 9), (ox + 33, g - 38), (ox - 33, g - 38)], '#CFD3DA', '#5F6672', 1.8)
    P.cell(ox, g - 24, 4.6, 4.6, '#D97757')
    if typing:
        P.cline([(ox - 24, g - 15), (ox + 24, g - 15)], '#B4BAC6', 1.2)


def draw_book(P, ox, t):
    g = GROUND - 6
    for s in (-1, 1):
        P.cpoly([(ox + s * 36, g - 32), (ox + s * 2, g - 26), (ox + s * 2, g), (ox + s * 36, g - 6)],
                '#C0504D', '#6B2A28', 1.6)
        P.cpoly([(ox + s * 33, g - 32), (ox + s * 2, g - 27), (ox + s * 2, g - 3), (ox + s * 33, g - 8)],
                '#FFF6E0', '#8A6A4A', 1.2)
        for i in range(3):
            y = g - 25 + i * 6
            P.cline([(ox + s * 8, y + 1), (ox + s * 28, y - 3)], '#C9B79A', 1)
    if math.sin(t * 0.9) > 0.93:   # flip a page now and then
        P.cpoly([(ox + 2, g - 27), (ox + 22, g - 36), (ox + 22, g - 12), (ox + 2, g - 3)], '#FFFBEF', '#8A6A4A', 1.2)


class Pen:
    """Draws under an arbitrary transform (accessory space: origin = top of head, body half-width ~36)."""

    def __init__(self, P, tf, k):
        self.cv, self.tf, self.k = P.cv, tf, k

    def poly(self, pts, fill, outline='', w=0, smooth=False):
        flat = []
        for x, y in pts:
            flat.extend(self.tf(x, y))
        self.cv.create_polygon(*flat, fill=fill, outline=outline, smooth=smooth,
                               width=max(1, round(w * self.k)) if outline else 0)

    def ell(self, cx, cy, rx, ry, fill, outline='', w=0):
        self.poly([(cx + rx * math.cos(i * 0.3142), cy + ry * math.sin(i * 0.3142)) for i in range(20)],
                  fill, outline, w)

    def line(self, pts, color, w, smooth=False):
        flat = []
        for x, y in pts:
            flat.extend(self.tf(x, y))
        self.cv.create_line(*flat, fill=color, width=max(1, round(w * self.k)), capstyle='round', smooth=smooth)


ACCESSORIES = [('none', 'None'), ('party', 'Party hat'), ('bow', 'Bow'), ('sprout', 'Sprout'), ('crown', 'Crown')]


def draw_accessory(pen, kind, t):
    if kind == 'party':
        pen.poly([(-15, 3), (15, 3), (5, -30)], '#5FC9F5', '#2F6FB5', 1.6)
        for f in (0.33, 0.62):
            pen.line([(-15 + 20 * f, 3 - 33 * f), (15 - 10 * f, 3 - 33 * f)], '#FFD54A', 3)
        pen.ell(5, -31, 4.5, 4.5, '#FF6B8B', '#C0395A', 1.2)
    elif kind == 'bow':
        cx, cy = 19, 1
        for s in (-1, 1):
            pen.poly([(cx, cy), (cx + s * 13, cy - 9), (cx + s * 13, cy + 8)], '#FF6B8B', '#B83A5A', 1.5)
        pen.ell(cx, cy, 4, 4, '#FF8FA8', '#B83A5A', 1.4)
    elif kind == 'sprout':
        sw = 4 * math.sin(t * 2.2)
        tx, ty = sw, -17
        pen.line([(0, 2), (sw * 0.3, -8), (tx, ty)], '#4E9A3A', 2.4, True)
        for s in (-1, 1):
            pen.poly([(tx, ty), (tx + s * 7, ty - 8), (tx + s * 14, ty - 4), (tx + s * 7, ty + 2)],
                     '#7BC96F', '#3F7F30', 1.2, smooth=True)
    elif kind == 'crown':
        pen.poly([(-16, 3), (16, 3), (18, -14), (9, -5), (0, -19), (-9, -5), (-18, -14)], '#FFD54A', '#C08A00', 1.6)
        for x, y, c in ((0, -2, '#FF5C7E'), (-9, 0, '#5FC9F5'), (9, 0, '#8BE38B')):
            pen.ell(x, y, 2.4, 2.4, c)
        for x, y in ((-18, -14), (0, -19), (18, -14)):
            pen.ell(x, y, 2.2, 2.2, '#FFF2B0', '#C08A00', 0.8)


def draw_typing_paws(P, ox, typing, t, C):
    g = GROUND
    for i, s in enumerate((-1, 1)):
        tap = 3.2 * max(0.0, math.sin(t * 15 + i * 2.6)) if typing else 0
        P.cpoly(rrect(ox + s * 26 - 7, g - 44 + tap, ox + s * 26 + 7, g - 34 + tap, 5, 5),
                C['base'], C['line'], 1.6)


def draw_yarn(P, cx, cy, r, rot):
    P.cell(cx, cy, r, r, '#5FA8F0', '#2F6FB5', 1.6)
    for k in range(3):
        a = rot + k * 1.05
        P.cline([(cx + r * 0.85 * math.cos(a), cy + r * 0.85 * math.sin(a)),
                 (cx + r * 0.2 * math.cos(a + 1.2), cy + r * 0.2 * math.sin(a + 1.2)),
                 (cx - r * 0.85 * math.cos(a + 0.4), cy - r * 0.85 * math.sin(a + 0.4))],
                '#E8F3FF', 1.3, True)


def draw_bowl(P, cx, amount):
    g = GROUND
    P.cpoly([(cx - 24, g - 16), (cx + 24, g - 16), (cx + 17, g), (cx - 17, g)], '#7FA8D8', '#3F5F8F', 1.8)
    P.cell(cx, g - 16, 24, 4.5, '#A9C7EA', '#3F5F8F', 1.6)
    n = int(round(7 * clamp(amount, 0, 1)))
    for i in range(n):
        P.cell(cx - 15 + i * 5, g - 19 - (i % 2) * 2.5, 3.2, 3.2, '#B0703A', '#6B3F1C', 1)


def cookie_icon(P, cx, cy, size=1.0):
    r = 7 * size
    P.cell(cx, cy, r, r, '#E0B070', '#8A5A2A', 1)
    for dx, dy in ((-2.5, -2), (2.5, -1), (0, 3)):
        P.cell(cx + dx * size, cy + dy * size, 1.1 * size, 1.1 * size, '#6B3F1C')


def bubble(P, cx, ybot, text, icon=None):
    cv, S = P.cv, P.S
    tid = P.ctext(cx, ybot - 15, text, 13, '#2B2B33', bold=True)
    x0, y0, x1, y1 = cv.bbox(tid)
    pad = 8 * S
    x0 -= pad
    x1 += pad
    y0 -= 5 * S
    y1 += 5 * S
    shift = 0
    if x0 < 3:
        shift = 3 - x0
    elif x1 > LW * S - 3:
        shift = LW * S - 3 - x1
    if shift:
        cv.move(tid, shift, 0)
        x0 += shift
        x1 += shift
    r = 8 * S
    pts = [x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1, x1 - r, y1, x0 + r, y1,
           x0, y1, x0, y1 - r, x0, y0 + r, x0, y0]
    ow = max(1, round(1.6 * S))
    cv.create_polygon(*pts, fill='#FFFFFF', outline='#2B2B33', width=ow, smooth=True)
    px = clamp(cx * S, x0 + 12 * S, x1 - 12 * S)
    cv.create_polygon(px - 6 * S, y1, px + 6 * S, y1, px, y1 + 7 * S, fill='#FFFFFF', outline='')
    cv.create_line(px - 6 * S, y1, px, y1 + 7 * S, px + 6 * S, y1, fill='#2B2B33', width=ow)
    cv.create_line(px - 5 * S, y1, px + 5 * S, y1, fill='#FFFFFF', width=ow + 1)
    cv.tag_raise(tid)
    if icon == 'cookie':
        cookie_icon(P, (x0 + 14 * S) / S, ((y0 + y1) / 2) / S)


def pill(P, cx, cy, text, color, icon=None):
    cv, S = P.cv, P.S
    tid = P.ctext(cx + (6 if icon else 0), cy, text, 10.5, '#3A3A44', bold=True)
    x0, y0, x1, y1 = cv.bbox(tid)
    x0 -= (15 if icon else 6) * S
    x1 += 6 * S
    shift = 3 - x0 if x0 < 3 else (LW * S - 3 - x1 if x1 > LW * S - 3 else 0)
    if shift:
        cv.move(tid, shift, 0)
        x0 += shift
        x1 += shift
    r = (y1 - y0) / 2 + 1
    cv.create_polygon(x0 + r, y0 - 1, x1 - r, y0 - 1, x1, y0 - 1, x1, y1 + 1, x1 - r, y1 + 1, x0 + r, y1 + 1,
                      x0, y1 + 1, x0, y0 - 1, fill='#FFFFFF', outline=color, width=max(1, round(1.4 * S)),
                      smooth=True)
    cv.tag_raise(tid)
    if icon == 'tomato':
        ix, iy = (x0 + 9 * S) / S, ((y0 + y1) / 2) / S
        P.cell(ix, iy + 0.5, 5, 4.6, '#E5484D', '#A82A2E', 0.9)
        P.cpoly([(ix - 3, iy - 4), (ix, iy - 2.5), (ix + 3, iy - 4), (ix, iy - 5.5)], '#4E9A3A')


def think_bubble(P, cx, ybot, t, caption=None):
    S = P.S
    if caption:
        pill(P, cx, ybot - 36, caption, '#9A9AAA')
    P.cell(cx + 8, ybot + 4, 2.5, 2.5, '#FFFFFF', '#2B2B33', 1.2)
    P.cell(cx + 4, ybot + 10, 1.6, 1.6, '#FFFFFF', '#2B2B33', 1.2)
    P.cpoly([(cx - 30, ybot - 26), (cx + 30, ybot - 26), (cx + 34, ybot - 12), (cx + 30, ybot),
             (cx - 30, ybot), (cx - 34, ybot - 12)], '#FFFFFF', '#2B2B33', 1.6, smooth=True)
    for i in range(3):
        k = 0.5 + 0.5 * math.sin(t * 5 - i * 0.9)
        P.cell(cx - 16 + i * 16, ybot - 13 - k * 3, 3.6 + k * 1.6, 3.6 + k * 1.6, '#2B2B33')


def draw_fx(P, po, C, cx, d, t):
    S = P.S
    top = GROUND - po['lift'] - 84 * po['sy']
    headc = GROUND - po['lift'] - 52 * po['sy']
    for fx in po['fx']:
        k = fx[0]
        if k == 'hearts':
            for i in range(3):
                ph = (fx[1] * 0.7 + i / 3.0) % 1.0
                x = cx + (i - 1) * 24 + 6 * math.sin(fx[1] * 3 + i)
                y = top - 6 - ph * 34
                P.cpoly(heart_pts(x, y, 7.5 * (1 - ph * 0.45)), '#FF6B8B')
        elif k == 'zzz':
            for i in range(3):
                ph = (fx[1] * 0.45 + i / 3.0) % 1.0
                if ph > 0.92:
                    continue
                P.ctext(cx + 26 + ph * 26, top + 10 - ph * 36, 'Z', 10 + ph * 10, '#6E82C8', bold=True, italic=True)
        elif k == 'sparkles':
            for i in range(7):
                ph = (fx[1] * 1.3 + rnd(i)) % 1.0
                a = rnd(i + 9) * 6.28
                rr = 38 + 22 * rnd(i + 3)
                x = cx + rr * math.cos(a)
                y = headc + 4 + rr * 0.8 * math.sin(a)
                P.cpoly(star_pts(x, y, 3 + 6 * math.sin(math.pi * ph)), '#FFD54A', '#E0A800', 0.8)
        elif k == 'confetti':
            cols = ('#FF6B8B', '#FFD54A', '#5FC9F5', '#8BE38B', '#C58BFF')
            for i in range(22):
                y = 8 + ((fx[1] * 70 + rnd(i + 50) * 220) % 210)
                x = cx + (rnd(i) - 0.5) * 200 + 9 * math.sin(fx[1] * 4 + i)
                w = 5
                P.cpoly([(x, y), (x + w, y + 1.5), (x + w - 1, y + 4), (x - 1, y + 2.5)], cols[i % 5])
        elif k == 'exclaim':
            j = 1.5 * math.sin(t * 40)
            P.ctext(cx + 34 + j, top + 2, '!', 30, '#E5384F', bold=True)
        elif k == 'sweat':
            y = headc - 18 + (t * 18) % 14
            P.cpoly([(cx + 32, y - 6), (cx + 36, y + 1), (cx + 28, y + 1)], '#8EC9F5', '#4A92CC', 0.8)
            P.cell(cx + 32, y + 2, 4, 3.6, '#8EC9F5', '#4A92CC', 0.8)
        elif k == 'stars':
            for i in range(3):
                a = fx[1] * 5 + i * 2.09
                P.cpoly(star_pts(cx + 26 * math.cos(a), headc - 22 + 7 * math.sin(a), 5), '#FFD54A', '#E0A800', 0.8)
        elif k == 'dust':
            for i in range(3):
                ph = (fx[1] * 4 + i / 3.0) % 1.0
                P.cell(cx - fx[2] * (20 + ph * 30), GROUND - 4 - ph * 9, 3 + ph * 5, 3 + ph * 5, '#D9D9D9', '#B5B5B5', 0.8)
        elif k == 'bubble':
            bubble(P, cx, max(38, top - 4), fx[1], fx[2] if len(fx) > 2 else None)
        elif k == 'think':
            think_bubble(P, cx, max(60, top - 6), fx[1], fx[2] if len(fx) > 2 else None)
        elif k == 'notes':
            cols = ('#C58BFF', '#5FA8F0', '#FF6B8B')
            for i in range(3):
                ph = (fx[1] * 0.6 + i / 3.0) % 1.0
                P.ctext(cx + (i - 1) * 34 + 8 * math.sin(fx[1] * 3 + i * 2), top - ph * 40,
                        '\u266a\u266b\u266a'[i], 14 + ph * 4, cols[i], bold=True)
        elif k == 'anger':
            s = 1 + 0.25 * abs(math.sin(fx[1] * 9))
            ax, ay = cx + 30, top + 8
            for q in range(4):
                pts = rot_pts([(ax + 2 * s, ay + 7 * s), (ax + 2 * s, ay + 2 * s), (ax + 7 * s, ay + 2 * s)],
                              (ax, ay), q * 90)
                P.cline(pts, '#E5384F', 2.2)


# ---------------------------------------------------------------- animation: pose generator
class Actor:
    """Produces pose parameters from (animation name + elapsed time). No window or state logic, so it can be
    previewed. The chibi skin draws from these directly; the pixel skin only uses shared fields like lift / fx."""

    def __init__(self):
        self.d = 1
        self.look = (0.0, 0.0)
        self.st = {}
        self.swing = 0.0

    def base(self, t):
        return dict(lift=0.0, sx=1.0, sy=1.0 + 0.014 * math.sin(t * 2.4), rot=0.0, ox=0.0, piv=0.0,
                    eyes='open', look=self.look, mouth='none', mopen=0.0, blush=0.0, glasses=False,
                    shadow=1.0, armL=-30.0, armR=-30.0, armlen=16.0, arms_front=False,
                    legs=[(0.0, 0.0)] * 4, props=[], fx=[])

    @staticmethod
    def trot(a, b):
        """Diagonal trot: a, b = lift of the two leg pairs."""
        return [(0, -6 * a), (0, -6 * b), (0, -6 * a), (0, -6 * b)]

    def pose(self, b, t):
        n = b['name']
        d = self.d
        p = self.base(t)
        mood = self.st.get('mood', 80)
        dur = b.get('dur') or 1.0

        if n == 'sit':
            k = t % 6.0
            p['armL'] = -30 + 5 * math.sin(t * 2.1)
            p['armR'] = -30 - 5 * math.sin(t * 2.1 + 1)
            if k < 0.6:
                p['rot'] = 4 * math.sin(k * 10.5)
            if mood < 30:
                p.update(eyes='sad', mouth='frown', armL=-62, armR=-62, sy=0.95)
            elif mood > 75:
                p.update(mouth='smile', lift=1.2 * abs(math.sin(t * 3)))

        elif n == 'walk':
            ph = t * 8
            a = math.sin(ph)
            p.update(legs=self.trot(max(0, a), max(0, -a)), lift=1.8 * abs(a), rot=d * 2.5 + 3 * a,
                     armL=-30 + 20 * a, armR=-30 - 20 * a, look=(d * 0.9, self.look[1] * 0.5))

        elif n in ('run', 'chase', 'fetch'):
            a = math.sin(t * 15)
            legs = self.trot(max(0, a), max(0, -a))
            p.update(legs=[(d * 5, dy * 1.4) for _, dy in legs], lift=5 * abs(a), rot=d * 10, sx=1.06, sy=0.95,
                     armL=-75 + 15 * a, armR=-75 - 15 * a, eyes='wide', look=(d, 0.0),
                     mouth='open', mopen=0.35)
            p['fx'] = [('dust', t, d)]

        elif n == 'sleep':
            p.update(sy=0.72 + 0.025 * math.sin(t * 1.6), sx=1.14, eyes='closed', armL=-75, armR=-75,
                     look=(0, 0), legs=[(0, -5)] * 4)
            p['fx'] = [('zzz', t)]

        elif n == 'wave':
            p.update(armR=70 + 25 * math.sin(t * 9), eyes='happy', mouth='smile', rot=2 * math.sin(t * 3),
                     lift=1.5 * abs(math.sin(t * 4.5)))

        elif n == 'yawn':
            k = math.sin(math.pi * clamp(t / dur, 0, 1)) ** 0.7
            p.update(eyes='closed', mouth='open', mopen=k, sy=1 + 0.08 * k, sx=1 - 0.04 * k,
                     armL=-30 + 50 * k, armR=-30 + 50 * k)

        elif n == 'stretch':
            k = math.sin(math.pi * clamp(t / dur, 0, 1))
            p.update(sy=1 + 0.16 * k, sx=1 - 0.08 * k, eyes='closed', mouth='open', mopen=0.3 * k,
                     armL=-30 + 115 * k, armR=-30 + 115 * k)

        elif n == 'scratch':
            w = math.sin(t * 22)
            p.update(armR=118 + 8 * w, arms_front=True, armlen=20, rot=-3, eyes='closed', mouth='flat')

        elif n == 'look':
            s = math.sin(t * 1.3)
            p.update(rot=3 * s, look=(s, 0.25 * math.sin(t * 0.8)), armL=-30 + 8 * max(0, -s),
                     armR=-30 + 8 * max(0, s))

        elif n in ('jump', 'pounce'):
            u = clamp(t / dur, 0, 1)
            if u < 0.22:
                k = u / 0.22
                p.update(sy=1 - 0.22 * k, sx=1 + 0.10 * k, eyes='shut' if n == 'jump' else 'wide')
            elif u < 0.85:
                k = (u - 0.22) / 0.63
                p.update(lift=(58 if n == 'jump' else 34) * math.sin(math.pi * k), sy=1.07, sx=0.96,
                         eyes='happy' if n == 'jump' else 'wide', mouth='open', mopen=0.4,
                         armL=75, armR=75, legs=[(0, -6)] * 4, rot=d * (2 if n == 'jump' else 9))
            else:
                k = (u - 0.85) / 0.15
                p.update(sy=0.8 + 0.2 * k, sx=1.14 - 0.14 * k, eyes='shut')
            if n == 'jump' and 0.2 < u < 0.9 and b.get('shout'):
                p['fx'] = [('bubble', T('b.yay'))]

        elif n == 'spin':
            c = math.cos(t * 7.5)
            p.update(sx=c, eyes='wide', look=(c, 0.3), mouth='open', mopen=0.3, rot=4 * math.sin(t * 7.5),
                     armL=15, armR=15, legs=self.trot(max(0, math.sin(t * 20)), max(0, -math.sin(t * 20))))

        elif n == 'pet':
            wig = math.sin(t * 13)
            p.update(eyes='happy', mouth='smile', blush=1.0, rot=3 * wig, armL=30 + 10 * wig, armR=30 - 10 * wig)
            p['fx'] = [('hearts', t)]
            if t > 0.25:
                p['fx'].append(('bubble', T('b.pet')))

        elif n == 'surprise':
            u = clamp(t / dur, 0, 1)
            p.update(lift=16 * math.sin(math.pi * min(1, u * 2.2)), eyes='wide', mouth='o', armL=80, armR=80,
                     sy=1.05, legs=[(0, -4)] * 4)
            p['fx'] = [('exclaim',)]

        elif n == 'land':
            k = clamp(t / dur, 0, 1)
            p.update(sy=0.76 + 0.24 * k, sx=1.18 - 0.18 * k, eyes='shut')
            if k < 0.6:
                p['fx'] = [('dust', t, 1)]

        elif n == 'dizzy':
            p.update(eyes='dizzy', mouth='o', rot=7 * math.sin(t * 5), armL=10, armR=10)
            p['fx'] = [('stars', t)]

        elif n == 'held':
            w = 6 * math.sin(t * 5)
            p.update(piv=-95.0, rot=self.swing + 3 * math.sin(t * 3), sy=1.12, sx=0.94, eyes='wide', mouth='o',
                     armL=-75 + w, armR=-75 - w, legs=[(0, 3)] * 4, shadow=0.0)

        elif n == 'fall':
            w = math.sin(t * 20)
            p.update(eyes='wide', mouth='o', armL=75 + 15 * w, armR=75 - 15 * w, legs=[(0, -5)] * 4,
                     sy=1.08, sx=0.95, shadow=0.0)
            if b.get('spin'):
                p.update(rot=b['spin'] * t, piv=-48.0, eyes='dizzy' if t > 0.4 else 'wide')

        elif n == 'work':
            p.update(look=(0.0, 0.75), glasses=True, armL=-80, armR=-80, rot=1.2 * math.sin(t * 1.5),
                     props=[('laptop', True), ('laptop_paws', True)])
            if b.get('cat') in ('read', 'search', 'web'):
                p['props'] = [('book',), ('laptop_paws', False)]
            p['fx'] = [('think', t, b.get('caption'))]

        elif n == 'dance':
            s = math.sin(t * 4.4)
            h = math.sin(t * 8.8)
            p.update(rot=10 * s, lift=8 * abs(h), eyes='happy', mouth='open', mopen=0.5, blush=0.8,
                     armL=20 + 60 * s, armR=20 - 60 * s, legs=self.trot(max(0, h), max(0, -h)))
            p['fx'] = [('notes', t)]

        elif n == 'annoyed':
            p.update(eyes='angry', mouth='pout', blush=1.0, sx=1.07, sy=0.95, armL=-5, armR=-5,
                     rot=4 * math.sin(t * 22) if t < 0.5 else 0)
            p['fx'] = [('anger', t), ('bubble', T('b.annoyed'))]

        elif n == 'kick':
            k = math.sin(math.pi * clamp(t / dur, 0, 1))
            legs = [(0.0, 0.0)] * 4
            legs[3 if d > 0 else 0] = (d * 12 * k, -9 * k)
            p.update(rot=-d * 8 * k, eyes='wide', mouth='open', mopen=0.3, armL=40 * k, armR=40 * k, legs=legs)

        elif n == 'ring':
            w = math.sin(t * 14)
            p.update(lift=6 * abs(math.sin(t * 6)), eyes='wide', mouth='open', mopen=0.5, armL=70 + 15 * w,
                     armR=70 - 15 * w)
            p['fx'] = [('exclaim',), ('bubble', b.get('text') or T('b.ring'))]

        elif n == 'remind':
            k = math.sin(math.pi * clamp(t / dur, 0, 1))
            p.update(sy=1 + 0.12 * k, sx=1 - 0.06 * k, eyes='happy', mouth='smile', armL=-30 + 110 * k,
                     armR=-30 + 110 * k)
            p['fx'] = [('bubble', b.get('text') or T('b.remind'))]

        elif n == 'bye':
            p.update(armR=70 + 25 * math.sin(t * 9), eyes='happy', mouth='smile', rot=2 * math.sin(t * 3))
            p['fx'] = [('bubble', T('b.bye'))]

        elif n == 'achieve':
            p.update(lift=12 * abs(math.sin(t * 5)), eyes='happy', mouth='open', mopen=0.5, armL=75, armR=75,
                     blush=1.0)
            p['fx'] = [('sparkles', t), ('bubble', T('b.achieve', name=b.get('text', '')))]

        elif n == 'celebrate':
            hop = abs(math.sin(t * 6.5))
            p.update(lift=28 * hop, sy=1 + 0.05 * (1 - hop), eyes='happy', mouth='open', mopen=0.65,
                     armL=80, armR=80, blush=1.0, legs=[(0, -4 * hop)] * 4)
            p['fx'] = [('confetti', t), ('bubble', b.get('text') or T('b.done'))]

        elif n == 'levelup':
            p.update(sx=math.cos(t * 9), lift=10 * abs(math.sin(t * 4.5)), eyes='happy', mouth='open', mopen=0.5,
                     armL=75, armR=75, blush=1.0)
            p['fx'] = [('sparkles', t), ('bubble', T('b.levelup', level=b.get('level', '?')))]

        elif n == 'alert':
            w = math.sin(t * 15)
            p.update(lift=9 * abs(math.sin(t * 5)), eyes='wide', mouth='o', armR=75 + 12 * w, armL=-30)
            p['fx'] = [('exclaim',), ('bubble', T('b.alert'))]

        elif n == 'hungry':
            p.update(eyes='sad', mouth='frown', sy=0.97 + 0.014 * math.sin(t * 5), armL=-140, armR=-140,
                     arms_front=True)
            p['fx'] = [('sweat',), ('bubble', T('b.hungry'), 'cookie')]

        elif n == 'eat':
            amt = clamp(1 - t / 5.6, 0, 1)
            chew = math.sin(t * 12)
            p.update(rot=d * 13, sy=0.96, eyes='closed' if amt > 0 else 'happy', armL=-50, armR=-50)
            if amt > 0:
                p.update(mouth='open', mopen=0.3 + 0.25 * chew)
            else:
                p.update(mouth='smile', blush=0.8)
                p['fx'] = [('hearts', t), ('bubble', T('b.yummy'))]
            p['props'] = [('bowl', d * 68, amt)]

        elif n == 'play':
            w = t * 2.2
            bx = d * (62 + 34 * math.sin(w))
            bounce = abs(math.sin(w * 2)) * 11
            swat = max(0.0, math.sin(t * 9)) if math.sin(w) > 0.4 else 0.0
            p.update(look=(1 if bx * d > 0 else -1, 0.7), rot=d * 3 * math.sin(w), eyes='wide', mouth='open',
                     mopen=0.25, lift=6 * abs(math.sin(t * 4.4)) if abs(math.sin(w)) >= 0.35 else 0.0)
            if d > 0:
                p['armR'] = -30 + 75 * swat
            else:
                p['armL'] = -30 + 75 * swat
            p['props'] = [('yarn', bx, bounce, w * 1.4)]
            if t > 8.0:
                p['fx'] = [('hearts', t)]
        return p


# ---------------------------------------------------------------- pixel skin (sprite sheet)
# Sprites from shigure0110/clawd-pet (MIT): 8 columns x 22 rows, 192x208 per cell, feet baseline at y=192.
SPRITE_CELL = (192, 208)
SPRITE_BASE_Y = 192
SPRITE_ROWS = dict(  # name: (row, frames, fps)
    idle=(0, 6, 6), run_r=(1, 8, 12), run_l=(2, 8, 12), wave=(3, 4, 7), jump=(4, 5, 8), fail=(5, 8, 8),
    wait=(6, 6, 6), busy=(7, 6, 8), review=(8, 6, 6), typing=(9, 6, 8), flower=(10, 6, 6), coffee=(11, 6, 6),
    water=(12, 6, 6), fries=(13, 6, 6), read=(14, 6, 6), game=(15, 6, 8), flip=(16, 8, 8), sleep=(17, 6, 3),
    sleepcap=(18, 6, 3), wake=(19, 6, 5), yawn=(20, 6, 5), love=(21, 6, 7))
# Effects already baked into the sprites; don't draw them twice
SPRITE_SKIP_FX = ('zzz', 'sweat', 'stars', 'dust')


class SpriteSkin:
    def __init__(self, root, png_path, S):
        self.root = root
        self.src = tk.PhotoImage(master=root, file=png_path)
        self.cache = {}
        self.rebuild(S)

    @staticmethod
    def try_load(root, S):
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'assets', 'clawd-sprites.png')
        try:
            return SpriteSkin(root, os.path.normpath(path), S)
        except Exception as e:
            log('sprites unavailable: %s' % e)
            return None

    def rebuild(self, S):
        # The art uses 4px per pixel: scale each one to bp real pixels so it stays crisp
        self.bp = max(1, round(S * 0.6 * 4))
        self.cache = {}

    def frame(self, row, col):
        key = (row, col)
        img = self.cache.get(key)
        if img is None:
            w, h = SPRITE_CELL
            cell = tk.PhotoImage(master=self.root)
            self.root.tk.call(str(cell), 'copy', str(self.src), '-from', col * w, row * h, (col + 1) * w, (row + 1) * h)
            img = cell.zoom(self.bp).subsample(4)
            self.cache[key] = img
        return img

    def select(self, b, t, d):
        """Returns (row, frame)."""
        n = b['name']
        dur = b.get('dur') or 1.0
        u = clamp(t / dur, 0.0, 0.999)

        def loop(name, fps=None):
            r, nf, f = SPRITE_ROWS[name]
            return r, int(t * (fps or f)) % nf

        def once(name):
            r, nf, _ = SPRITE_ROWS[name]
            return r, int(u * nf)

        def hold(name, i):
            return SPRITE_ROWS[name][0], i

        if n == 'walk':
            return loop('run_r' if d > 0 else 'run_l', 8)
        if n == 'dance':
            nm, i = (('jump', 1), ('wave', 0), ('jump', 2), ('wave', 2))[int(t * 5) % 4]
            return hold(nm, i)
        if n == 'fall' and b.get('spin'):
            return loop('flip', 12)
        if n == 'work':
            return loop({'read': 'read', 'search': 'review', 'web': 'read', 'agent': 'busy'}.get(b.get('cat'), 'typing'))
        if n == 'kick':
            return once('jump')
        if n in ('ring', 'bye'):
            return loop('wave', 10 if n == 'ring' else 7)
        if n == 'remind':
            return loop('water')
        if n == 'achieve':
            return loop('love')
        if n == 'annoyed':
            return loop('busy')
        if n in ('run', 'chase', 'fetch'):
            return loop('run_r' if d > 0 else 'run_l', 14)
        if n in ('jump', 'pounce'):
            return once('jump')
        if n == 'spin':
            return once('flip')
        if n == 'levelup':
            return loop('flip', 10)
        if n in ('celebrate',):
            r = SPRITE_ROWS['jump'][0]
            return r, 1 + int(t * 8) % 3
        if n in ('held', 'fall'):
            return hold('jump', 3)
        if n == 'surprise':
            return hold('jump', 1)
        if n == 'land':
            return hold('idle', 0)
        if n == 'sleep':
            return loop('sleepcap' if b.get('cap') else 'sleep')
        if n == 'stretch':
            return once('wake')
        if n == 'alert':
            return loop('wave', 10)
        table = dict(sit='idle', wave='wave', look='wait', yawn='yawn', scratch='review', hungry='wait',
                     pet='love', eat='fries', play='game', dizzy='fail', work='typing', coffee='coffee',
                     water='water', fries='fries', flower='flower', game='game', read='read')
        return loop(table.get(n, 'idle'))

    def head_top(self, row, col):
        """Height of the body top above the feet in this cell (sprite pixels); used to place accessories."""
        key = ('top', row, col)
        v = self.cache.get(key)
        if v is None:
            w, h = SPRITE_CELL
            v = 104
            for y in range(40, SPRITE_BASE_Y):
                if any(not self.src.transparency_get(col * w + x, row * h + y) for x in (90, 96, 102)):
                    v = SPRITE_BASE_Y - y
                    break
            self.cache[key] = v
        return v

    def draw(self, P, po, b, d, t):
        r, c = self.select(b, t, d)
        self.last_rc = (r, c)
        img = self.frame(r, c)
        S = P.S
        x = (LW / 2 + po['ox']) * S - 24 * self.bp
        y = (GROUND - po['lift']) * S - (SPRITE_BASE_Y // 4) * self.bp
        P.cv.create_image(int(x), int(y), anchor='nw', image=img)


def draw_pixel(P, po, C, d, t, b, sprites):
    ox = LW / 2 + po['ox']
    draw_shadow(P, ox, po['shadow'], 1.0, po['lift'], 40)
    sprites.draw(P, po, b, d, t)
    acc = po.get('acc')
    r, c = sprites.last_rc
    if acc and acc != 'none' and r not in (16, 17, 18):   # no accessories on flip / sleep frames
        S = P.S
        k = sprites.bp / (4.0 * S)            # 1 sprite pixel = k logical units
        top = GROUND - po['lift'] - sprites.head_top(r, c) * k
        m = 57 * k / 36.0                      # body half-width is ~57 px; accessories are drawn for 36
        draw_accessory(Pen(P, lambda x, y: ((ox + x * m) * S, (top + y * m) * S), S), acc, t)
    po['fx'] = [f for f in po['fx'] if f[0] not in SPRITE_SKIP_FX]
    draw_fx(P, po, C, ox, d, t)


DUR = dict(sit=(3, 7), wave=(4.5, 4.5), look=(4, 4), yawn=(2.4, 2.4), stretch=(2.8, 2.8),
           scratch=(3, 3), spin=(2.6, 2.6), jump=(1.15, 1.15), sleep=(18, 40), hungry=(4, 6),
           pet=(1.8, 1.8), celebrate=(3.4, 3.4), levelup=(3.2, 3.2), alert=(6, 6), eat=(6.8, 6.8),
           play=(9, 9), coffee=(5, 5), water=(5, 5), fries=(5, 5), flower=(5, 5), game=(6, 6),
           read=(5, 5), land=(0.45, 0.45), dizzy=(2.5, 2.5), surprise=(0.9, 0.9), pounce=(1.0, 1.0),
           dance=(4.5, 4.5), annoyed=(2.2, 2.2), kick=(0.55, 0.55), ring=(6, 6), remind=(5, 5), bye=(3, 3),
           achieve=(3.4, 3.4))
CALM = {'sit', 'walk', 'run', 'chase', 'wave', 'look', 'yawn', 'stretch', 'scratch', 'spin', 'jump',
        'sleep', 'hungry', 'pet', 'eat', 'play', 'pounce', 'surprise', 'coffee', 'water', 'fries', 'flower',
        'game', 'read', 'dance', 'fetch', 'kick', 'annoyed'}
TRICKS = [('dance', 'Dance'), ('spin', 'Spin'), ('jump', 'Jump'), ('wave', 'Wave'), ('stretch', 'Stretch'),
          ('sleep', 'Sleep')]
WATCH = ('alertAt', 'levelUpAt', 'celebrateAt', 'feedAt', 'playAt', 'trickAt', 'sayAt', 'byeAt', 'achieveAt',
         'timerSetAt', 'timerDoneAt')
SCALES = (0.6, 0.75, 0.9, 1.0, 1.2, 1.4, 1.65, 1.9, 2.2)


# ---------------------------------------------------------------- the pet
class Ball:
    """A ball you can throw; Clawd chases and kicks it (its own small transparent window)."""
    R = 13

    def __init__(self, app, x, y):
        self.app = app
        self.x, self.y = x, y
        self.vx, self.vy = 0.0, 0.0
        self.ang = 0.0
        self.held = None
        self.shown = True
        self.lastpos = None
        w = self.top = tk.Toplevel(app.root)
        w.overrideredirect(True)
        w.configure(bg=CHROMA)
        w.attributes('-topmost', True)
        try:
            w.attributes('-transparentcolor', CHROMA)
        except tk.TclError:
            pass
        self.cv = tk.Canvas(w, bg=CHROMA, highlightthickness=0, bd=0)
        self.cv.pack()
        self.cv.bind('<ButtonPress-1>', self.on_press)
        self.cv.bind('<B1-Motion>', self.on_motion)
        self.cv.bind('<ButtonRelease-1>', self.on_release)
        self.cv.bind('<Button-3>', app.on_menu)
        self.resize()

    def resize(self):
        self.px = int((self.R * 2 + 4) * self.app.S)
        self.cv.config(width=self.px, height=self.px)
        self.lastpos = None

    @property
    def resting(self):
        return self.held is None and self.vy == 0 and abs(self.vx) < 20 * self.app.S

    def on_press(self, e):
        self.held = (e.x_root - self.x, e.y_root - self.y, time.time())
        self.vx = self.vy = 0.0

    def on_motion(self, e):
        if not self.held:
            return
        n = time.time()
        dt = max(n - self.held[2], 0.008)
        nx, ny = e.x_root - self.held[0], e.y_root - self.held[1]
        self.vx = 0.5 * self.vx + 0.5 * (nx - self.x) / dt
        self.vy = 0.5 * self.vy + 0.5 * (ny - self.y) / dt
        self.x, self.y = nx, ny
        self.held = (self.held[0], self.held[1], n)

    def on_release(self, e):
        if self.held and time.time() - self.held[2] > 0.1:
            self.vx = self.vy = 0.0
        self.held = None
        self.app.restore_focus()

    def kick(self, d):
        S = self.app.S
        self.vx = d * random.uniform(380, 700) * S
        self.vy = -random.uniform(350, 800) * S

    def step(self, dt, wa, visible):
        S = self.app.S
        if visible != self.shown:
            self.shown = visible
            if visible:
                self.top.deiconify()
                self.top.attributes('-topmost', True)
                self.lastpos = None
            else:
                self.top.withdraw()
        if not self.held:
            r = self.R * S
            self.vx = clamp(self.vx, -3000 * S, 3000 * S)
            self.vy = clamp(self.vy + 2000 * S * dt, -3000 * S, 3000 * S)
            self.x += self.vx * dt
            self.y += self.vy * dt
            if self.y >= wa[3] - r:
                self.y = wa[3] - r
                self.vy = -self.vy * 0.62 if self.vy > 160 * S else 0.0
                self.vx *= max(0.0, 1 - 2.2 * dt)
                if abs(self.vx) < 5 * S:
                    self.vx = 0.0
            if self.x < wa[0] + r:
                self.x, self.vx = wa[0] + r, abs(self.vx) * 0.8
            elif self.x > wa[2] - r:
                self.x, self.vx = wa[2] - r, -abs(self.vx) * 0.8
            if self.y < wa[1] + r:
                self.y, self.vy = wa[1] + r, abs(self.vy) * 0.5
            self.ang += self.vx * dt / max(r, 1) * 57.3
        if not self.shown:
            return
        pos = (int(self.x - self.px / 2), int(self.y - self.px / 2))
        if pos != self.lastpos:
            self.top.geometry('%dx%d+%d+%d' % (self.px, self.px, pos[0], pos[1]))
            self.lastpos = pos
        cv = self.cv
        cv.delete('all')
        c = self.px / 2
        r = self.R * S
        box = (c - r, c - r, c + r, c + r)
        for i, col in enumerate(('#FF6B6B', '#FFD54A', '#5FA8F0')):
            cv.create_arc(*box, start=self.ang + i * 120, extent=120, fill=col, outline='')
        cv.create_oval(c - r * 0.3, c - r * 0.3, c + r * 0.3, c + r * 0.3, fill='#FFFFFF', outline='')
        cv.create_oval(*box, outline='#5A3A2A', width=max(1, round(1.6 * S)))
        cv.create_oval(c - r * 0.6, c - r * 0.7, c - r * 0.2, c - r * 0.35, fill='#FFFFFF', outline='')

    def destroy(self):
        try:
            self.top.destroy()
        except Exception:
            pass


class PetApp:
    PREF_DEFAULTS = dict(scale=1.0, follow=False, only_claude=True, skin='pixel', peek=True, sound=True,
                         chatter=True, stay=False, dnd=False, break_mins=60,
                         lang='auto')

    def __init__(self, force=None):
        dpi = 1.0
        if os.name == 'nt':
            try:
                ctypes.windll.user32.SetProcessDPIAware()
                dpi = ctypes.windll.user32.GetDpiForSystem() / 96.0
            except Exception:
                pass
        self.dpi = dpi
        self.read_prefs(load_prefs())
        self.S = dpi * self.scale_pref

        self.root = tk.Tk()
        r = self.root
        r.title('Claude Pet')
        r.overrideredirect(True)
        r.configure(bg=CHROMA)
        r.attributes('-topmost', True)
        try:
            r.attributes('-transparentcolor', CHROMA)
        except tk.TclError:
            r.attributes('-alpha', 0.95)
        self.cv = tk.Canvas(r, bg=CHROMA, highlightthickness=0, bd=0)
        self.cv.pack()
        self.P = Painter(self.cv, self.S)
        self.actor = Actor()
        self.sprites = SpriteSkin.try_load(r, self.S)
        if self.sprites is None:
            self.skin = 'chibi'

        self.st = load_state()
        self.st_mtime = 0
        act = self.st.get('activity', {})
        self.seen = {k: act.get(k, 0) for k in WATCH}

        self.wa = self.work_area()
        self.d = random.choice((-1, 1))
        self.x = random.uniform(self.wa[0] + 200, self.wa[2] - 200)
        self.y = self.wa[3]
        self.vy = 0.0
        self.vx = 0.0
        self.dvy = 0.0
        self.press = None
        self.dragging = False
        self.last = time.time()
        self.last_motion = self.last
        self.msg = None
        self.queue = []
        self.last_name = ''
        self.blink_until = 0.0
        self.next_blink = self.last + 3
        self.next_decay = self.last + 30
        self.next_topmost = self.last + 5
        self.next_area = self.last + 3
        self.next_slow = self.last + 1
        self.next_chatter = self.last + random.uniform(120, 300)
        self.cur_speed = 0.0
        self.last_ptr = (0, 0)
        self.last_pet_bonus = 0.0
        self.chase_cool = self.last + 20
        self.size_dirty = True
        self.lastpos = None
        self.visible = True
        self.pending = {}
        self.not_claude_since = None
        self.next_fg = 0.0
        self.next_prefs = self.last + 1
        self.prefs_mtime = self.prefs_stamp()
        self.peek_until = 0.0
        self.snooze_until = 0.0
        self.active_since = self.last
        self.prev_fg = None
        self.clicks = []
        self.hover_since = None
        self.hover_shown = False
        self.ball = None
        self.ach_win = None

        self.apply_scale(self.scale_pref, save=False)
        self.build_menu()
        for ev, fn in (('<ButtonPress-1>', self.on_press), ('<B1-Motion>', self.on_motion),
                       ('<ButtonRelease-1>', self.on_release), ('<Button-3>', self.on_menu),
                       ('<Enter>', self.on_enter), ('<Leave>', self.on_leave),
                       ('<Control-MouseWheel>', self.on_wheel)):
            self.cv.bind(ev, fn)

        try:
            os.remove(QUIT)
        except OSError:
            pass

        self.cur = None
        if force:
            self.start(force)
        else:
            self.y = self.wa[3] - 240 * self.S
            self.start('fall')
        if self.only_claude and not foreground_is_claude():
            self.root.withdraw()
            self.visible = False
        self.root.after(TICK_MS, self.tick)

    # ---------- environment
    def work_area(self):
        if os.name == 'nt':
            try:
                from ctypes import wintypes
                rc = wintypes.RECT()
                if ctypes.windll.user32.SystemParametersInfoW(48, 0, ctypes.byref(rc), 0):
                    return rc.left, rc.top, rc.right, rc.bottom
            except Exception:
                pass
        return 0, 0, self.root.winfo_screenwidth(), self.root.winfo_screenheight() - 48

    @property
    def gy(self):
        return self.wa[3]

    @property
    def busy(self):
        return self.st.get('activity', {}).get('busyUntil', 0) > now_ms()

    def apply_scale(self, scale, save=True):
        self.scale_pref = scale
        self.S = self.dpi * scale
        self.P.S = self.S
        self.WP, self.HP = int(LW * self.S), int(LH * self.S)
        self.cv.config(width=self.WP, height=self.HP)
        self.size_dirty = True
        if self.sprites:
            self.sprites.rebuild(self.S)
        if self.ball:
            self.ball.resize()
        if save:
            self.save_prefs()

    # ---------- preferences
    def read_prefs(self, prefs):
        d = dict(self.PREF_DEFAULTS)
        d.update({k: v for k, v in prefs.items() if k in d})
        self.scale_pref = float(d['scale'])
        self.follow = bool(d['follow'])
        self.only_claude = bool(d['only_claude'])
        self.skin = d['skin'] if d['skin'] in ('pixel', 'chibi') else 'pixel'
        self.peek_on = bool(d['peek'])
        self.sound = bool(d['sound'])
        self.chatter = bool(d['chatter'])
        self.stay = bool(d['stay'])
        self.dnd = bool(d['dnd'])
        self.lang_pref = d['lang'] if d['lang'] in STRINGS else 'auto'
        set_lang(self.lang_pref)
        try:
            self.break_mins = max(0, int(d['break_mins']))
        except (TypeError, ValueError):
            self.break_mins = 60

    def save_prefs(self):
        try:
            prefs = load_prefs()
            prefs.update(scale=self.scale_pref, follow=self.follow, only_claude=self.only_claude, skin=self.skin,
                         peek=self.peek_on, sound=self.sound, chatter=self.chatter, stay=self.stay, dnd=self.dnd,
                         break_mins=self.break_mins, lang=self.lang_pref)
            write_json(PREFS, prefs)
        except Exception as e:
            log('prefs: %s' % e)
        self.prefs_mtime = self.prefs_stamp()

    def prefs_stamp(self):
        try:
            return os.stat(PREFS).st_mtime_ns
        except OSError:
            return 0

    def poll_prefs(self):
        """pet.js commands like /pet focus and /pet skin edit prefs.json; read them back here."""
        m = self.prefs_stamp()
        if m == self.prefs_mtime:
            return
        self.prefs_mtime = m
        skin, scale, lang = self.skin, self.scale_pref, self.lang_pref
        self.read_prefs(load_prefs())
        if self.lang_pref != lang:
            self.build_menu()
        if self.skin == 'pixel' and not self.sprites:
            self.skin = 'chibi'
        if self.scale_pref != scale:
            self.apply_scale(self.scale_pref, save=False)
        self.sync_vars()

    def set_skin(self, skin):
        if skin == 'pixel' and self.sprites is None:
            self.say(T('say.no_sprites'))
            skin = 'chibi'
        self.skin = skin
        self.save_prefs()

    def set_break(self, mins):
        self.break_mins = mins
        self.active_since = time.time()
        self.save_prefs()
        self.say(T('say.break_every', n=mins) if mins else T('say.break_off'))

    # ---------- show / hide / pop-up reminders
    def update_visibility(self, now):
        fg = foreground()
        if fg and fg[1] != os.getpid():
            self.prev_fg = fg[0]
        if now < self.snooze_until:
            want = False
        else:
            want = (not self.only_claude) or now < self.peek_until or foreground_is_claude()
        if want:
            self.not_claude_since = None
            if not self.visible:
                self.show_pet()
        elif self.visible and not self.dragging:
            # Right after switching windows the foreground may briefly be the taskbar; wait a moment before hiding
            if self.not_claude_since is None:
                self.not_claude_since = now
            elif now - self.not_claude_since > 0.6:
                self.hide_pet()

    def hide_pet(self):
        self.root.withdraw()
        self.visible = False
        self.press = None

    def show_pet(self, replay=True):
        self.root.deiconify()
        self.root.attributes('-topmost', True)
        self.visible = True
        self.size_dirty = True
        self.last = time.time()
        if not replay:
            return
        # Things missed while hidden (permission request, achievement, level up, just finished): replay on return
        pend, self.pending = self.pending, {}
        n = time.time()
        for key, limit in (('alertAt', 600), ('achieveAt', 3600), ('levelUpAt', 3600), ('celebrateAt', 30)):
            if key in pend and n - pend[key][0] < limit:
                self.play_event(key, pend[key][1])
                break

    def can_peek(self):
        return self.peek_on and not self.dnd and time.time() >= self.snooze_until

    def peek(self, secs):
        """Pop up briefly while Claude is not in front."""
        self.peek_until = max(self.peek_until, time.time() + secs)
        if not self.visible:
            self.show_pet(replay=False)
            self.not_claude_since = None

    def beep(self):
        if not self.sound or self.dnd:
            return
        try:
            import winsound
            winsound.MessageBeep(0x40)
        except Exception:
            pass

    def notify(self, name, peek_secs, beep=False, **kw):
        """Locally triggered reminders (pomodoro, break): pop up if hidden, optionally with a sound."""
        if not self.visible:
            if not self.can_peek():
                return False
            self.peek(peek_secs)
        if beep:
            self.beep()
        self.start(name, **kw)
        return True

    def restore_focus(self):
        """Clicking the pet steals focus; hand it back to the previous window (usually Claude) so typing continues."""
        fg = foreground()
        if self.prev_fg and fg and fg[1] == os.getpid():
            activate(self.prev_fg)

    # ---------- state
    def colors(self):
        return SCHEMES.get(self.st.get('color', 'orange'), SCHEMES['orange'])

    def mutate(self, fn):
        st = load_state()
        tick_state(st)
        res = fn(st)
        check_achievements(st)
        try:
            write_json(STATE, st)
        except Exception as e:
            log('write state: %s' % e)
        self.st = st
        self.poll_state(force=True)
        return res

    def poll_state(self, force=False):
        try:
            m = os.stat(STATE).st_mtime_ns
        except OSError:
            m = 0
        if m == self.st_mtime and not force:
            return
        self.st_mtime = m
        self.st = load_state()
        act = self.st.get('activity', {})
        if self.cur['name'] in ('held', 'fall'):
            return
        for key in WATCH:
            v = act.get(key, 0)
            if v > self.seen[key]:
                self.seen[key] = v
                self.on_event(key, dict(act))

    def on_event(self, key, act):
        if not self.visible:
            peek = {'alertAt': 30, 'celebrateAt': 7, 'timerDoneAt': 20}.get(key)
            if peek and self.can_peek() and self.only_claude:
                self.peek(peek)
                if key != 'celebrateAt':
                    self.beep()
            else:
                if key in ('alertAt', 'levelUpAt', 'celebrateAt', 'achieveAt'):
                    self.pending[key] = (time.time(), act)
                return
        self.play_event(key, act)

    def play_event(self, key, act):
        cur = self.cur['name'] if self.cur else ''
        if key == 'alertAt':
            self.start('alert')
        elif key == 'levelUpAt':
            self.start('levelup', level=act.get('levelUpTo', level_of(self.st['xp'])))
        elif key == 'celebrateAt':
            if cur not in ('levelup', 'alert', 'achieve'):
                lt = act.get('lastTurn') or {}
                ms = lt.get('ms', 0)
                text = T('b.done_time', time=fmt_clock(ms / 1000)) if ms >= 20000 else None
                self.start('celebrate', text=text)
                if ms >= 180000:
                    self.queue = ['dance']
        elif key == 'feedAt':
            self.start('eat')
        elif key == 'playAt':
            self.start('play')
        elif key == 'trickAt':
            if act.get('trick') in dict(TRICKS):
                self.start(act['trick'])
        elif key == 'sayAt':
            self.say(str(act.get('sayText', ''))[:40], 6)
            if cur in CALM:
                self.start('wave')
        elif key == 'byeAt':
            if cur in CALM:
                self.start('bye')
        elif key == 'achieveAt':
            by_id = {a['id']: a for a in ACHIEVEMENTS}
            names = [loc(by_id[i]['name']) for i in act.get('achieveIds') or [] if i in by_id]
            items = [('achieve', {'text': nm}) for nm in names]
            if cur in ('annoyed', 'kick', 'pet', 'eat', 'play', 'celebrate', 'levelup', 'alert', 'ring', 'jump',
                       'dizzy', 'land', 'pounce'):
                self.queue[:0] = items      # announce after the current animation
            elif items:
                self.start('achieve', text=names[0])
                self.queue = items[1:]
        elif key == 'timerSetAt':
            tm = self.st.get('timer') or {}
            self.say(T('say.timer_start', n=tm.get('mins', 0)) if tm else T('say.timer_start0'))
        elif key == 'timerDoneAt':
            label = act.get('timerLabel') or ''
            self.start('ring', text=T('say.timer_done_label', label=label) if label else T('say.timer_done'))

    def check_timer(self):
        tm = self.st.get('timer')
        if not tm or now_ms() < tm.get('end', 0):
            return

        def f(st):
            t = st.get('timer')
            if t and now_ms() >= t.get('end', 0):
                st['timer'] = None
                bump(st, 'pomodoros')
                st['activity']['timerDoneAt'] = now_ms()
                st['activity']['timerLabel'] = t.get('label', '')
        self.mutate(f)

    def check_break(self, now):
        idle = user_idle_secs()
        if idle > 300:
            self.active_since = now
        elif self.break_mins and not self.dnd and now - self.active_since > self.break_mins * 60:
            self.active_since = now
            self.notify('remind', 10, beep=True,
                        text=T('say.remind_mins', n=self.break_mins))

    def say(self, text, secs=3.5):
        self.msg = (text, time.time() + secs)

    def chatter_line(self):
        st = self.st
        h = time.localtime().tm_hour
        name = st['name']
        lines = list(T('chat.general')) + [T('chat.love', name=name)]
        if 5 <= h < 11:
            lines += T('chat.morning')
        elif 11 <= h < 14:
            lines += T('chat.noon')
        elif 14 <= h < 17:
            lines += T('chat.afternoon')
        elif 18 <= h < 23:
            lines += T('chat.evening')
        elif h >= 23 or h < 5:
            lines += T('chat.night')
        td = today_stats(st)
        if td.get('tools'):
            lines.append(T('chat.tools', n=td['tools']))
        if td.get('turns'):
            lines.append(T('chat.turns', n=td['turns']))
        if st['stats'].get('streak', 0) >= 2:
            lines.append(T('chat.streak', n=st['stats']['streak']))
        if st['hunger'] < 40:
            lines += [T('chat.hungry')] * 3
        if st['mood'] < 40:
            lines += [T('chat.bored')] * 3
        if self.ball:
            lines.append(T('chat.ball'))
        return random.choice(lines)

    # ---------- interactions
    def do_feed(self):
        def f(st):
            if st['hunger'] >= 95:
                return False
            st['hunger'] = clamp(st['hunger'] + 30, 0, 100)
            st['mood'] = clamp(st['mood'] + 5, 0, 100)
            st['fed'] += 1
            add_xp(st, 2)
            st['activity']['feedAt'] = now_ms()
            return True
        if not self.mutate(f):
            self.say(T('say.full'))

    def do_play(self):
        def f(st):
            if st['hunger'] < 15:
                return False
            st['mood'] = clamp(st['mood'] + 25, 0, 100)
            st['hunger'] = clamp(st['hunger'] - 5, 0, 100)
            st['played'] += 1
            add_xp(st, 2)
            st['activity']['playAt'] = now_ms()
            return True
        if not self.mutate(f):
            self.say(T('say.too_hungry'))

    def short_status(self):
        st = self.st
        s = T('say.status', name=st['name'], lv=level_of(st['xp']), h=int(st['hunger']), m=int(st['mood']))
        return s

    def do_status(self):
        self.say(self.short_status(), 4.5)

    def set_color(self, key):
        def f(st):
            st['color'] = key
        self.mutate(f)

    def set_accessory(self, key):
        if key == 'crown' and level_of(self.st['xp']) < 10:
            self.say(T('say.crown_locked'))
            return

        def f(st):
            st['accessory'] = key
        self.mutate(f)

    def rename(self):
        name = simpledialog.askstring(T('dlg.rename_title'), T('dlg.rename_prompt'), parent=self.root,
                             initialvalue=self.st['name'])
        if name and name.strip():
            def f(st):
                st['name'] = name.strip()[:20]
            self.mutate(f)

    def set_timer(self, mins, label=''):
        def f(st):
            if mins:
                st['timer'] = dict(end=now_ms() + int(mins * 60000), mins=mins, label=label)
                st['activity']['timerSetAt'] = now_ms()
            else:
                st['timer'] = None
        self.mutate(f)
        if not mins:
            self.say(T('say.timer_cancel'))

    def custom_timer(self):
        m = simpledialog.askinteger(T('dlg.timer_title'), T('dlg.timer_prompt'), parent=self.root,
                                    minvalue=1, maxvalue=240, initialvalue=25)
        if m:
            self.set_timer(m)

    def snooze(self, mins):
        self.snooze_until = time.time() + mins * 60
        self.peek_until = 0
        self.hide_pet()

    def toggle_ball(self):
        if self.ball:
            self.ball.destroy()
            self.ball = None
            self.say(T('say.ball_away'))
        else:
            self.ball = Ball(self, clamp(self.x + self.d * 150 * self.S, self.wa[0] + 40, self.wa[2] - 40),
                             self.gy - 200 * self.S)
            self.say(T('say.ball_out'))

    def sleep_toggle(self):
        if self.cur['name'] == 'sleep':
            self.start('yawn')
            self.queue = ['stretch']
        else:
            self.start('sleep')

    def show_achievements(self):
        if self.ach_win is not None:
            try:
                self.ach_win.destroy()
            except Exception:
                pass
        st = self.st
        w = self.ach_win = tk.Toplevel(self.root)
        w.title(T('ach.title', name=st['name']))
        w.attributes('-topmost', True)
        w.configure(bg='#FFF8F2')
        s = st['stats']
        td = today_stats(st)
        got = sum(1 for a in ACHIEVEMENTS if a['id'] in st['achievements'])
        head = T('ach.head', name=st['name'], lv=level_of(st['xp']), xp=st['xp'], tp=td.get('prompts', 0),
                 tt=td.get('tools', 0), td=td.get('turns', 0), tools=s.get('tools', 0), turns=s.get('turns', 0),
                 streak=s.get('streak', 0), best=s.get('maxStreak', 0), pets=s.get('pets', 0),
                 throws=s.get('throws', 0), kicks=s.get('kicks', 0), pomo=s.get('pomodoros', 0))
        tk.Label(w, text=head, justify='left', bg='#FFF8F2', fg='#5A3A2A', font=(FONT, 10)).pack(
            anchor='w', padx=14, pady=(12, 6))
        tk.Label(w, text=T('ach.count', got=got, total=len(ACHIEVEMENTS)), bg='#FFF8F2', fg='#D97757',
                 font=(FONT, 12, 'bold')).pack(anchor='w', padx=14)
        box = tk.Frame(w, bg='#FFF8F2')
        box.pack(fill='both', padx=14, pady=(4, 12))
        for a in ACHIEVEMENTS:
            ok = a['id'] in st['achievements']
            if ok:
                txt, fg = T('ach.row_done', name=loc(a['name']), desc=loc(a['desc'])), '#3A2A20'
            elif a.get('hidden'):
                txt, fg = T('ach.hidden'), '#B0A090'
            else:
                txt, fg = T('ach.row', name=loc(a['name']), desc=loc(a['desc']), goal=a['goal'],
                            v=min(stat_of(st, a['stat']), a['goal'])), '#9A8A7A'
            tk.Label(box, text=txt, bg='#FFF8F2', fg=fg, font=(FONT, 10), anchor='w').pack(fill='x')
        w.update_idletasks()
        w.geometry('+%d+%d' % (max(self.wa[0], int(self.x - w.winfo_width() / 2)),
                               max(self.wa[1], int(self.y - w.winfo_height() - 200 * self.S))))

    def quit(self):
        try:
            self.root.destroy()
        except Exception:
            pass

    # ---------- menu and mouse
    def build_menu(self):
        m = tk.Menu(self.root, tearoff=0)
        self.vars = {}

        def flag(menu, key, attr):
            v = self.vars[attr] = tk.BooleanVar(value=getattr(self, attr))
            menu.add_checkbutton(label=T('m.' + key), variable=v, command=lambda: self.set_flag(attr))

        m.add_command(label=T('m.pet'), command=lambda: self.start('pet'))
        m.add_command(label=T('m.feed'), command=self.do_feed)
        m.add_command(label=T('m.play'), command=self.do_play)
        tm = tk.Menu(m, tearoff=0)
        for key, _ in TRICKS:
            tm.add_command(label=T('trick.' + key), command=lambda k=key: self.start(k))
        m.add_cascade(label=T('m.tricks'), menu=tm)
        m.add_command(label=T('m.ball_out'), command=self.toggle_ball)
        self.ball_idx = m.index('end')
        m.add_command(label=T('m.status'), command=self.do_status)
        m.add_command(label=T('m.achievements'), command=self.show_achievements)
        m.add_separator()

        pm = tk.Menu(m, tearoff=0)
        for mins in (25, 50, 5):
            pm.add_command(label=T('m.mins_break' if mins == 5 else 'm.mins', n=mins),
                           command=lambda mm=mins: self.set_timer(mm, T('timer.break_label') if mm == 5 else ''))
        pm.add_command(label=T('m.custom'), command=self.custom_timer)
        pm.add_separator()
        pm.add_command(label=T('m.timer_cancel'), command=lambda: self.set_timer(0))
        m.add_cascade(label=T('m.timer'), menu=pm)
        m.add_command(label=T('m.sleep'), command=self.sleep_toggle)
        hm = tk.Menu(m, tearoff=0)
        for mins in (10, 30, 60):
            hm.add_command(label=T('m.mins', n=mins), command=lambda mm=mins: self.snooze(mm))
        m.add_cascade(label=T('m.hide_for'), menu=hm)
        m.add_separator()

        km = tk.Menu(m, tearoff=0)
        self.skin_var = tk.StringVar(value=self.skin)
        for label, v in ((T('m.skin_pixel'), 'pixel'), (T('m.skin_chibi'), 'chibi')):
            km.add_radiobutton(label=label, variable=self.skin_var, value=v, command=lambda vv=v: self.set_skin(vv))
        m.add_cascade(label=T('m.skin'), menu=km)
        cm = tk.Menu(m, tearoff=0)
        for key in SCHEMES:
            cm.add_command(label=T('color.' + key), command=lambda k=key: self.set_color(k))
        m.add_cascade(label=T('m.color'), menu=cm)
        self.color_idx = m.index('end')
        am = self.acc_menu = tk.Menu(m, tearoff=0)
        self.acc_var = tk.StringVar(value=self.st.get('accessory', 'none'))
        for key, _ in ACCESSORIES:
            am.add_radiobutton(label=T('acc.' + key), variable=self.acc_var, value=key,
                               command=lambda k=key: self.set_accessory(k))
        m.add_cascade(label=T('m.accessory'), menu=am)
        sm = tk.Menu(m, tearoff=0)
        self.size_var = tk.DoubleVar(value=self.scale_pref)
        for label, v in ((T('m.size_s'), 0.75), (T('m.size_m'), 1.0), (T('m.size_l'), 1.4), (T('m.size_xl'), 1.9)):
            sm.add_radiobutton(label=label, variable=self.size_var, value=v, command=lambda vv=v: self.apply_scale(vv))
        sm.add_separator()
        sm.add_command(label=T('m.size_hint'), state='disabled')
        m.add_cascade(label=T('m.size'), menu=sm)

        gm = tk.Menu(m, tearoff=0)
        flag(gm, 'only_claude', 'only_claude')
        flag(gm, 'peek', 'peek_on')
        flag(gm, 'sound', 'sound')
        flag(gm, 'chatter', 'chatter')
        flag(gm, 'stay', 'stay')
        flag(gm, 'follow', 'follow')
        bm = tk.Menu(gm, tearoff=0)
        self.break_var = tk.IntVar(value=self.break_mins)
        for mins in (0, 30, 45, 60, 90):
            bm.add_radiobutton(label=T('m.mins', n=mins) if mins else T('m.off'), variable=self.break_var, value=mins,
                               command=lambda mm=mins: self.set_break(mm))
        gm.add_cascade(label=T('m.break'), menu=bm)
        gm.add_separator()
        flag(gm, 'dnd', 'dnd')
        lm = tk.Menu(gm, tearoff=0)
        self.lang_var = tk.StringVar(value=self.lang_pref)
        lm.add_radiobutton(label=T('m.lang_auto'), variable=self.lang_var, value='auto',
                           command=lambda: self.set_language('auto'))
        for code, strings in STRINGS.items():
            lm.add_radiobutton(label=strings.get('lang.name', code), variable=self.lang_var, value=code,
                               command=lambda c=code: self.set_language(c))
        gm.add_cascade(label=T('m.language'), menu=lm)
        m.add_cascade(label=T('m.settings'), menu=gm)
        m.add_command(label=T('m.rename'), command=self.rename)
        m.add_separator()
        m.add_command(label=T('m.quit'), command=self.quit)
        self.menu = m

    def set_flag(self, attr):
        setattr(self, attr, self.vars[attr].get())
        self.save_prefs()
        self.say(T('f.%s.%s' % (attr, 'on' if getattr(self, attr) else 'off')))

    def set_language(self, pref):
        self.lang_pref = pref
        set_lang(pref)
        self.save_prefs()
        self.build_menu()
        self.say(T('say.lang'))

    def sync_vars(self):
        for attr, v in self.vars.items():
            v.set(getattr(self, attr))
        self.skin_var.set(self.skin)
        self.size_var.set(self.scale_pref)
        self.break_var.set(self.break_mins)
        self.acc_var.set(self.st.get('accessory', 'none'))
        self.lang_var.set(self.lang_pref)

    def on_menu(self, e):
        self.sync_vars()
        self.menu.entryconfig(self.color_idx, state='disabled' if self.skin == 'pixel' else 'normal')
        self.menu.entryconfig(self.ball_idx, label=T('m.ball_away') if self.ball else T('m.ball_out'))
        crown = [k for k, _ in ACCESSORIES].index('crown')
        locked = level_of(self.st['xp']) < 10
        self.acc_menu.entryconfig(crown, state='disabled' if locked else 'normal',
                                  label=T('m.crown_locked') if locked else T('acc.crown'))
        try:
            self.menu.tk_popup(e.x_root, e.y_root)
        finally:
            self.menu.grab_release()
        try:
            self.restore_focus()
        except Exception:
            pass

    def on_enter(self, e):
        if self.hover_since is None:
            self.hover_since = time.time()

    def on_leave(self, e):
        self.hover_since = None
        self.hover_shown = False

    def on_wheel(self, e):
        cur = min(range(len(SCALES)), key=lambda i: abs(SCALES[i] - self.scale_pref))
        i = clamp(cur + (1 if e.delta > 0 else -1), 0, len(SCALES) - 1)
        if SCALES[i] != self.scale_pref:
            self.apply_scale(SCALES[i])

    def on_press(self, e):
        self.press = (e.x_root, e.y_root, self.x, self.y)
        self.dragging = False
        self.vx = self.dvy = 0.0
        self.last_motion = time.time()

    def on_motion(self, e):
        if not self.press:
            return
        dx, dy = e.x_root - self.press[0], e.y_root - self.press[1]
        if not self.dragging and math.hypot(dx, dy) > 6:
            self.dragging = True
            self.start('held')
        if self.dragging:
            nx = self.press[2] + dx
            ny = min(self.press[3] + dy, self.gy)
            n = time.time()
            dt = max(n - self.last_motion, 0.008)
            self.vx = 0.6 * self.vx + 0.4 * ((nx - self.x) / dt)
            self.dvy = 0.6 * self.dvy + 0.4 * ((ny - self.y) / dt)
            self.last_motion = n
            self.x, self.y = nx, ny

    def on_release(self, e):
        if not self.press:
            return
        self.press = None
        if self.dragging:
            self.dragging = False
            S = self.S
            fresh = time.time() - self.last_motion < 0.08
            vx = clamp(self.vx, -2600 * S, 2600 * S) if fresh else 0.0
            vy = clamp(self.dvy, -2600 * S, 1500 * S) if fresh else 0.0
            self.vx, self.vy = vx, vy
            thrown = math.hypot(vx, vy) > 900 * S
            if self.y < self.gy - 2 or thrown:
                self.start('fall', spin=clamp(vx / (6 * S), -900, 900) if thrown else 0)
                if thrown:
                    self.mutate(lambda st: bump(st, 'throws'))
            else:
                self.vx = 0.0
                self.start('land')
            self.restore_focus()
        else:
            self.on_click()

    def on_click(self):
        n = self.cur['name']
        now = time.time()
        # Clicking the pet while it's popped up: jump straight back to Claude
        if now < self.peek_until or n in ('alert', 'ring'):
            self.peek_until = 0
            hw = find_claude_window()
            if hw:
                activate(hw)
            self.start('pet')
            return
        self.clicks = [c for c in self.clicks if now - c < 2.0] + [now]
        if n == 'sleep':
            self.start('surprise')
            self.queue = ['yawn']
        elif len(self.clicks) >= 7:
            self.clicks = []
            self.start('annoyed')
            self.mutate(lambda st: bump(st, 'annoyed'))
        elif len(self.clicks) == 4:
            self.start('jump', shout=True)
        elif n != 'annoyed':
            self.start('pet')
        bonus = now - self.last_pet_bonus > 20

        def f(st):
            bump(st, 'pets')
            if bonus:
                st['mood'] = clamp(st['mood'] + 3, 0, 100)
        if bonus:
            self.last_pet_bonus = now
        self.mutate(f)
        self.restore_focus()

    # ---------- animation scheduling
    def start(self, name, **kw):
        lo_hi = DUR.get(name)
        dur = None
        if lo_hi:
            dur = lo_hi[0] if lo_hi[0] == lo_hi[1] else random.uniform(*lo_hi)
        b = dict(name=name, t0=time.time(), dur=dur)
        b.update(kw)
        S = self.S
        if name == 'walk':
            tx = random.uniform(self.wa[0] + 60 * S, self.wa[2] - 60 * S)
            if abs(tx - self.x) < 110 * S:
                tx = clamp(self.x + random.choice((-1, 1)) * random.uniform(140, 320) * S,
                           self.wa[0] + 60 * S, self.wa[2] - 60 * S)
            b.update(tx=tx, dir=1 if tx > self.x else -1, speed=random.uniform(40, 60) * S)
            self.d = b['dir']
        elif name == 'run':
            self.dash(b)
            b['dashes'] = random.randint(1, 3)
        elif name == 'chase':
            b.update(speed=210 * S, dir=self.d)
        elif name in ('jump', 'pounce'):
            b['vx'] = kw.get('vx', (self.d * random.uniform(0, 90) * S) if name == 'jump' else 0)
            b.setdefault('shout', random.random() < 0.4)
        elif name in ('play', 'eat'):
            self.d = random.choice((-1, 1))
        elif name == 'sleep':
            b['cap'] = random.random() < 0.5   # pixel skin: nightcap half the time
        self.last_name = self.cur['name'] if getattr(self, 'cur', None) else ''
        self.cur = b

    def dash(self, b):
        S = self.S
        tx = random.uniform(self.wa[0] + 70 * S, self.wa[2] - 70 * S)
        if abs(tx - self.x) < 200 * S:
            tx = clamp(self.x + random.choice((-1, 1)) * 400 * S, self.wa[0] + 70 * S, self.wa[2] - 70 * S)
        b.update(tx=tx, dir=1 if tx > self.x else -1, speed=240 * S)
        self.d = b['dir']

    def pick(self):
        if self.busy:
            return self.start('work')
        if self.queue:
            item = self.queue.pop(0)
            return self.start(item[0], **item[1]) if isinstance(item, tuple) else self.start(item)
        st = self.st
        hunger, mood = st['hunger'], st['mood']
        hour = time.localtime().tm_hour
        w = dict(sit=3, walk=4, wave=2, look=2, yawn=1, jump=1.2, run=1, scratch=1, spin=0.6, stretch=1,
                 sleep=0.7, dance=0.4)
        if self.skin == 'pixel':
            # Everyday actions only the sprite sheet has: coffee, water, fries, flower, games, reading
            w.update(coffee=1, water=0.8, fries=0.8, flower=0.8, game=0.8, read=0.8)
        if self.ball and self.ball.held is None and abs(self.ball.x - self.x) > 60 * self.S:
            w['fetch'] = 4 if mood > 30 else 1
        if hunger < 25:
            w['hungry'] = 8
        if mood < 30:
            w['sit'] += 3
            w['sleep'] += 2
            w['jump'] = 0.2
            w['run'] = 0.2
            w['dance'] = 0
        if hour >= 23 or hour < 6:
            w['sleep'] += 3
        if mood > 80:
            w['jump'] += 0.8
            w['run'] += 0.6
            w['dance'] += 0.4
        if self.stay:
            w.pop('walk', None)
            w.pop('run', None)
            w.pop('fetch', None)
        if self.last_name in w:
            w[self.last_name] *= 0.15
        names = list(w)
        self.start(random.choices(names, weights=[w[k] for k in names])[0])

    def finish(self, b):
        n = b['name']
        if n == 'sleep':
            self.queue = ['yawn', 'stretch']
        elif n == 'yawn' and random.random() < 0.4 and not self.queue:
            self.queue = ['stretch']
        elif n == 'pounce':
            self.queue = ['pet'] if random.random() < 0.6 else []
        elif n == 'kick' and self.ball and random.random() < 0.7 and not self.queue:
            self.queue = ['fetch']
        self.pick()

    def update_behavior(self, now, dt):
        b = self.cur
        n = b['name']
        t = now - b['t0']
        S = self.S
        if n == 'held':
            return
        if n == 'fall':
            self.vy += 2400 * S * dt
            self.x += self.vx * dt
            self.y += self.vy * dt
            lo, hi = self.wa[0] + 40 * S, self.wa[2] - 40 * S
            if self.x < lo or self.x > hi:
                self.x = clamp(self.x, lo, hi)
                self.vx = -self.vx * 0.6
                b['spin'] = -b.get('spin', 0)
            if self.y < self.wa[1] + 100 * S:
                self.y = self.wa[1] + 100 * S
                self.vy = abs(self.vy) * 0.4
            if self.y >= self.gy:
                hard = self.vy > 1500 * S or abs(b.get('spin', 0)) > 400
                self.y = self.gy
                self.vy = self.vx = 0.0
                self.start('dizzy' if hard else 'land')
            return
        if self.y < self.gy - 1:
            self.y = self.gy
        if self.busy and n in CALM and n != 'work':
            self.start('work')
            return
        done = False
        if n == 'walk':
            self.x += b['dir'] * b['speed'] * dt
            done = (b['tx'] - self.x) * b['dir'] <= 0
        elif n == 'run':
            self.x += b['dir'] * b['speed'] * dt
            if (b['tx'] - self.x) * b['dir'] <= 0:
                b['dashes'] -= 1
                if b['dashes'] <= 0:
                    done = True
                else:
                    self.dash(b)
        elif n == 'chase':
            px = self.root.winfo_pointerx()
            dx = px - self.x
            b['dir'] = self.d = 1 if dx > 0 else -1
            if abs(dx) < 45 * S:
                self.start('pounce', vx=self.d * 110 * S)
                return
            self.x += b['dir'] * b['speed'] * dt
            done = t > 8
        elif n == 'fetch':
            if not self.ball:
                done = True
            else:
                dx = self.ball.x - self.x
                self.d = 1 if dx > 0 else -1
                if abs(dx) < 34 * S and self.ball.y > self.gy - 70 * S and self.ball.held is None:
                    self.ball.kick(self.d)
                    self.start('kick')
                    self.mutate(lambda st: bump(st, 'kicks'))
                    return
                self.x += self.d * 200 * S * dt
                done = t > 10
        elif n in ('jump', 'pounce'):
            u = t / b['dur']
            if 0.22 < u < 0.85:
                self.x += b['vx'] * dt
        elif n == 'work':
            done = (not self.busy) and t > 2.0
        elif n == 'sleep' and self.busy:
            done = True
        self.x = clamp(self.x, self.wa[0] + 40 * S, self.wa[2] - 40 * S)
        if b['dur'] is not None and t >= b['dur']:
            done = True
        if done:
            self.finish(b)

    # ---------- main loop
    def tick(self):
        try:
            if os.path.exists(QUIT):
                self.quit()
                return
            self.step()
        except tk.TclError:
            return
        except Exception:
            import traceback
            log('tick: %s' % traceback.format_exc())
        self.root.after(TICK_MS, self.tick)

    def step(self):
        now = time.time()
        dt = min(now - self.last, 0.1)
        self.last = now
        S = self.S

        if now > self.next_topmost:
            self.next_topmost = now + 5
            self.root.attributes('-topmost', True)
        if now > self.next_area:
            self.next_area = now + 3
            self.wa = self.work_area()
        if now > self.next_decay:
            self.next_decay = now + 30
            self.mutate(lambda st: None)
        if now > self.next_prefs:
            self.next_prefs = now + 1
            self.poll_prefs()
        if now > self.next_slow:
            self.next_slow = now + 5
            self.check_timer()
            self.check_break(now)
            try:
                with open(ALIVE, 'w') as f:
                    f.write(str(now_ms()))
            except OSError:
                pass
        if now > self.next_fg:
            self.next_fg = now + 0.25
            self.update_visibility(now)
        self.poll_state()
        if self.ball:
            self.ball.step(dt, self.wa, self.visible)
        if not self.visible:
            return

        px, py = self.root.winfo_pointerxy()
        self.cur_speed = 0.8 * self.cur_speed + 0.2 * (math.hypot(px - self.last_ptr[0], py - self.last_ptr[1]) / max(dt, 0.01))
        self.last_ptr = (px, py)
        a = self.actor
        a.look = (clamp((px - self.x) / (320 * S), -1, 1), clamp((py - (self.y - 68 * S)) / (320 * S), -1, 1))
        a.st = self.st
        a.d = self.d
        if self.cur['name'] == 'held':
            target = clamp(self.vx / (45 * S), -32, 32)
            a.swing += (target - a.swing) * min(1.0, dt * 8)
        # Besides regular actions, sometimes get distracted by the cursor
        if (self.follow and self.cur['name'] in ('sit', 'walk', 'look', 'wave', 'yawn') and
                abs(px - self.x) > 120 * S):
            self.start('chase')
        elif (not self.follow and not self.stay and now > self.chase_cool and self.cur['name'] in ('sit', 'look') and
              self.cur_speed > 900 * S and abs(px - self.x) < 500 * S and abs(py - self.y) < 260 * S):
            self.chase_cool = now + 45
            self.start('chase')

        # Mouse resting on the pet: show a small status
        if self.hover_since and not self.hover_shown and not self.press and now - self.hover_since > 1.2:
            self.hover_shown = True
            if not self.msg:
                self.say(self.short_status(), 3)
        # Chatter now and then
        if now > self.next_chatter:
            self.next_chatter = now + random.uniform(240, 480)
            if (self.chatter and not self.dnd and not self.busy and not self.msg and
                    self.cur['name'] in ('sit', 'walk', 'look')):
                self.say(self.chatter_line(), 5)

        if now > self.next_blink:
            self.blink_until = now + 0.14
            self.next_blink = now + random.uniform(2.5, 6.0)
        self.update_behavior(now, dt)
        self.apply_window()
        self.render(now)

    def apply_window(self):
        wx = int(self.x - self.WP / 2)
        wy = int(self.y - GROUND * self.S)
        if self.size_dirty:
            self.size_dirty = False
            self.root.geometry('%dx%d+%d+%d' % (self.WP, self.HP, wx, wy))
            self.lastpos = (wx, wy)
        elif (wx, wy) != self.lastpos:
            self.root.geometry('+%d+%d' % (wx, wy))
            self.lastpos = (wx, wy)

    def render(self, now):
        b = self.cur
        t = now - b['t0']
        if b['name'] == 'work':
            act = self.st.get('activity', {})
            b['cat'], label = tool_info(act.get('tool', ''))
            ts = act.get('turnStart', 0)
            b['caption'] = '%s %s' % (label, fmt_clock((now_ms() - ts) / 1000)) if ts else label
        po = self.actor.pose(b, t)
        po['acc'] = self.st.get('accessory', 'none')
        if self.msg:
            if now < self.msg[1]:
                po['fx'] = [f for f in po['fx'] if f[0] not in ('bubble', 'think')] + [('bubble', self.msg[0])]
            else:
                self.msg = None
        if now < self.blink_until and po['eyes'] in ('open', 'wide'):
            po['eyes'] = 'shut'
        self.cv.delete('all')
        if self.skin == 'pixel' and self.sprites:
            draw_pixel(self.P, po, self.colors(), self.d, t, b, self.sprites)
        else:
            draw_clawd(self.P, po, self.colors(), self.d, t)
        tm = self.st.get('timer')
        if tm:
            left = (tm.get('end', 0) - now_ms()) / 1000
            top = GROUND - po['lift'] - 84 * po['sy']
            kinds = {f[0] for f in po['fx']}
            y = top - 16 - (48 if 'think' in kinds else 40 if 'bubble' in kinds else 0)
            pill(self.P, LW / 2 + po['ox'], max(12, y), fmt_clock(left + 0.999), '#E5484D', 'tomato')

    def run(self):
        self.root.mainloop()



# ---------------------------------------------------------------- gallery (debug)
GALLERY = [('sit', 1.0), ('walk', 0.1), ('run', 0.05), ('sleep', 2.0), ('wave', 0.2), ('yawn', 1.2),
           ('stretch', 1.4), ('scratch', 0.3), ('jump', 0.15), ('jump', 0.6), ('spin', 0.35), ('look', 1.0),
           ('pet', 1.0), ('surprise', 0.2), ('land', 0.1), ('dizzy', 1.0), ('held', 1.0), ('fall', 0.3),
           ('work', 1.0), ('celebrate', 0.8), ('levelup', 1.0), ('alert', 0.8), ('hungry', 1.0),
           ('eat', 2.0), ('eat', 6.2), ('play', 1.0), ('play', 3.2), ('sit', 4.0), ('dance', 0.4),
           ('annoyed', 1.0), ('kick', 0.27), ('ring', 0.5), ('remind', 2.5), ('bye', 0.5), ('achieve', 0.7),
           ('fetch', 0.1)]
GALLERY_PIXEL_EXTRA = [('coffee', 1.0), ('water', 1.0), ('fries', 1.0), ('flower', 1.0), ('game', 1.0),
                       ('read', 1.0)]


def gallery():
    if os.name == 'nt':
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass
    set_lang(os.environ.get('GALLERY_LANG', 'en'))
    root = tk.Tk()
    root.title('gallery')
    root.geometry('+0+0')
    S = float(os.environ.get('GALLERY_S', '0.62'))
    cols = int(os.environ.get('GALLERY_COLS', '7'))
    page = int(os.environ.get('GALLERY_PAGE', '-1'))
    per = int(os.environ.get('GALLERY_PER', '12'))
    colorkeys = list(SCHEMES)
    actor = Actor()
    actor.st = dict(mood=80, hunger=80)
    pixel = os.environ.get('GALLERY_SKIN', 'chibi') == 'pixel'
    sprites = SpriteSkin.try_load(root, S) if pixel else None
    items = list(enumerate(GALLERY + (GALLERY_PIXEL_EXTRA if pixel else [])))
    if page >= 0:
        items = items[page * per:(page + 1) * per]
    for j, (i, (name, t)) in enumerate(items):
        cv = tk.Canvas(root, width=int(LW * S), height=int(LH * S), bg='#DCE8F3', highlightthickness=1,
                       highlightbackground='#9BB')
        cv.grid(row=j // cols, column=j % cols)
        P = Painter(cv, S)
        actor.d = 1 if i % 3 else -1
        actor.swing = 14
        b = dict(name=name, dur=(DUR.get(name) or (2, 2))[0], level=3, text='Little Helper')
        if name == 'work':
            b.update(cat='read' if i % 2 else 'edit', caption='Reading 1:23')
        po = actor.pose(b, t)
        po['acc'] = ACCESSORIES[i % len(ACCESSORIES)][0]
        if name == 'sit' and t > 3:
            po['eyes'] = 'shut'
        C = SCHEMES[colorkeys[i % 4]]
        if sprites:
            b['cap'] = i % 2 == 0
            draw_pixel(P, po, C, actor.d, t, b, sprites)
        else:
            draw_clawd(P, po, C, actor.d, t)
        cv.create_text(6, 6, anchor='nw', text='%s %.1f' % (name, t), font=('Consolas', 9), fill='#345')
    root.update()
    root.after(int(float(os.environ.get('GALLERY_SECS', '600')) * 1000), root.destroy)
    root.mainloop()


_claude_pids = {}


def _proc_is_claude(pid):
    """Is this process the Claude desktop app? (cached by pid)"""
    if pid in _claude_pids:
        return _claude_pids[pid]
    from ctypes import wintypes
    k = ctypes.windll.kernel32
    k.OpenProcess.restype = wintypes.HANDLE
    k.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k.CloseHandle.argtypes = [wintypes.HANDLE]
    ok = False
    h = k.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if h:
        try:
            buf = ctypes.create_unicode_buffer(1024)
            n = wintypes.DWORD(1024)
            if k.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)):
                p = buf.value.lower()
                # The desktop app is claude.exe; the Claude Code CLI is too, but it lives in a claude-code folder with no window
                ok = os.path.basename(p) == 'claude.exe' and 'claude-code' not in p
        finally:
            k.CloseHandle(h)
    if len(_claude_pids) > 500:
        _claude_pids.clear()
    _claude_pids[pid] = ok
    return ok


# Walking up from a Claude Code process stops at these, so e.g. Explorer never counts as "Claude"
_HOST_STOP = {'explorer.exe', 'svchost.exe', 'services.exe', 'wininit.exe', 'winlogon.exe', 'sihost.exe',
              'runtimebroker.exe', 'userinit.exe', 'taskhostw.exe', 'dllhost.exe', 'system', 'smss.exe',
              'csrss.exe', 'lsass.exe'}
# Terminals and editors that can host the Claude Code CLI
_TERMINALS = {'windowsterminal.exe', 'openconsole.exe', 'conhost.exe', 'cmd.exe', 'powershell.exe', 'pwsh.exe',
              'wezterm-gui.exe', 'alacritty.exe', 'mintty.exe', 'hyper.exe', 'tabby.exe', 'warp.exe',
              'code.exe', 'code - insiders.exe', 'cursor.exe', 'windsurf.exe', 'zed.exe', 'idea64.exe',
              'pycharm64.exe', 'webstorm64.exe', 'rider64.exe', 'goland64.exe', 'clion64.exe', 'phpstorm64.exe'}
_hosts_cache = {'t': 0.0, 'hosts': frozenset(), 'names': {}, 'cli': False}


def _proc_path(pid):
    from ctypes import wintypes
    k = ctypes.windll.kernel32
    k.OpenProcess.restype = wintypes.HANDLE
    k.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k.CloseHandle.argtypes = [wintypes.HANDLE]
    h = k.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return ''
    try:
        buf = ctypes.create_unicode_buffer(1024)
        n = wintypes.DWORD(1024)
        return buf.value.lower() if k.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)) else ''
    finally:
        k.CloseHandle(h)


def _is_desktop_app_path(p):
    return 'windowsapps' in p or 'anthropicclaude' in p


def _scan_claude():
    """Refresh (at most every 2 s) the PIDs of every claude.exe plus the processes it runs inside (shell,
    terminal, editor...), and whether a standalone Claude Code CLI is running."""
    c = _hosts_cache
    now = time.time()
    if now - c['t'] < 2.0:
        return c
    hosts, names, cli = set(), {}, False
    try:
        from ctypes import wintypes

        class PROCESSENTRY32W(ctypes.Structure):
            _fields_ = [('dwSize', wintypes.DWORD), ('cntUsage', wintypes.DWORD),
                        ('th32ProcessID', wintypes.DWORD), ('th32DefaultHeapID', ctypes.c_size_t),
                        ('th32ModuleID', wintypes.DWORD), ('cntThreads', wintypes.DWORD),
                        ('th32ParentProcessID', wintypes.DWORD), ('pcPriClassBase', ctypes.c_long),
                        ('dwFlags', wintypes.DWORD), ('szExeFile', ctypes.c_wchar * 260)]
        k = ctypes.windll.kernel32
        k.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        k.CloseHandle.argtypes = [wintypes.HANDLE]
        snap = k.CreateToolhelp32Snapshot(0x2, 0)  # TH32CS_SNAPPROCESS
        procs = {}
        try:
            e = PROCESSENTRY32W()
            e.dwSize = ctypes.sizeof(e)
            ok = k.Process32FirstW(snap, ctypes.byref(e))
            while ok:
                procs[e.th32ProcessID] = (e.th32ParentProcessID, e.szExeFile.lower())
                ok = k.Process32NextW(snap, ctypes.byref(e))
        finally:
            k.CloseHandle(snap)
        names = {pid: exe for pid, (_, exe) in procs.items()}
        for pid, (ppid, exe) in procs.items():
            if exe != 'claude.exe':
                continue
            # A CLI started from a terminal: its parent isn't the desktop app, and it isn't the desktop app itself
            if procs.get(ppid, (0, ''))[1] != 'claude.exe' and not _is_desktop_app_path(_proc_path(pid)):
                cli = True
            hosts.add(pid)
            for _ in range(12):
                if ppid not in procs or ppid in hosts or procs[ppid][1] in _HOST_STOP:
                    break
                hosts.add(ppid)
                ppid = procs[ppid][0]
    except Exception:
        pass
    c.update(t=now, hosts=frozenset(hosts), names=names, cli=cli)
    return c


def claude_hosts():
    return _scan_claude()['hosts']


def _is_claude_window_pid(pid):
    """Does this window's process count as Claude? The desktop app, anything Claude Code runs inside, or
    (while a Claude Code CLI is running) any terminal / editor, since a terminal tab can't be traced reliably."""
    if _proc_is_claude(pid):
        return True
    c = _scan_claude()
    return pid in c['hosts'] or (c['cli'] and c['names'].get(pid, '') in _TERMINALS)


def _hwnd_pid(hwnd):
    from ctypes import wintypes
    u = ctypes.windll.user32
    u.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    pid = wintypes.DWORD()
    u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def foreground():
    """(foreground hwnd, pid); None outside Windows."""
    if os.name != 'nt':
        return None
    try:
        from ctypes import wintypes
        u = ctypes.windll.user32
        u.GetForegroundWindow.restype = wintypes.HWND
        hwnd = u.GetForegroundWindow()
        return (hwnd, _hwnd_pid(hwnd)) if hwnd else None
    except Exception:
        return None


def foreground_is_claude():
    """Is the foreground window Claude: the desktop app, a terminal / editor running Claude Code,
    or the pet itself (e.g. while clicked or showing its menu)?"""
    if os.name != 'nt':
        return True
    try:
        fg = foreground()
        if not fg:
            return False
        return fg[1] == os.getpid() or _is_claude_window_pid(fg[1])
    except Exception:
        return True


def find_claude_window():
    """Find the topmost window running Claude (desktop app, or a terminal / editor with Claude Code in it)."""
    if os.name != 'nt':
        return None
    try:
        from ctypes import wintypes
        u = ctypes.windll.user32
        u.GetWindow.restype = wintypes.HWND
        u.GetWindow.argtypes = [wintypes.HWND, ctypes.c_uint]
        found = []
        proto = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def cb(hwnd, _):
            if (u.IsWindowVisible(hwnd) and not u.GetWindow(hwnd, 4) and u.GetWindowTextLengthW(hwnd) > 0
                    and _is_claude_window_pid(_hwnd_pid(hwnd))):
                found.append(hwnd)
                return False
            return True
        u.EnumWindows(proto(cb), 0)
        return found[0] if found else None
    except Exception:
        return None


def activate(hwnd):
    """Bring a window to the front (restoring it if minimized)."""
    if os.name != 'nt' or not hwnd:
        return
    try:
        from ctypes import wintypes
        u = ctypes.windll.user32
        u.SetForegroundWindow.argtypes = [wintypes.HWND]
        u.IsIconic.argtypes = [wintypes.HWND]
        u.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        if u.IsIconic(hwnd):
            u.ShowWindow(hwnd, 9)  # SW_RESTORE
        if not u.SetForegroundWindow(hwnd):
            # Foreground lock: tap Alt and try again
            u.keybd_event(0x12, 0, 0, 0)
            u.keybd_event(0x12, 0, 2, 0)
            u.SetForegroundWindow(hwnd)
    except Exception:
        pass


def user_idle_secs():
    """How long since the user last touched the keyboard or mouse (seconds)."""
    if os.name != 'nt':
        return 0
    try:
        class LASTINPUTINFO(ctypes.Structure):
            _fields_ = [('cbSize', ctypes.c_uint), ('dwTime', ctypes.c_uint)]
        li = LASTINPUTINFO()
        li.cbSize = ctypes.sizeof(li)
        if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(li)):
            return 0
        return ((ctypes.windll.kernel32.GetTickCount() - li.dwTime) & 0xFFFFFFFF) / 1000.0
    except Exception:
        return 0



def single_instance():
    if os.name != 'nt':
        return True, None
    k = ctypes.windll.kernel32
    h = k.CreateMutexW(None, False, 'Local\\ClaudePetDesktopCat')
    return k.GetLastError() != 183, h


def main():
    args = sys.argv[1:]
    if '--gallery' in args:
        return gallery()
    ok, _mutex = single_instance()
    if not ok:
        return
    force = args[args.index('--force') + 1] if '--force' in args else None
    try:
        PetApp(force).run()
    except Exception:
        import traceback
        log('fatal: %s' % traceback.format_exc())


if __name__ == '__main__':
    main()
