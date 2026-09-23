#!/usr/bin/env node
// Claude Pet: CLI and hook entry point. State lives in ~/.claude/pet/state.json (override with CLAUDE_PET_DIR).
// The desktop Clawd is drawn by pet_window.py (tkinter); both sides talk through state.json / prefs.json.
const fs = require('fs');
const os = require('os');
const path = require('path');
const { spawn, execFileSync } = require('child_process');

const DIR = process.env.CLAUDE_PET_DIR || path.join(os.homedir(), '.claude', 'pet');
const FILE = path.join(DIR, 'state.json');
const PREFS = path.join(DIR, 'prefs.json');
const QUIT = path.join(DIR, 'quit');
const WINDOW_PY = path.join(__dirname, 'pet_window.py');

const HUNGER_DECAY_PER_HOUR = 4;
const MOOD_DECAY_PER_HOUR = 2;
const BUSY_MS = 120000;
const COLORS = ['orange', 'blue', 'green', 'purple'];
const ACCESSORIES = ['none', 'party', 'bow', 'sprout', 'crown'];
const TRICKS = ['dance', 'spin', 'jump', 'wave', 'stretch', 'sleep'];

const readJson = (file, fallback) => {
  try {
    return JSON.parse(fs.readFileSync(file, 'utf8'));
  } catch {
    return fallback;
  }
};
const ACHIEVEMENTS = readJson(path.join(__dirname, 'achievements.json'), []);
const STRINGS = readJson(path.join(__dirname, 'lang.json'), { en: {} });

// Window preferences that can be flipped with /pet <name> on|off
const TOGGLES = {
  focus: { pref: 'only_claude', def: true },
  peek: { pref: 'peek', def: true },
  sound: { pref: 'sound', def: true },
  chatter: { pref: 'chatter', def: true },
  stay: { pref: 'stay', def: false },
  follow: { pref: 'follow', def: false },
  dnd: { pref: 'dnd', def: false },
};

// ---- i18n (strings are shared with the desktop window through lang.json)
function detectLang() {
  let loc = '';
  try {
    loc = Intl.DateTimeFormat().resolvedOptions().locale || '';
  } catch {}
  loc = loc || process.env.LANG || '';
  return /^zh/i.test(loc) ? 'zh-TW' : 'en';
}

function resolveLang(pref) {
  return STRINGS[pref] ? pref : detectLang();
}

let LANG = resolveLang(getPrefs().lang);

function t(key, vars = {}) {
  const s = (STRINGS[LANG] && STRINGS[LANG][key]) ?? STRINGS.en[key] ?? key;
  return String(s).replace(/\{(\w+)\}/g, (m, k) => (k in vars ? vars[k] : m));
}

const loc = (v) => (typeof v === 'string' ? v : v[LANG] || v.en || '');

const clamp = (n, lo = 0, hi = 100) => Math.max(lo, Math.min(hi, n));
const levelOf = (xp) => Math.floor(Math.sqrt(xp / 10)) + 1;
const xpForLevel = (lv) => (lv - 1) * (lv - 1) * 10;
const pad2 = (n) => String(n).padStart(2, '0');
const dayKey = (d = new Date()) => `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`;
const list = (keys, prefix) => keys.map((k) => `${k} (${t(prefix + k)})`).join(t('cli.sep'));

function fmtDur(ms) {
  const s = Math.max(0, Math.round(ms / 1000));
  if (s < 60) return t('dur.s', { s });
  if (s < 3600) return t('dur.ms', { m: Math.floor(s / 60), s: s % 60 });
  return t('dur.hm', { h: Math.floor(s / 3600), m: Math.floor((s % 3600) / 60) });
}

function load() {
  const p = readJson(FILE, {});
  const now = Date.now();
  return normalize({
    name: 'Clawd',
    color: 'orange',
    accessory: 'none',
    born: now,
    xp: 0,
    hunger: 80,
    mood: 80,
    lastTick: now,
    fed: 0,
    played: 0,
    autostart: true,
    timer: null,
    ...p,
    activity: p.activity || {},
    stats: p.stats || {},
    achievements: p.achievements || {},
  });
}

function normalize(p) {
  if (!COLORS.includes(p.color)) p.color = 'orange';
  if (!ACCESSORIES.includes(p.accessory)) p.accessory = 'none';
  return p;
}

function save(p) {
  fs.mkdirSync(DIR, { recursive: true });
  const tmp = `${FILE}.tmp${process.pid}`;
  fs.writeFileSync(tmp, JSON.stringify(p, null, 2));
  fs.renameSync(tmp, FILE);
}

