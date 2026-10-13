# Implementation Plan

## Approach

Build a small end-to-end vertical slice first, then expand it. Keep core rules deterministic and testable.

This plan is a proposed sequence. Adjust it based on implementation findings without silently changing requirements or treating unresolved proposals as confirmed decisions.

## Phase 0 — Repository and Technology Decisions

**Status:** completed 2026-10-12. Decisions in `architecture.md` §12.

### Tasks

- Inspect the existing repository and document the current environment.
- Choose the initial Python version and packaging approach.
- Decide a minimal local Web UI/backend stack.
- Prototype the selected LLM access path and confirm whether all inference must remain local.
- Decide the runtime orchestration approach; do not assume Claude Code itself is the deployed application runtime.
- Record decisions in `docs/architecture.md`.

### Exit Criteria

- A reproducible development environment.
- A short architecture decision record for major technology choices.
- No unresolved decision is silently represented as confirmed.

## Phase 1 — YAML Schemas and Repositories

**Status:** completed 2026-10-12. Code in `meal_planner/` (`models`, `catalogue`, `store`, `readonly`, `yaml_io`); tests in `tests/`.

### Tasks

- Define versioned schemas for ingredients, approved dishes, pending dishes, constraints, preferences, and menus.
- Implement YAML loading, validation, stable ID checks, and ingredient-reference checks.
- Create repository/service functions for reading data.
- Implement safe writes for application-owned files, with backups or atomic replacement where practical.
- Enforce read-only ingredient access for AI workflows.
- Add fixtures with a small representative catalogue.

### Tests

- Valid and malformed YAML.
- Duplicate IDs and unknown ingredient IDs.
- AI/tool attempts to write ingredient data are denied.
- Pending dishes cannot be queried as approved dishes by the optimizer.
- Safe persistence and recovery behavior.

### Exit Criteria

- All core YAML files load and validate.
- Data ownership boundaries are enforced in code.

## Phase 2 — Constraint Registry and Parser

**Status:** completed 2026-10-12. Code in `meal_planner/` (`constraint_types`, `constraint_parser`, `constraints`, `llm/`); see `architecture.md` §5.2. No UI yet: persistent constraints are inspected and edited through `constraints.py` functions until Phase 6.

### Tasks

- Define typed executable constraint schemas and a registry.
- Implement persistent and task-scoped constraint loading.
- Implement an LLM parser that returns schema-constrained structured output.
- Validate all parser output in ordinary application code.
- Track parse status: executable, approximated, needs clarification, unsupported, or conflict.
- Implement explicit override handling and ambiguity prompts.
- Provide a way to inspect and edit persistent natural-language constraints.
- Ensure menu generation and menu adjustment accept independent task-specific constraint inputs.

### Tests

- Natural-language examples for dish count, soup count, meat/vegetable composition, calorie tolerance, ingredient exclusions, and similarity.
- Invalid or incomplete parser output.
- Conflicting persistent and task-level constraints.
- Task-level constraints do not mutate persistent constraints.
- Explicit overrides work only for the current task.
- Unsupported constraints are reported honestly.

### Exit Criteria

- A task can produce a validated effective constraint set with source, scope, strictness, and parse status preserved.

## Phase 3 — Deterministic Food and Similarity Tools

**Status:** completed 2026-10-12. Code in `meal_planner/` (`calories`, `checks`, `similarity`); see `architecture.md` §6.8.1, ADR-015, ADR-016.

### Tasks

- Implement dish-type counting and meal composition checks.
- Implement calorie estimation with explicit serving/yield assumptions and missing-data warnings.
- Implement exact dish repetition checks for configurable windows.
- Implement dish similarity using configured features and weights.
- Implement whole-meal greedy matching and a normalized comparison score.
- Return explainable intermediate scores.

### Tests

- Unit tests for calories and units.
- Similarity boundary cases: identical dishes, disjoint ingredients, shared cooking method, and missing features.
- Whole-meal greedy matching and unequal meal sizes.
- Repetition-window boundaries.
- Missing data must not be silently treated as a precise value.
- The same input and configuration produce consistent scores.

### Exit Criteria

- Deterministic checks and scores are independently testable without an LLM.

## Phase 4 — Optimizer Prototype

**Status:** completed 2026-10-12. Code in `meal_planner/` (`plan_context`, `solver`, `repair`, `validator`, `planner`); benchmark in `benchmarks/bench_planner.py`; see `architecture.md` §6.12 and ADR-017.

### Tasks

