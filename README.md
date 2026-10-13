# Local Family Dinner Planner

A local-first application for planning four weeks of weekday family dinners (20 dinners). It maintains your ingredient and dish catalogues, applies your long-term household rules automatically, adjusts saved menus dish by dish, imports recipes from Bilibili / YouTube videos and exports an English recipe book as PDF.

AI (Claude, through your own Claude subscription) is used only where language helps: understanding rules written in Chinese, drafting candidate recipes, extracting recipes from video subtitles and translating. Everything that must be correct is done by ordinary code: validation, permissions, the menu optimizer (OR-Tools CP-SAT), similarity and calorie calculations, and saving.

## Features

| Area | What it does |
|---|---|
| Generate a menu | Plans 20 dinners at once, globally rather than day by day, under your persistent rules plus rules for this time only. The result says honestly whether every rule was checked and met, and explains infeasibility (missing dishes, or which rule to relax). |
| Adjust a menu | Click a dish to replace it. The change starts with that dish alone and widens to the dinner, the week or the whole menu only when needed. Every change is a new version; old versions stay. Optional "dislike" feedback applies to this menu only, to future menus, or permanently. |
| Constraints | Write rules in Chinese, for example 每顿三到四个菜，其中一个汤. Claude interprets them; code validates the result. Rules that cannot be represented are marked "unsupported" or "needs clarification", never guessed. |
| Dish catalogue and review | Add dishes manually, or let Claude draft candidates for a catalogue gap. Candidates enter the catalogue only after you approve them. |
| Ingredients | Only you edit the ingredient catalogue. AI can read it but never write it; this is enforced in code. |
| Video import | Reads title, description and subtitles (no video download), extracts a recipe and puts it into review. Unknown ingredients are flagged for you. |
| English PDF | Translates the recipes of a menu version (cached, checked) and builds an A4 recipe book. |

## Requirements

- Windows with Anaconda or Miniconda (Python 3.11 or later; tested with 3.13).
- The standalone **Claude Code CLI**, logged in with your Claude subscription. Install it with `irm https://claude.ai/install.ps1 | iex` in PowerShell, then run `claude` once to log in. `ANTHROPIC_API_KEY` must **not** be set, otherwise the CLI bills that key instead of using your subscription.
- Internet access only for Claude calls and video import. Everything else works offline.

## Install

```bash
conda create -n meal python=3.13
conda activate meal
pip install -r requirements.txt   # pinned, tested versions
```

`requirements.txt` lists only the top-level packages; their own dependencies are installed automatically. `pip install -e ".[dev]"` also works and takes the looser version ranges from `pyproject.toml`.

## Start

```bash
conda activate meal
python app.py           # your data in ./data
python app.py --demo    # invented demo data in ./demo_data (100 dishes, 6 rules); ./data is not touched
python app.py 5001      # another port
```

Open http://127.0.0.1:5000. The server only accepts connections from this computer.

## First steps with your own data

1. **食材库**: add your ingredients. `kcal / 100g` and per-unit gram weights such as `个=150` are optional; they make calorie estimates more complete.
2. **菜品库**: add the dishes you already cook, or generate candidates in **候选审核** and approve the ones you like.
3. **长期约束**: write your household rules, then click "用 Claude 解析". At least one rule must fix the number of dishes per dinner, for example 每顿4个菜.
4. **设置**: choose which Claude model each task uses.
5. **生成菜单**: pick the first Monday, check the diners, add rules for this time only, and generate the menu. Save it when you are happy.
6. **菜单记录**: replace dishes, compare versions, and export the English PDF.

## Data files and backup

All data is readable YAML in `data/`:

| File | Content |
|---|---|
| `ingredients.yaml` | Ingredient master data (yours only) |
| `dishes.yaml` | Approved dishes |
| `pending_dishes.yaml` | Candidates waiting for review, and rejected candidates |
| `constraints.yaml` | Persistent rules and their interpretations |
| `preferences.yaml` | Default diners and dislike feedback |
| `settings.yaml` | Models per task, similarity weights, planner parameters |
| `translations.yaml` | Cached English translations |
| `menus/<menu_id>/vNNN.yaml` | One immutable file per menu version |