// Hunger and mood drop with the time you've been away
function tick(p) {
  const now = Date.now();
  const hours = Math.max(0, (now - p.lastTick) / 3600000);
  p.hunger = clamp(p.hunger - hours * HUNGER_DECAY_PER_HOUR);
  p.mood = clamp(p.mood - hours * MOOD_DECAY_PER_HOUR);
  p.lastTick = now;
}

function addXp(p, n) {
  const before = levelOf(p.xp);
  p.xp += n;
  const after = levelOf(p.xp);
  if (after > before) {
    p.activity.levelUpAt = Date.now();
    p.activity.levelUpTo = after;
    return after;
  }
  return 0;
}

// ---- Stats and achievements (defined in achievements.json, also read by the window)
const bump = (p, key, n = 1) => (p.stats[key] = (p.stats[key] || 0) + n);
const bumpToday = (p, key) => (p.stats.today[key] = (p.stats.today[key] || 0) + 1);

function touchDay(p) {
  const s = p.stats;
  const today = dayKey();
  if (s.lastDay !== today) {
    const y = new Date();
    y.setDate(y.getDate() - 1);
    s.streak = s.lastDay === dayKey(y) ? (s.streak || 0) + 1 : 1;
    s.maxStreak = Math.max(s.maxStreak || 0, s.streak);
    s.lastDay = today;
  }
  if (!s.today || s.today.date !== today) s.today = { date: today, prompts: 0, tools: 0, turns: 0 };
}

function statOf(p, key) {
  if (key === 'level') return levelOf(p.xp);
  if (key === 'fed' || key === 'played') return p[key] || 0;
  return p.stats[key] || 0;
}

function checkAchievements(p) {
  const fresh = ACHIEVEMENTS.filter((a) => !p.achievements[a.id] && statOf(p, a.stat) >= a.goal);
  for (const a of fresh) p.achievements[a.id] = Date.now();
  if (fresh.length) {
    p.activity.achieveAt = Date.now();
    p.activity.achieveIds = fresh.map((a) => a.id);
  }
  return fresh;
}

const bar = (v) => '█'.repeat(Math.round(v / 10)) + '░'.repeat(10 - Math.round(v / 10));

function timerLine(p) {
  const tm = p.timer;
  if (!tm) return '';
  const left = tm.end - Date.now();
  const label = tm.label ? t('cli.timer_label', { label: tm.label }) : '';
  return left > 0 ? t('cli.timer_left', { label, left: fmtDur(left) }) : t('cli.timer_up', { label });
}

function summary(p) {
  const lv = levelOf(p.xp);
  const days = Math.max(1, Math.ceil((Date.now() - p.born) / 86400000));
  const streak = p.stats.streak > 1 ? t('cli.streak', { n: p.stats.streak }) : '';
  const got = ACHIEVEMENTS.filter((a) => p.achievements[a.id]).length;
  const lines = [
    t('cli.status_head', { name: p.name, lv, days, streak }),
    `${t('cli.food')}${bar(p.hunger)} ${Math.round(p.hunger)}`,
    `${t('cli.mood')}${bar(p.mood)} ${Math.round(p.mood)}`,
    t('cli.xp', {
      cur: p.xp - xpForLevel(lv),
      need: xpForLevel(lv + 1) - xpForLevel(lv),
      xp: p.xp,
      fed: p.fed,
      played: p.played,
    }),
    t('cli.ach_count', { got, total: ACHIEVEMENTS.length }),
  ];
  const tl = timerLine(p);
  if (tl) lines.push(tl);
  return lines.join('\n');
}

function statsText(p) {
  const s = p.stats;
  const td = s.today && s.today.date === dayKey() ? s.today : {};
  return t('cli.stats', {
    tp: td.prompts || 0,
    tt: td.tools || 0,
    td: td.turns || 0,
    sessions: s.sessions || 0,
    prompts: s.prompts || 0,
    tools: s.tools || 0,
    turns: s.turns || 0,
    longest: fmtDur((s.longestTurnSec || 0) * 1000),
    fed: p.fed,
    played: p.played,
    pets: s.pets || 0,
    throws: s.throws || 0,
    kicks: s.kicks || 0,
    pomo: s.pomodoros || 0,
    streak: s.streak || 0,
    best: s.maxStreak || 0,
  });
}

