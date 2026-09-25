#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Render the README demo GIFs and the social preview image (docs/media/).

Frames are drawn with the same pose / drawing code as the real pet, on an opaque window, and advanced with a
fixed time step so the output is deterministic. Requires Pillow (pip install pillow).

Usage:
  python tools/make_media.py                    render everything
  MEDIA_LANG=zh-TW python tools/make_media.py   render the GIFs in another language
"""
import ctypes
import math
import os
import sys
import tkinter as tk

from PIL import Image, ImageChops, ImageDraw, ImageFont, ImageGrab

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'claude-pet', 'scripts'))
import pet_window as pw  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'docs', 'media')
FPS = 12
BG = '#FBF7F2'
FLOOR = '#E9DFD3'


def scene_hero():
    """Pixel Clawd reacting to Claude Code."""
    return [
        dict(name='walk', secs=2.2, move=(-70, 0)),
        dict(name='work', secs=3.2, cat='edit', tool=pw.T('tool.edit'), clock=(41, 44)),
        dict(name='work', secs=2.2, cat='read', tool=pw.T('tool.grep'), clock=(44, 46)),
        dict(name='celebrate', secs=3.0, text=pw.T('b.done_time', time='2:13')),
        dict(name='alert', secs=2.4),
        dict(name='dance', secs=3.0, acc='party'),
    ]


def scene_chibi():
    """Chibi Clawd: accessories, tricks and the pomodoro timer."""
    return [
        dict(name='wave', secs=2.0, acc='bow', color='orange'),
        dict(name='pet', secs=1.8, acc='bow', color='orange'),
        dict(name='fall', secs=1.1, spin=520, color='blue', acc='sprout', lift=(0, 90, 0)),
        dict(name='dizzy', secs=1.6, color='blue', acc='sprout'),
        dict(name='annoyed', secs=2.0, color='green', acc='party'),
        dict(name='ring', secs=2.6, color='purple', acc='crown', text=pw.T('say.timer_done')),
        dict(name='dance', secs=2.6, color='orange', acc='crown'),
    ]


def render(root, cv, S, skin, sprites, scenes, path):
    P = pw.Painter(cv, S)
    actor = pw.Actor()
    actor.st = dict(mood=80, hunger=80)
    frames = []
    for sc in scenes:
        n = int(sc['secs'] * FPS)
        for i in range(n):
            t = i / FPS
            u = i / max(1, n - 1)
            b = dict(name=sc['name'], dur=(pw.DUR.get(sc['name']) or (sc['secs'], 0))[0], t0=0)
            for k in ('cat', 'text', 'spin'):
                if k in sc:
                    b[k] = sc[k]
            if 'clock' in sc:
                a, z = sc['clock']
                b['caption'] = '%s %s' % (sc['tool'], pw.fmt_clock(a + (z - a) * u))
            actor.d = 1
            actor.look = (0.3 * math.sin(t * 0.9), 0.1)
            po = actor.pose(b, t)
            if 'move' in sc:
                po['ox'] = sc['move'][0] + (sc['move'][1] - sc['move'][0]) * u
            if 'lift' in sc:
                l0, l1, l2 = sc['lift']
                po['lift'] = l1 * math.sin(math.pi * u) + l0 * (1 - u) + l2 * u
            po['acc'] = sc.get('acc', 'none')
            C = pw.SCHEMES[sc.get('color', 'orange')]
            cv.delete('all')
            cv.create_rectangle(0, 0, pw.LW * S + 2, pw.LH * S + 2, fill=BG, outline='')
            cv.create_rectangle(0, (pw.GROUND + 1) * S, pw.LW * S + 2, pw.LH * S + 2, fill=FLOOR, outline='')
            if skin == 'pixel':
                pw.draw_pixel(P, po, C, 1, t, b, sprites)
            else:
                pw.draw_clawd(P, po, C, 1, t)
            root.update()
            x, y = cv.winfo_rootx(), cv.winfo_rooty()
            frames.append(ImageGrab.grab(bbox=(x, y, x + int(pw.LW * S), y + int(pw.LH * S))).convert('RGB'))
    pal = [f.quantize(colors=128, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE) for f in frames]
    pal[0].save(path, save_all=True, append_images=pal[1:], duration=int(1000 / FPS), loop=0, optimize=True,
                disposal=1)
    print('%s: %d frames, %.0f KB' % (os.path.basename(path), len(frames), os.path.getsize(path) / 1024))
    return frames


def social(frames_hero, frames_chibi, path):
    """1280x640 image for GitHub's social preview (upload it in the repo's Settings > Social preview)."""
    W, H = 1280, 640
    floor = 500
    img = Image.new('RGB', (W, H), BG)
    d = ImageDraw.Draw(img)
    d.rectangle((0, floor, W, H), fill=FLOOR)

    def font(size, bold=False, cjk=False):
        names = ['msjhbd.ttc' if bold else 'msjh.ttc'] if cjk else []
        names += ['seguisb.ttf' if bold else 'segoeui.ttf', 'arial.ttf']
        for name in names:
            try:
                return ImageFont.truetype(name, size)
            except OSError:
                continue
        return ImageFont.load_default()
    # Paste the central strip of two frames so their floor lines up with ours
    for fr, x in ((frames_hero[int(len(frames_hero) * 0.62)], 690), (frames_chibi[int(len(frames_chibi) * 0.05)], 960)):
        w, h = fr.size
        ground = int((pw.GROUND + 1) * h / pw.LH)
        strip = fr.crop((w // 2 - 150, 0, w // 2 + 150, ground))
        strip = strip.resize((int(strip.width * 1.25), int(strip.height * 1.25)), Image.LANCZOS)
        # Only paste pixels that differ from the background, so the two pets never cover each other
        diff = ImageChops.difference(strip, Image.new('RGB', strip.size, BG)).convert('L')
        img.paste(strip, (x, floor - strip.height), diff.point(lambda v: 255 if v > 12 else 0))
    # Text last: the pasted frames have the same background color, so the text stays on top
    d.text((70, 110), 'claude-pet', font=font(96, True), fill='#3A2A20')
    d.text((74, 228), 'A desktop pet for Claude Code', font=font(42), fill='#8E4128')
    d.text((74, 290), 'Reacts to Claude  ·  Pomodoro  ·  Achievements', font=font(30), fill='#6B5A4E')
    d.text((74, 336), 'English / 繁體中文  ·  Unofficial fan project', font=font(26, cjk=True), fill='#9A8A7A')
    img.save(path)
    print('%s: %.0f KB' % (os.path.basename(path), os.path.getsize(path) / 1024))


def main():
    if os.name == 'nt':
        ctypes.windll.user32.SetProcessDPIAware()
    pw.set_lang(os.environ.get('MEDIA_LANG', 'en'))
    pw.SHADOW_COLOR = '#DDD2C6'
    os.makedirs(OUT, exist_ok=True)
    root = tk.Tk()
    root.overrideredirect(True)
    root.attributes('-topmost', True)
    root.geometry('+40+40')
    S = 1.4
    cv = tk.Canvas(root, width=int(pw.LW * S), height=int(pw.LH * S), highlightthickness=0, bd=0, bg=BG)
    cv.pack()
    root.update()
    sprites = pw.SpriteSkin.try_load(root, S)
    suffix = '' if pw.LANG == 'en' else '-' + pw.LANG
    hero = render(root, cv, S, 'pixel', sprites, scene_hero(), os.path.join(OUT, 'demo%s.gif' % suffix))
    chibi = render(root, cv, S, 'chibi', sprites, scene_chibi(), os.path.join(OUT, 'chibi%s.gif' % suffix))
    if not suffix:
        social(hero, chibi, os.path.join(OUT, 'social-preview.png'))
    root.destroy()


if __name__ == '__main__':
    main()
