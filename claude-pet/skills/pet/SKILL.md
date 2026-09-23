---
name: pet
description: Look after your Clawd desktop pet (status, stats, achievements, feed, play, tricks, pomodoro timer, accessories, skin, language and settings)
argument-hint: "[status | stats | achievements | feed | play | trick <name> | say <text> | timer <min>|off | hat <accessory> | name <name> | skin pixel|chibi | color <color> | lang en|zh-TW|auto | show | hide | settings | help]"
disable-model-invocation: true
allowed-tools: Bash(node:*)
---

Run the command below and show its output to the user **verbatim** inside a code block. Do not rewrite it or
add commentary:

```
node "${CLAUDE_PLUGIN_ROOT}/scripts/pet.js" $ARGUMENTS
```

With no arguments the script shows the pet's status; `help` lists every command.
