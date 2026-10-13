# Requirements Specification

## 1. Product Scope

The application plans family weekday dinners using a local ingredient catalogue and an approved dish catalogue. It uses AI for natural-language interpretation, candidate recipe generation, video recipe extraction, and translation. Deterministic code performs calculations, permission checks, constraint validation, similarity scoring, optimization support, and persistence.

### Primary Capabilities

1. Generate a four-week plan covering Monday through Friday: 20 dinners.
2. Make scoped changes to an existing plan based on user feedback.
3. Maintain ingredient and dish catalogues.
4. Review AI-generated dishes in batches before approval.
5. Import recipe tutorials from Bilibili or YouTube URLs.
6. Translate approved recipes into English and export a PDF.
7. Maintain persistent natural-language constraints and accept task-specific additional constraints.

## 2. Users and Meal Assumptions

- The initial target is a single household.
- The user provides the number and composition of diners, such as three adult women and one six-year-old child.
- For a given four-week plan, diner composition can be assumed constant across all 20 dinners.
- The user chooses the desired number and composition of dishes per dinner, such as three or four dishes plus one soup.
- Exact nutritional precision is not required. Calorie estimates are approximate planning signals.

## 3. Constraint Model

### 3.1 Constraint Sources and Scope

**Persistent constraints**

- Maintained in a reusable constraint list.
- Active by default for both full-menu generation and subsequent menu adjustment.
- Examples include dish count, soup count, meat/vegetable composition, calorie target, variety, and repetition avoidance.

**Task-scoped additional constraints**

- Entered by the user for an individual generation or adjustment task.
- Apply only to the specified task unless the user explicitly saves them as persistent constraints.
- Menu generation and menu adjustment each provide an independent input path for additional constraints.

**Effective constraint set**

The system combines persistent constraints and the current task's additional constraints before optimization. Each constraint retains its source, scope, strictness, and parse status.

- An explicit task-level override may temporarily supersede a persistent constraint.
- An ambiguous conflict must be explained and clarified with the user.
- A task-level override must not silently modify the persistent constraint list.

### 3.2 Natural Language and Executable Representation

Each constraint has a natural-language description, typically one or two sentences. The system attempts to parse it into a structured representation that deterministic code can evaluate.

Constraint parsing must distinguish at least:

- `executable`: directly represented and evaluable;
- `approximated`: evaluated using an imperfect proxy or incomplete features;
- `needs_clarification`: ambiguous or incomplete;
- `unsupported`: current data or tools cannot evaluate it;
- `conflict`: incompatible with another active constraint.

The system must retain the original natural-language description after parsing. It must not claim a constraint has been met when it could not be evaluated.

### 3.3 Hard Constraints and Soft Objectives

Hard constraints must be satisfied for a plan to be marked feasible. Examples may include a required number of dishes, required soup count, ingredient exclusions, or explicitly non-negotiable user instructions.

Soft constraints are optimized rather than treated as absolute pass/fail conditions. Examples include approximate calorie targets, variety, similarity avoidance, and preference matching.

Strictness depends on the user's intent and the constraint's meaning. If hard constraints are infeasible, the system must report the reason and offer useful next steps.

### 3.4 Constraint Priority and Conflict Resolution

- Persistent constraints apply by default.
- Task-level constraints apply only to the current task.
- Explicit task-level overrides are temporary.
- Implicit conflicts must be surfaced before the system commits to a decision.
- The optimizer must not silently relax a hard constraint.
- If a proposed relaxation could make the task feasible, explain the relaxation and its impact and obtain user approval.

## 4. Menu Generation Requirements

- Generate exactly four weeks of Monday–Friday dinners, for 20 dinners in total.
- Respect the fixed diner composition supplied for the plan.
- Respect user-selected dish count and dish-type composition.
- Include soup according to the selected constraint.
- Estimate calories using recipe ingredients, quantities, serving yield, and diner assumptions when data permits.
- Target a reasonable calorie range. An initial default of approximately ±20% around the target is proposed, not a clinically precise nutrition guarantee. **Deferred (2026-10-12):** calorie constraints are not implemented in the initial version; calorie fields are still recorded on ingredients and dishes (see `architecture.md` ADR-008).
- Avoid exact dish repetition within the configured repetition window.
- Support configurable repetition windows, such as one week, two weeks, or the full four-week plan.
- Reduce similarity between individual dishes and between complete meals.
- Use global planning and optimization rather than selecting each dish independently and greedily.
- When approved dishes are insufficient, identify the unmet requirements and generate targeted candidate dishes from available ingredients.
- AI-generated candidate dishes must go through batch user review before they become approved dishes.
- Distinguish a feasible plan from a best-effort or incomplete proposal.

## 5. Dish and Ingredient Catalogues

### 5.1 Separate Catalogues

Ingredients and dishes are separate data entities and are stored in multiple readable YAML files. SQL is not required for the initial data volume.

The ingredient catalogue is manually maintained by the user. The initial dish catalogue is also seeded manually, then may grow through approved AI-generated or imported recipes.

Expected approved dish catalogue size is roughly 100–300 dishes as a soft planning estimate. The system must not impose a hard limit at 300.

### 5.2 Ingredient Permissions