- Create a benchmark catalogue and a 20-dinner test problem.
- Prototype OR-Tools CP-SAT as the candidate solver.
- Model dish-selection variables, meal composition, exact repeats, and calorie deviation.
- Add tractable dish-level similarity penalties.
- Return solver status, feasibility, per-objective scores, and diagnostics.
- Evaluate whole-meal similarity after solving.
- Prototype local-search/repair swaps to improve meal-level similarity while preserving hard constraints.
- Compare solve time and output quality on representative data.
- Keep the solver behind a small interface.

### Tests

- Known feasible and infeasible instances.
- All hard constraints checked by an independent final validator.
- Repeatable results under fixed configuration where practical.
- Solver timeout and no-solution behavior.
- Objective score report and trade-off explanation.
- Local repair never commits a change that violates hard constraints.
- A solver result is never marked feasible solely because the solver returned a candidate.

### Exit Criteria

- A 20-dinner plan is either validated as feasible or accompanied by actionable infeasibility diagnostics.
- The solver is benchmarked before the final implementation approach is locked.

## Phase 5 — Dish Candidate Generation and Batch Review

**Status:** completed 2026-10-12. Code in `meal_planner/` (`ai_tools`, `candidates`, `review`); see `architecture.md` §6.10.1 and ADR-018.

### Tasks

- Generate targeted recipe candidates based on identified catalogue gaps and available ingredient IDs.
- Require valid schema and ingredient references.
- Store candidates only in pending data.
- Implement batch approve, edit, and reject review.
- Add approved candidates to the approved dish catalogue through validated application code.
- Rerun planning after approval.

### Tests

- Generated candidates cannot bypass review.
- Unknown ingredients are flagged rather than auto-created.
- Reject, edit, and approve operations persist correctly.
- Only approved records are selectable by the optimizer.
- Invalid candidates cannot enter the approved catalogue.

### Exit Criteria

- The system can explain a catalogue shortage, request candidate dishes, and resume planning after user review.

## Phase 6 — Local Web UI and Menu Generation Workflow