function achievementsText(p) {
  const got = ACHIEVEMENTS.filter((a) => p.achievements[a.id]).length;
  const rows = ACHIEVEMENTS.map((a) => {
    const name = loc(a.name);
    const desc = loc(a.desc);
    if (p.achievements[a.id]) return t('ach.row_done', { name, desc });
    if (a.hidden) return t('cli.ach_hidden');
    return t('ach.row', { name, desc, v: Math.min(statOf(p, a.stat), a.goal), goal: a.goal });
  });
  return [t('cli.ach_count', { got, total: ACHIEVEMENTS.length }), ...rows].join('\n');
}

// Window preferences (the desktop window polls this file)
function getPrefs() {
  return readJson(PREFS, {});
}

function setPref(key, value) {
  const prefs = getPrefs();
  prefs[key] = value;
  fs.mkdirSync(DIR, { recursive: true });
  const tmp = `${PREFS}.tmp${process.pid}`;
  fs.writeFileSync(tmp, JSON.stringify(prefs, null, 2));
  fs.renameSync(tmp, PREFS);
}

const prefOn = (prefs, tg) => (prefs[tg.pref] === undefined ? tg.def : !!prefs[tg.pref]);
const onOffText = (v) => t(v ? 'cli.on' : 'cli.off');

function settingsText() {
  const prefs = getPrefs();
  const rows = Object.entries(TOGGLES).map(
    ([k, tg]) => `${prefOn(prefs, tg) ? '●' : '○'} ${k.padEnd(8)}${t('toggle.' + k)}`
  );
  const br = prefs.break_mins === undefined ? 60 : prefs.break_mins;
  const state = br ? t('cli.break_row_on', { n: br }) : t('cli.off');
  rows.push(`${br ? '●' : '○'} ${'break'.padEnd(8)}${t('cli.break_row', { state })}`);
  rows.push(`● ${'lang'.padEnd(8)}${langName(prefs.lang)}`);
  return [t('cli.settings_head'), ...rows].join('\n');
}

function langName(pref) {
  return STRINGS[pref] ? STRINGS[pref]['lang.name'] : t('cli.lang_auto', { lang: STRINGS[detectLang()]['lang.name'] });
}

// ---- Desktop window
function findPython() {
  for (const exe of ['pythonw', 'pyw', 'python']) {
    try {
      const out = execFileSync('where', [exe], { encoding: 'utf8', windowsHide: true, stdio: ['ignore', 'pipe', 'ignore'] });
      const first = out.split(/\r?\n/)[0].trim();
      if (first) return first;
    } catch {}
  }
  return null;
}

function launchDesktop() {
  const py = findPython();
  if (!py) return false;
  try {
    fs.rmSync(QUIT, { force: true });
    const child = spawn(py, [WINDOW_PY], { detached: true, stdio: 'ignore', windowsHide: true });
    child.on('error', () => {});
    child.unref();
    return true;
  } catch {
    return false;
  }
}

function hideDesktop() {
  fs.mkdirSync(DIR, { recursive: true });
  fs.writeFileSync(QUIT, String(Date.now()));
}

function helpText() {
  return t('help', {
    tricks: TRICKS.join(' / '),
    colors: COLORS.join(' / '),
    accs: ACCESSORIES.join(' / '),
    toggles: Object.keys(TOGGLES).join(' / '),
  });
}

// ---- Commands
function onOff(v) {
  v = (v || '').toLowerCase();
  if (['on', 'true', '1', '開'].includes(v)) return true;
  if (['off', 'false', '0', '關'].includes(v)) return false;
  return null;
}