- The user has exclusive write authority over ingredient master data.
- AI may read ingredient records and suggest additions or corrections in a separate proposal, but may not directly add, edit, or delete ingredient master records.
- Enforce this in application/backend code, not only in prompts.
- Unknown ingredients in a candidate recipe must be flagged for user resolution. The system must not silently create master records.

### 5.3 Dish Records

A dish record should support, at minimum:

- Stable `dish_id`.
- Chinese and English names where available.
- Business type/category, such as vegetarian dish, mixed meat-and-vegetable dish, major meat dish, or soup.
- Ingredient IDs and quantities.
- Serving/yield information where available.
- Preparation steps/tutorial.
- Approximate calories and the serving basis for the estimate.
- Source/provenance: manual, AI-generated, or video-imported.
- Review status.
- Style/similarity features.

The business category and similarity features are separate dimensions. A soup is a meal role/category; its cuisine, cooking method, flavour, and main ingredients are similarity features.

### 5.4 Candidate Review

- AI-generated dishes are stored separately from approved dishes until reviewed.
- Batch review supports approve, edit, and reject.
- Approved candidates must pass schema and ingredient-reference validation.
- Rejected candidates must not enter the approved catalogue.
- Approval does not imply that all nutritional data is exact; uncertainty should be retained.

## 6. Similarity and Variety

### 6.1 Dish-Level Similarity

Dish similarity is a deterministic score in the range 0–1 based on available features, potentially including:

- Main ingredients.
- Cooking method.
- Flavour.
- Cuisine/style.
- Core ingredient combination.

Initial feature weights and thresholds are configurable and remain open decisions. Any initial weights used during prototyping are tunable assumptions, not universal truths.

Exact same dish IDs must be detectable independently of approximate similarity. Whether exact repetition is a hard constraint is configurable and must be consistent with the active repetition policy.

### 6.2 Whole-Meal Similarity

The baseline whole-meal similarity method is greedy matching:

1. Calculate dish-to-dish similarity scores between two meals.
2. Select the remaining pair with the highest similarity.
3. Add its score and remove both dishes from further matching.
4. Repeat until no pairs remain.
5. Sum the matched scores.

When meals have different numbers of dishes, also report a normalized score, such as mean matched similarity, or otherwise account for meal size so scores are not compared naively across different sizes.

Do not replace greedy matching with another algorithm without an explicit design decision.

### 6.3 Use of Similarity

- During four-week generation, discourage overly similar dishes and meals across the configured comparison window.
- During local adjustment, evaluate the replacement against the affected meal and the rest of the plan.
- The same base metrics may be reused, but thresholds and penalty strength may differ by task.
- Similarity is initially a soft objective unless the user explicitly sets a strict no-similarity rule.

## 7. Menu Adjustment and Feedback

- Users can identify a disliked dish and request a replacement.
- The system should ask for or record the scope of feedback when it matters: this menu only, future menus, a named diner if supported, or a persistent preference.
- A dislike does not delete the dish from the dish catalogue.
- Prefer local replacement and preserve unrelated approved dishes.
- If no valid local replacement exists, expand the search scope gradually and explain the broader changes.
- Revalidate all applicable constraints after each proposed change.
- Preserve menu versions and an auditable change history.
- Support task-specific additional constraints for adjustment independently of generation-task inputs.

## 8. Video Recipe Import

- Accept Bilibili and YouTube URLs.
- Retrieve platform-provided subtitles/transcripts or descriptions where accessible and permitted.
- If subtitles are unavailable, an ASR path may be considered; visual understanding may be needed for some recipes.
- Extract ingredients, quantities, steps, cooking methods, and uncertainty.
- Normalize ingredient references against the user-maintained catalogue without modifying it.
- Route extracted recipes through candidate review before approval.
- Platform accessibility, ASR/vision providers, and handling of inaccessible videos are open implementation decisions.

## 9. English Recipe PDF

- After menu/recipe approval, translate recipe content into English.
- Export a printable PDF for household use.
- Exact layout, pagination, inclusion of shopping lists, and translation review workflow were open decisions. Implemented default (ADR-021): A4, a cover menu table plus one section per recipe, no shopping list, cached checked translations that can be corrected in `data/translations.yaml`.

## 10. Acceptance Criteria

A first usable version should demonstrate that:

1. It loads valid ingredient, dish, constraint, and preference YAML data.
2. It rejects malformed records and invalid ingredient references with actionable errors.
3. AI-originated operations cannot mutate the ingredient master catalogue.
4. It can build a 20-dinner planning problem and either return a validated feasible plan or a meaningful infeasibility explanation.
5. It applies persistent constraints and task-scoped constraints with the specified scopes.
6. It does not silently override persistent constraints when a task-level instruction is ambiguous.
7. It computes calorie estimates and reports their assumptions and uncertainty.
8. It computes dish similarity and whole-meal similarity using the documented baseline.
9. It identifies exact repeats and evaluates the configured repetition window.
10. It supports batch review of candidate dishes and only adds approved dishes to the approved catalogue.
11. It can propose a local replacement and revalidate the affected menu.
12. It preserves menu history and does not change unrelated approved menu items during a successful local replacement.
13. It can export an English recipe PDF from approved recipe data.
14. It provides a documented, testable path for video recipe extraction, even if platform/ASR capabilities are initially limited.
15. It reports which constraints were satisfied, approximated, unsupported, or left unresolved.