**Status:** completed 2026-10-12 (pending the user's manual UI check). See `architecture.md` §11.1.

### Tasks

- Build UI for diner composition, dish count/composition, persistent constraints, and task-level constraints.
- Show constraint parse status and ask about ambiguous conflicts.
- Run the optimizer and show the proposed 20-dinner plan.
- Display calorie estimates, dish roles, repetition/similarity warnings, and unresolved constraints.
- Let the user review and save a menu version.

### Tests

- End-to-end generation with persistent and task-level constraints.
- UI clearly distinguishes feasible, best-effort, and infeasible outcomes.
- A constraint that could not be evaluated is visible to the user.
- Task-level overrides do not alter persistent settings.

### Exit Criteria

- The user can generate, inspect, and save a validated four-week menu.

## Phase 7 — Menu Adjustment and History

**Status:** completed 2026-10-12 (pending the user's manual UI check). Code in `meal_planner/adjust.py`, adjustment endpoints in `web/api/menus.py`, UI on the menu page; see `architecture.md` §6.11.1 and ADR-019.

### Tasks

- Implement feedback input with scope: current menu, future plans, or named diner if supported.
- Generate local replacement candidates and optimize the smallest affected scope first.
- Expand the scope only if necessary and show the diff.
- Preserve unrelated approved dishes.
- Save a new menu version and change rationale.

### Tests

- Replacement meets all hard constraints.
- Dislike does not delete a dish from the catalogue.
- Unrelated menu entries remain unchanged for a local replacement.
- Failed local search reports why and whether a wider search is needed.
- All changed plans are revalidated.
- Adjustment-task constraints remain separate from generation-task inputs.

### Exit Criteria

- The user can request a replacement and receive an explainable, validated proposal with history.

## Phase 8 — Video Recipe Import

**Status:** completed 2026-10-12. Code in `meal_planner/video_import.py`; see `architecture.md` §8 and ADR-020. Speech recognition is not supported.

### Tasks

- Implement URL intake and platform-specific metadata/transcript retrieval where permitted.
- Add optional ASR if needed and selected.
- Extract structured recipe content.
- Match ingredient mentions to ingredient IDs and surface unmatched terms.
- Send extracted recipes to pending review.

### Tests

- Valid and invalid URLs.
- Missing subtitles/transcript.
- Ambiguous quantities and ingredients.
- No automatic ingredient master mutation.
- Extraction uncertainty is visible.
- Inaccessible videos fail clearly rather than producing fabricated recipe content.

### Exit Criteria

- At least one supported video path produces a reviewable candidate recipe; unsupported URLs fail clearly.

## Phase 9 — English PDF Export

**Status:** completed 2026-10-13. Code in `meal_planner/translation.py` and `pdf_export.py`; see `architecture.md` §8 and ADR-021.

### Tasks

- Translate approved recipe content into English.
- Preserve quantities, cooking order, and relevant cooking details.
- Generate a printable PDF.
- Decide and implement page layout; this remains an open decision.
- Add a menu/recipe export workflow.

### Tests

- Expected recipes are present.
- Units and quantities are retained.
- Long steps wrap correctly and pages are printable.
- Translation/export failures are reported.

### Exit Criteria

- An approved menu's recipes can be exported to a usable English PDF.

## Phase 10 — Hardening and Documentation

**Status:** completed 2026-10-13.

- End-to-end API test on the demo catalogue: shortage → candidates → review → plan → save → adjustment with feedback → video import → PDF. At the end, the ingredient file is unchanged byte for byte.
- Corrupt-file reporting with a backup hint, tested.
- Host restriction against DNS rebinding.
- Logging review.
- README rewritten: installation, start, first steps, data and backup, troubleshooting, privacy, limitations.
- `architecture.md` §9 and §10 updated.

### Tasks

- Run end-to-end tests using a representative catalogue.
- Test backup/recovery and malformed-file handling.
- Review local privacy, logging, and credential handling.
- Document installation, startup, backup, and troubleshooting.
- Update the architecture and requirements with decisions confirmed during development.

### Exit Criteria

- Reproducible setup, passing tests, clear known limitations, and documentation consistent with the implemented behavior.

## Cross-Phase Definition of Done

A feature is not complete until:

- Its behavior is documented.
- Its core logic has tests.
- Failure and unsupported cases are explicit.
- Permissions are enforced outside the prompt.
- Affected data is validated before persistence.
- Any menu change is revalidated.
- User-visible status does not overstate what the system actually checked.
- Relevant open decisions and known limitations are recorded.

## Acceptance Criteria Checklist (requirements §10)

| # | Criterion | Where it is implemented and tested |
|---|---|---|
| 1 | Loads valid ingredient, dish, constraint and preference YAML | `store.py`, `catalogue.py`; `tests/test_loading.py` |
| 2 | Rejects malformed records and invalid references with actionable errors | `catalogue.py` (file/record/field locations); `tests/test_loading.py`, `test_writes.py` |
| 3 | AI-originated operations cannot mutate ingredient master data | `readonly.py`, `ai_tools.py` (tools hold only `ReadOnlyCatalogue`); `tests/test_readonly.py`, `test_ai_tools.py`, `test_candidates.py`, `test_video_import.py`, `test_end_to_end.py` |
| 4 | Builds a 20-dinner problem; returns a validated plan or an infeasibility explanation | `planner.py`, `solver.py`, `validator.py`; `tests/test_planner.py` |
| 5 | Persistent and task-scoped constraints with the specified scopes | `constraints.py`, `menus.py`; `tests/test_constraints.py`, `test_adjust.py`, `test_web_api.py` |
| 6 | No silent override of persistent constraints on ambiguous task instructions | Explicit `overrides` only; conflicts block the task; `tests/test_constraints.py` |
| 7 | Calorie estimates with assumptions and uncertainty | `calories.py`, calories in the validation report; `tests/test_calories.py` |
| 8 | Dish and whole-meal similarity using the documented baseline | `similarity.py` (greedy matching); `tests/test_similarity.py` |
| 9 | Exact repeats within the configured window | `checks.find_repeats`, solver repeat rules, history across menus; `tests/test_checks.py`, `test_planner.py` |
| 10 | Batch review; only approved dishes enter the catalogue | `review.py`; `tests/test_review.py`, `test_candidates.py` |
| 11 | Local replacement proposal and revalidation | `adjust.py`; `tests/test_adjust.py` |
| 12 | Menu history kept; unrelated items unchanged in a local replacement | Immutable versions; `tests/test_adjust.py`, `test_writes.py` |
| 13 | English recipe PDF from approved recipe data | `translation.py`, `pdf_export.py`; `tests/test_translation_pdf.py`, `test_web_api.py` |
| 14 | Documented, testable video extraction path | `video_import.py`; `tests/test_video_import.py`; live YouTube check |
| 15 | Reports which constraints were satisfied, approximated, unsupported or unresolved | `validator.py` per-constraint results; UI result tables; `tests/test_validator.py` |