function command(cmd, args) {
  const p = load();
  tick(p);
  let note = '';
  let showSummary = true;
  cmd = (cmd || '').toLowerCase();

  switch (cmd) {
    case 'feed':
      if (p.hunger >= 95) {
        note = t('cli.full', { name: p.name });
      } else {
        p.hunger = clamp(p.hunger + 30);
        p.mood = clamp(p.mood + 5);
        p.fed++;
        const up = addXp(p, 2);
        p.activity.feedAt = Date.now();
        note = t('cli.fed', { name: p.name }) + (up ? '\n' + t('cli.levelup', { lv: up }) : '');
      }
      break;
    case 'play':
      if (p.hunger < 15) {
        note = t('cli.too_hungry', { name: p.name });
      } else {
        p.mood = clamp(p.mood + 25);
        p.hunger = clamp(p.hunger - 5);
        p.played++;
        const up = addXp(p, 2);
        p.activity.playAt = Date.now();
        note = t('cli.played', { name: p.name }) + (up ? '\n' + t('cli.levelup', { lv: up }) : '');
      }
      break;
    case 'name': {
      const n = args.join(' ').trim().slice(0, 20);
      if (!n) note = t('cli.name_usage');
      else {
        p.name = n;
        note = t('cli.renamed', { name: n });
      }
      break;
    }
    case 'color': {
      const c = (args[0] || '').toLowerCase();
      if (!COLORS.includes(c)) note = t('cli.colors', { list: list(COLORS, 'color.') });
      else {
        p.color = c;
        note = t('cli.color_set', { color: t('color.' + c) });
      }
      break;
    }
    case 'hat':
    case 'accessory': {
      const a = (args[0] || '').toLowerCase();
      if (!ACCESSORIES.includes(a)) {
        note = t('cli.acc_list', { cur: t('acc.' + p.accessory), list: list(ACCESSORIES, 'acc.') });
      } else if (a === 'crown' && levelOf(p.xp) < 10) {
        note = t('cli.crown_locked', { lv: levelOf(p.xp) });
      } else {
        p.accessory = a;
        note = a === 'none' ? t('cli.acc_none') : t('cli.acc_set', { acc: t('acc.' + a) });
      }
      break;
    }
    case 'skin': {
      const v = (args[0] || '').toLowerCase();
      if (v === 'pixel' || v === 'chibi') {
        setPref('skin', v);
        note = t(v === 'pixel' ? 'cli.skin_pixel' : 'cli.skin_chibi');
      } else {
        note = t('cli.skin_cur', { skin: t(getPrefs().skin === 'chibi' ? 'cli.skin_chibi_name' : 'cli.skin_pixel_name') });
      }
      break;
    }
    case 'lang':
    case 'language': {
      const v = args[0] || '';
      const pick = v.toLowerCase() === 'auto' ? 'auto' : Object.keys(STRINGS).find((k) => k.toLowerCase() === v.toLowerCase());
      if (pick) {
        setPref('lang', pick);
        LANG = resolveLang(pick);
        note = t('cli.lang_set', { lang: langName(pick) });
      } else {
        note = t('cli.lang_cur', { lang: langName(getPrefs().lang) });
      }
      showSummary = false;
      break;
    }
    case 'trick': {
      const tr = (args[0] || '').toLowerCase();
      if (!TRICKS.includes(tr)) note = t('cli.tricks', { list: list(TRICKS, 'trick.') });
      else {
        p.activity.trickAt = Date.now();
        p.activity.trick = tr;
        note = t('cli.trick', { name: p.name, trick: t('trick.' + tr).toLowerCase() });
      }
      showSummary = false;
      break;
    }
    case 'say': {
      const s = args.join(' ').trim().slice(0, 40);
      if (!s) note = t('cli.say_usage');
      else {
        p.activity.sayAt = Date.now();
        p.activity.sayText = s;
        note = t('cli.say', { name: p.name, text: s });
      }
      showSummary = false;
      break;
    }
    case 'timer':
    case 'pomodoro': {
      const a = (args[0] || '').toLowerCase();
      if (['off', 'stop', 'cancel', '取消'].includes(a)) {
        note = t(p.timer ? 'cli.timer_cancel' : 'cli.timer_none');
        p.timer = null;
      } else if (a) {
        const m = Number(a);
        if (!Number.isFinite(m) || m < 1 || m > 240) note = t('cli.timer_usage');
        else {
          const label = args.slice(1).join(' ').trim().slice(0, 16);
          p.timer = { end: Date.now() + m * 60000, mins: m, label };
          p.activity.timerSetAt = Date.now();
          note = t('cli.timer_set', { n: m, label: label ? t('cli.timer_label', { label }) : '', name: p.name });
        }
      } else {
        note = timerLine(p) || t('cli.timer_none_usage');
      }
      showSummary = false;
      break;
    }
    case 'stats':
      note = statsText(p);
      showSummary = false;
      break;
    case 'achievements':
    case 'ach':
      note = achievementsText(p);
      showSummary = false;
      break;
    case 'settings':
      note = settingsText();
      showSummary = false;
      break;
    case 'break': {
      const a = (args[0] || '').toLowerCase();
      const m = Number(a);
      if (onOff(a) === false) {
        setPref('break_mins', 0);
        note = t('cli.break_off');
      } else if (Number.isFinite(m) && m >= 10 && m <= 240) {
        setPref('break_mins', m);
        note = t('cli.break_set', { n: m, name: p.name });
      } else {
        const cur = getPrefs().break_mins;
        note = t('cli.break_cur', { cur: cur === 0 ? t('cli.off') : t('cli.break_every', { n: cur || 60 }) });
      }
      showSummary = false;
      break;
    }
    case 'show':
      note = t(launchDesktop() ? 'cli.show' : 'cli.no_python');
      break;
    case 'hide':
      hideDesktop();
      note = t('cli.hide');
      break;
    case 'autostart': {
      const v = onOff(args[0]);
      if (v !== null) {
        p.autostart = v;
        note = t('cli.autostart_set', { will: t(p.autostart ? 'cli.will' : 'cli.wont') });
      } else {
        note = t('cli.autostart_cur', { will: t(p.autostart ? 'cli.will' : 'cli.wont') });
      }
      break;
    }
    case 'help':
    case '?':
      note = helpText();
      showSummary = false;
      break;
    case 'status':
    case '':
      break;
    default:
      if (TOGGLES[cmd]) {
        const tg = TOGGLES[cmd];
        const v = onOff(args[0]);
        if (v !== null) setPref(tg.pref, v);
        const on = v !== null ? v : prefOn(getPrefs(), tg);
        note = t('cli.toggle', { label: t('toggle.' + cmd), state: onOffText(on) });
        if (v === null) note += '\n' + t('cli.toggle_usage', { cmd });
      } else {
        note = t('cli.unknown', { cmd }) + '\n\n' + helpText();
      }
      showSummary = false;
  }

  const fresh = checkAchievements(p);
  if (fresh.length) note += '\n\n' + t('cli.new_ach', { list: fresh.map((a) => loc(a.name)).join(t('cli.sep')) });
  save(p);
  console.log(showSummary ? summary(p) + (note ? `\n\n${note}` : '') : note.trim());
}

