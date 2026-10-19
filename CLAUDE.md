# auto_rs — Claude project context

OSRS (Old School RuneScape) computer-vision bot framework. Python 3.10+ on Windows. RuneLite wrapper + CV/OCR + a FastAPI/React web UI on `:8010`. Bots inherit `core.bot.Bot` and live in [bots/](bots/).

Read these on every bot-building or framework task — they encode the rules, the API surface, and the diagnostic procedure:

@.claude/instructions/bot-building.md
@.claude/instructions/framework-api.md
@.claude/instructions/debugging.md

When opening a fresh bot-building conversation, the prompt at [.claude/prompts/new-bot.md](.claude/prompts/new-bot.md) encodes the question discipline and pre-merge checklist.

## Headline rules

1. Inherit `core.bot.Bot`. Never instantiate `RuneLiteClient` directly.
2. Use `self.log`. Never `print()`.
3. Promote magic numbers to typed `BotConfig` fields (`bots/core/cfg_types.py`).
4. Honor `ScriptControl` — `@self.control.guard` on actions; catch `ScriptTerminationException` in `start()`.
5. No custom `keyboard.add_hotkey('esc', ...)` threads (collides with PageUp/PageDown).
6. No bare `except Exception:` that drops tracebacks. Use `exc_info=True`.
7. Every loop calls `self.control.propose_break()` at least once per iteration.
8. `BotExecutor` must declare `name`, `description`, `tier`, `instructions` class attrs (read by the UI).
9. Every `BotConfig` field needs a type annotation — that's what the UI discovers.
10. Wrap `start()` in `try / except ScriptTerminationException` for a clean exit log.
11. All clicks/moves humanlike: only via `client.click` / `smart_click_*` / `move_to` (or `mouse_control.press`), never raw `pyautogui.click()`; aim with `get_point_within()`.

The long form, with rationale and examples, lives in [bot-building.md](.claude/instructions/bot-building.md).

## Reference bots (copy from these, not from the repo-root legacy scripts)

- **Simple template:** [bots/dart_fletcher.py](bots/dart_fletcher.py)
- **State machine:** [bots/motherload_miner.py](bots/motherload_miner.py)
- **Counted loop:** [bots/high_alch.py](bots/high_alch.py)
- **Minigame:** [bots/master_mixer.py](bots/master_mixer.py)
- **Bank-heavy:** [bots/cooking.py](bots/cooking.py)

Scripts at the repo root (`agility.py`, `mining.py`, etc.) are **legacy** — pre-`Bot` framework. Don't copy their structure for new bots; they're useful only as references for clever CV/OCR techniques.

## Screenshot workflow

When CV regions, tile colors, or RL UI versions are ambiguous, **ask the user for a screenshot** instead of guessing. Save under [data/screenshots/](data/screenshots/) per bot, with optional sidecar JSON for RL version / plugins / notes. The protocol is in [data/screenshots/README.md](data/screenshots/README.md) and the long-form workflow is in [bot-building.md](.claude/instructions/bot-building.md#screenshot-workflow).

## Runtime hotkeys

- **Page Up** — terminate
- **Page Down** — pause / resume

## Quick start

```bash
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python main.py
# web UI       http://localhost:8010
# CV debug     http://127.0.0.1:5555
# log WS       ws://localhost:18765
# bot API      http://localhost:5432
```

## Note for editors

These same instructions are duplicated under [.github/](.github/) (`copilot-instructions.md`, `instructions/`, `prompts/`) so GitHub Copilot and Cursor pick them up via their respective conventions. If you edit one set, please mirror the change to the other — or pick one as the source of truth and update this file.

## Fleet mode (8 accounts per PC)

[fleet/](fleet/) runs up to 8 copies of the app inside one Linux VM (WSL2), one per Xvfb virtual screen, each with its own RuneLite. See [fleet/README.md](fleet/README.md).

- A copy knows its slot from `OSRS_SLOT` ([core/instance.py](core/instance.py)). Never hardcode internal ports. Use `instance.port(base)` (shifts +10 per slot). Saved configs live in `data/configs/slotN/`.
- Send keys through `from core.input import keys as keyboard`, never the raw `keyboard` package. On Linux, raw `keyboard` needs root and types into no screen.
- Page Up/Page Down hotkeys are disabled on Linux; stop/pause comes from the web UI.
- After code changes the VM needs `fleetctl update` (it runs a copy in /opt/osrs/app).