- **Safe saving.** Every save is validated first and written atomically. The previous content is kept as `<file>.bak`.
- **Restoring a file.** If a file becomes unreadable, the error message names it and mentions the backup. To restore, copy `<file>.bak` over `<file>`.
- **Your own backups.** `data/` is tracked in git; commit it regularly, or copy the folder. To keep personal data out of GitHub, add `data/` to `.gitignore`.
- **Editing by hand.** You can edit the files directly while the app is stopped or running; each request reloads them and reports any mistake with file, record and field.

## Troubleshooting

| Problem | What to do |
|---|---|
| "Claude Code CLI not found" | Install the standalone CLI and open a new terminal so that `claude` is on `PATH`. |
| Claude calls fail or say you are not logged in | Run `claude` in a terminal and log in. Check that `ANTHROPIC_API_KEY` is not set. |
| A Claude call is slow | Parsing and translation take seconds; generating candidates can take one to two minutes. Use Sonnet for a task in **设置** to make it faster. |
| "需先处理约束" (blocked) | Parse unparsed rules, answer "needs clarification" rules, or resolve conflicts, for example by ticking "本次替代长期约束". |
| "不可行" with catalogue gaps | Add dishes or generate candidates for the named dish type, or relax a rule. |
| "未找到方案" (no solution found) | Increase the solver time limit in **设置**. This is not a proof that no menu exists. |
| A data file error on every page | Fix the named field, or restore `<file>.bak`. |
| A video cannot be imported | The video may need login, be region-restricted, or have no subtitles; speech recognition is not supported. |
| The page is blank | Make sure `python app.py` is still running, then reload the page. |

## Privacy and safety

- **Where data goes.** Data stays on this computer. Claude receives only the text needed for one task: rule texts and the ingredient list, recipes to translate, video text, or catalogue lookups through read-only tools. Logs record only timings and error messages, never prompts or recipes.
- **Isolated Claude calls.** Each Claude call runs the CLI in an empty temporary folder, without built-in file or shell tools, so the model cannot read or change your files.
- **Local access only.** The web server listens on 127.0.0.1 only and accepts only the host names `127.0.0.1` and `localhost`. Other web pages cannot send it changes.

## Tests

```bash
pytest                                                     # about 330 tests; never calls a real model or the network
MEAL_PLANNER_LIVE_LLM=1 pytest tests/test_live_claude.py   # optional: real Claude calls on your subscription
MEAL_PLANNER_LIVE_LLM=1 MEAL_PLANNER_LIVE_VIDEO_URL=<url> pytest tests/test_live_claude.py -k video
python benchmarks/bench_planner.py 100 200 300             # optimizer benchmark on synthetic data
```

## Known limitations

- **Calories.** Calorie constraints are not implemented. Calories are only estimated and shown (ADR-008).
- **Similarity thresholds.** Thresholds and weights are provisional. Calibrate them on your own catalogue (ADR-015, ADR-017).
- **Video import.** Video import uses text only: no speech recognition or vision. Bilibili access was not verified with a real video.
- **PDF.** The PDF is English only and has no shopping list. Translations can be corrected only by editing `data/translations.yaml`.
- **Feedback.** Feedback for a named diner is not supported. The "future menus" and "permanent" dislike scopes currently behave the same.
- **Browser testing.** The web UI has been tested through its API and by static checks of the JavaScript, not by automated browser tests.

## Documentation

- `docs/requirements.md`: requirements and acceptance criteria.
- `docs/architecture.md`: design, data model, optimizer and Web UI, and the decision records (§12).
- `docs/implementation-plan.md`: phases, their status, and the acceptance-criteria checklist.
- `CLAUDE.md`: working rules for Claude Code when developing this project.
