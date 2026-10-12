# Local Family Dinner Planner

A local-first application for planning weekday family dinners, maintaining ingredient and dish catalogues, making scoped menu adjustments from feedback, importing recipe tutorials from video links, and exporting approved recipes in English PDF form.

## Goals

1. Generate a four-week plan for Monday–Friday: 20 dinners.
2. Apply long-term household constraints automatically, without asking the user to re-enter them every time.
3. Allow additional constraints for a specific generation or adjustment task.
4. Balance meal composition, approximate calories, variety, and similarity across dishes and meals.
5. Maintain a user-owned ingredient catalogue and a reviewed dish catalogue.
6. Use AI where language understanding or recipe generation helps, and deterministic code where correctness can be checked.
7. Support local-first operation and readable YAML data files.

## Core Workflow

### Generate a Four-Week Menu

1. Read the ingredient catalogue, approved dishes, persistent constraints, preferences, and relevant menu history.
2. Collect the current task's meal composition and any additional constraints.
3. Parse natural-language constraints into structured rules and identify ambiguities or conflicts.
4. Build a candidate set and solve the menu as a global optimization problem.
5. Validate the proposed 20-dinner menu with deterministic checks.
6. If the catalogue cannot satisfy the constraints, explain the shortfall and generate targeted candidate dishes.
7. Present generated candidates for batch review. Only approved dishes enter the approved catalogue.
8. Re-run planning and validation, then let the user review and save the menu.

### Adjust an Existing Menu

1. Collect the disliked dish or requested change and the scope of the feedback.
2. Preserve unrelated approved dishes where possible.
3. Generate and rank replacement candidates, then optimize within the affected scope.
4. Recalculate calories, composition, repetition, similarity, and all applicable constraints.
5. Show the proposed change and its impact; save a new menu version according to the application's confirmation policy.

### Import a Recipe from a Video

1. Accept a Bilibili or YouTube URL.
2. Retrieve available subtitles, transcripts, or descriptions where permitted.
3. Use speech recognition if needed and feasible; visual understanding may be required for some recipes.
4. Extract ingredients, quantities, steps, cooking method, and uncertainty notes.
5. Normalize references against the ingredient catalogue without modifying that catalogue.
6. Send the candidate recipe through user review before approval.

### Export English Recipes

Translate approved menu recipes into English and export a printable PDF. Page layout and whether shopping lists are included remain to be decided.

## Data Ownership

Data layout (schemas in `meal_planner/models.py`, details in `docs/architecture.md` §4):

- `data/ingredients.yaml`: user-maintained ingredient master data; AI has read-only access.
- `data/dishes.yaml`: approved dish catalogue.
- `data/pending_dishes.yaml`: candidate dishes awaiting review.
- `data/constraints.yaml`: persistent constraints and their structured interpretations.
- `data/preferences.yaml`: user preferences and scoped feedback, where applicable.
- `data/menus/<menu_id>/v<NNN>.yaml`: immutable menu versions with change notes.

The `data/` directory is currently tracked in git as a backup; tests never read or write it except to check that the shipped files are valid.

## Architecture Principles

- Natural-language constraints are parsed into structured representations.
- Persistent constraints and task-specific constraints remain distinguishable.
- Hard constraints are validated; soft constraints are optimized.
- The optimizer plans the full menu globally rather than choosing each dish independently.
- The final plan is checked by a deterministic validator.
- AI-generated dishes cannot bypass review or ingredient-reference validation.
- Menu changes preserve history and are revalidated before being accepted.

## Documentation

- `CLAUDE.md` — working rules for Claude Code.
- `docs/requirements.md` — functional requirements, constraints, and acceptance criteria.
- `docs/architecture.md` — proposed architecture, modules, data model, and optimizer design.
- `docs/implementation-plan.md` — phased implementation and test plan.

## Development Setup

```bash
conda create -n meal-planner python=3.11
conda activate meal-planner
pip install -e ".[dev]"
pytest                                         # never calls a real model
MEAL_PLANNER_LIVE_LLM=1 pytest tests/test_live_claude.py   # optional: real `claude -p` calls on your subscription
```

AI features call the Claude Code CLI (`claude -p`) using your own Claude subscription. Install the standalone CLI, run `claude` once to log in, and make sure `ANTHROPIC_API_KEY` is not set. See `docs/architecture.md` §12 for the recorded technology decisions.

## Project Status

This is the first project-specification draft.

Items explicitly marked **Open decision** are proposals or unresolved choices, not confirmed requirements. Implementation should not silently treat them as final decisions.

The initial implementation should prioritize a working end-to-end path for YAML validation, constraint parsing, deterministic validation, and menu optimization before building more autonomous agent workflows.