// ---- Hook events
function readInput() {
  try {
    return JSON.parse(fs.readFileSync(0, 'utf8') || '{}');
  } catch {
    return {};
  }
}

function hook(event) {
  const input = readInput(); // always drain stdin to avoid a broken pipe
  const p = load();
  tick(p);
  const now = Date.now();
  const act = p.activity;
  let msg = '';
  touchDay(p);

  if (event === 'SessionStart') {
    if (p.autostart) launchDesktop();
    if (!input.source || input.source === 'startup' || input.source === 'resume') bump(p, 'sessions');
    const streak = p.stats.streak > 1 ? t('hook.streak', { n: p.stats.streak }) : '';
    if (p.hunger < 25) msg = t('hook.hungry', { name: p.name });
    else if (p.mood < 30) msg = t('hook.bored', { name: p.name });
    else msg = t('hook.hello', { name: p.name, lv: levelOf(p.xp), streak });
  } else if (event === 'UserPromptSubmit') {
    act.busyUntil = now + BUSY_MS;
    act.turnStart = now;
    act.turnTools = 0;
    act.tool = '';
    bump(p, 'prompts');
    bumpToday(p, 'prompts');
    if (new Date().getHours() < 5) bump(p, 'lateNight');
  } else if (event === 'PreToolUse') {
    act.busyUntil = now + BUSY_MS;
    act.tool = String(input.tool_name || '');
    act.toolAt = now;
    act.turnTools = (act.turnTools || 0) + 1;
    bump(p, 'tools');
    bumpToday(p, 'tools');
    addXp(p, 1);
  } else if (event === 'Stop') {
    act.busyUntil = 0;
    act.tool = '';
    act.celebrateAt = now;
    const ms = act.turnStart && now - act.turnStart < 6 * 3600000 ? now - act.turnStart : 0;
    act.lastTurn = { ms, tools: act.turnTools || 0 };
    act.turnStart = 0;
    bump(p, 'turns');
    bumpToday(p, 'turns');
    p.stats.longestTurnSec = Math.max(p.stats.longestTurnSec || 0, Math.round(ms / 1000));
    p.mood = clamp(p.mood + 2);
    addXp(p, 3);
  } else if (event === 'Notification') {
    // Only permission requests count as "needs your OK"; idle "waiting for input" notices are ignored
    const type = input.notification_type || '';
    const m = String(input.message || '').toLowerCase();
    const idle = type === 'idle_prompt' || /waiting for your input/.test(m);
    if (!idle && (type === '' || type === 'permission_prompt' || type === 'elicitation_dialog')) act.alertAt = now;
  } else if (event === 'SessionEnd') {
    act.busyUntil = 0;
    if (input.reason !== 'clear') act.byeAt = now;
  }

  checkAchievements(p);
  save(p);
  if (msg) process.stdout.write(JSON.stringify({ systemMessage: msg }));
}

try {
  const [mode, ...rest] = process.argv.slice(2);
  if (mode === 'hook') hook(rest[0]);
  else command(mode, rest);
} catch (e) {
  // A failing hook must never break Claude Code itself
  if (process.argv[2] !== 'hook') console.error(e.message);
}
process.exit(0);
