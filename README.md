# claude-pet 🦀

> **Unofficial fan project.** Clawd is Anthropic's mascot. This project is not affiliated with, endorsed by,
> or sponsored by Anthropic. It is a free, non-commercial tribute for personal use.

A desktop pet for Claude Code: **Clawd** wanders along the bottom of your screen and reacts to what Claude is
doing: typing while Claude works, celebrating when it finishes, and waving at you when Claude needs your approval.

Supports **English** and **繁體中文** (auto-detected, switchable any time).

## Install

In Claude Code:

```
/plugin marketplace add Door3172/clawd-desktop-pet
/plugin install claude-pet@pet-marketplace
```

Requirements: **Windows**, Node.js, and Python 3 with tkinter (included in the standard Windows installer).
Works with both the Claude Code CLI (in any terminal) and the Claude desktop app.

## Two skins (right-click → Skin)

- **Pixel Clawd** (default): sprite-sheet art that looks closest to the original. It also drinks coffee and
  water, eats fries, holds a flower, plays games, reads, and sleeps in a nightcap.
- **Chibi Clawd**: a round, hand-drawn version that squashes and stretches, tumbles when thrown, and comes in
  four colors.

Both skins can wear **accessories**: party hat, bow, sprout, and a crown (unlocks at Lv.10).

## Reacting to Claude

| Event | Reaction |
| --- | --- |
| Claude is working | Types on a laptop (or reads a book while reading, searching or browsing), with a caption showing what it's doing and for how long, e.g. "Searching 1:24" |
| Claude finishes | Jumps and throws confetti. Long replies show "Done! Took 2:13", and very long ones get a dance |
| Claude needs permission | Waves and shouts "Needs your OK!" (plain "waiting for input" notices are ignored) |
| Level up / achievement | Spins with sparkles and announces it |
| Session ends | Waves goodbye |

**Pop-up reminders:** when Claude finishes, needs you, or a pomodoro ends while you're in another app, Clawd
pops up for a moment (with an optional sound). **Click it to jump straight back to Claude.** Clicking the pet
also hands focus back to the window you were in, so it never interrupts your typing.

## Fun stuff

- **Throw it**: drag and fling. It tumbles, bounces off the screen edges, and gets dizzy on hard landings.
- **Ball**: right-click → Bring out the ball. Throw it around and Clawd chases and kicks it.
- **Poke it**: 4 quick clicks make it jump; 7 make it angry (hidden achievement!).
- **Tricks**: right-click → Tricks (dance, spin, jump, wave, stretch, sleep), or `/pet trick dance`.
- **Make it talk**: `/pet say hello`.
- **Chatter**: now and then it comments on the time of day, today's stats, or your streak.
- **Achievements**: 20 of them (2 hidden). Right-click → Achievements & stats.

## Quality of life

- **Pomodoro timer** with a countdown above its head (25 / 50 / 5 min or custom).
- **Break reminder**: after 60 minutes of continuous computer use (resets after 5 idle minutes).
  Choose 30 / 45 / 60 / 90 minutes or turn it off.
- **Do not disturb**: no pop-ups, sounds, chatter or break reminders.
- **Stay put**: stops it from wandering around.
- **Hide for a while**: 10 / 30 / 60 minutes (handy when screen sharing).
- **Hover** over it to see its name, level, food and mood.
- **Ctrl + mouse wheel** over it to resize.
- By default it only shows while Claude is in front: the Claude desktop app, or a terminal / editor running the
  Claude Code CLI (Windows Terminal, PowerShell, VS Code, Cursor, JetBrains IDEs...). Toggle it in Settings.

## Commands

| Command | Description |
| --- | --- |
| `/claude-pet:pet` | Status |
| `/claude-pet:pet help` | All commands |
| `/claude-pet:pet stats` / `achievements` | Stats / achievements |
| `/claude-pet:pet feed` / `play` | Feed / play |
| `/claude-pet:pet trick dance` | Tricks: dance / spin / jump / wave / stretch / sleep |
| `/claude-pet:pet say <text>` | Make it say something |
| `/claude-pet:pet timer 25 <label>` / `timer off` | Pomodoro timer |
| `/claude-pet:pet hat party` | Accessory: none / party / bow / sprout / crown |
| `/claude-pet:pet name <name>` | Rename |
| `/claude-pet:pet skin pixel` / `chibi` | Switch skin |
| `/claude-pet:pet color blue` | Chibi color: orange / blue / green / purple |
| `/claude-pet:pet lang en` / `zh-TW` / `auto` | Language |
| `/claude-pet:pet show` / `hide` | Bring out / put away the pet |
| `/claude-pet:pet settings` | Show all settings |
| `/claude-pet:pet peek off` | Other switches: focus / peek / sound / chatter / stay / follow / dnd (on/off) |
| `/claude-pet:pet break 45` / `break off` | Break reminder interval |
| `/claude-pet:pet autostart off` | Don't bring out the pet when Claude Code starts |

## Files

- `claude-pet/scripts/pet_window.py`: the desktop window (skins, animations, interaction, ball, timer, reminders)
- `claude-pet/scripts/pet.js`: command and hook entry point; updates state and stats
- `claude-pet/scripts/lang.json`: UI strings for every language
- `claude-pet/scripts/achievements.json`: achievement definitions
- `claude-pet/assets/clawd-sprites.png`: pixel sprites (third party, MIT, see `NOTICE`)
- Your pet's state is stored locally in `~/.claude/pet/` (`state.json`, `prefs.json`, `desktop.log`)

### Adding a language

Copy the `"en"` block in `lang.json` to a new language code, translate the values, and add the same code to
the `name` / `desc` objects in `achievements.json`. It will show up in the Language menu and in `/pet lang`.

## Development

```
python claude-pet/scripts/pet_window.py --gallery                      # preview every chibi pose
GALLERY_SKIN=pixel python claude-pet/scripts/pet_window.py --gallery   # preview the pixel skin
GALLERY_LANG=zh-TW python claude-pet/scripts/pet_window.py --gallery   # preview in another language
python claude-pet/scripts/pet_window.py --force dance                  # start and force an animation
```

Set `CLAUDE_PET_DIR` to use a separate state folder while testing.

## Credits & license

- Code: MIT, see [LICENSE](LICENSE).
- Pixel sprites: [shigure0110/clawd-pet](https://github.com/shigure0110/clawd-pet) (MIT), see
  `claude-pet/assets/LICENSE.clawd-pet`.
- Transparent-window technique inspired by [Mochi Desktop Pet](https://github.com/m18023318493-sys/mochi-desktop-pet) (MIT).
- Clawd and Claude are trademarks of Anthropic. This is an unofficial fan work. See `claude-pet/NOTICE`.
