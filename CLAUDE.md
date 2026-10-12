 # CLAUDE.md — Project Working Rules

## Project Purpose

Build a local-first family dinner planning application. The application maintains a user-owned ingredient catalogue and an approved dish catalogue, generates four weeks of weekday dinners (20 dinners), supports scoped menu adjustments based on feedback, imports recipe tutorials from video links, and exports approved recipes in English PDF form.

The application combines AI reasoning with deterministic validation. An LLM must not be treated as the authority for arithmetic, constraint validation, permissions, or persistence.

## Read These Files First

Before implementation or a substantial change, read:

1. `README.md`
2. `docs/requirements.md`
3. `docs/architecture.md`
4. `docs/implementation-plan.md`

If implementation reveals a conflict, follow the latest explicit user decision. Do not silently convert an open question or an assistant suggestion into a confirmed requirement. Update the relevant documentation when a decision is confirmed.

## Core Engineering Principles

- Local-first by default. Keep recipe data and application state on the user's machine unless the user explicitly approves another arrangement.
- Store ingredient and dish catalogues as readable YAML files. SQL is not required for the initial data volume.
- Ingredient master data is user-owned. AI workflows may read it and propose changes, but must never write, edit, or delete it.
- AI-generated dishes remain pending until the user approves them. Batch review must support approval, editing, and rejection.
- Use stable IDs for ingredients, dishes, menus, constraints, and feedback. Dish ingredient references must use ingredient IDs, not names as keys.
- Use deterministic code for calculations, schema validation, permission enforcement, constraint checks, similarity calculations, and persistence.
- Treat LLM output as untrusted input. Validate types, IDs, ranges, required fields, and references before use.
- Keep hard constraints separate from soft objectives. Never silently report a plan as fully compliant if a hard constraint is unmet or cannot be evaluated.
- Preserve user-approved menu items during a local adjustment unless the adjustment explicitly requires a broader change.
- Record menu versions and adjustment history.
- Do not write directly to canonical YAML files from an LLM. Validate proposed changes and save through application code, using safe/atomic writes and backups where practical.
- Prefer small, testable modules over a monolithic agent prompt.
- Keep secrets, tokens, and credentials out of source control and logs.

## Constraint Handling Rules

- Maintain persistent natural-language constraints and task-scoped additional constraints as separate sources.
- Persistent constraints apply by default to both full menu generation and subsequent menu adjustment.
- Generation and adjustment must each provide a separate way to enter task-specific additional constraints.
- Parse natural-language constraints into structured executable representations where possible.
- Preserve each constraint's description, scope, priority, parser status, and execution status.
- Do not force unsupported natural-language constraints into unrelated existing parameters.
- If a constraint is ambiguous, conflicts with another constraint, or cannot be evaluated with available data/tools, explain the limitation or ask for clarification.
- Task-scoped constraints do not permanently change persistent constraints.
- An explicit task-level override may temporarily supersede a persistent constraint. An implicit conflict must be surfaced to the user.
- Re-run validation after every menu change.

## Optimizer Rules

- Treat a four-week menu as a global planning problem, not a sequence of independent greedy dish choices.
- Use a deterministic constraint-solving/optimization layer. OR-Tools CP-SAT is the proposed first implementation candidate; verify its suitability before committing implementation details.
- Enforce hard constraints and optimize soft objectives separately.
- Track feasibility status and reasons for infeasibility.
- Calculate dish similarity and whole-meal similarity in deterministic code.
- The baseline whole-meal similarity algorithm is greedy matching: repeatedly match the highest-similarity remaining dish pair between two meals, remove that pair, and sum the matched scores.
- Do not silently replace the greedy matching baseline with another algorithm. A globally optimal matching algorithm may be evaluated later as an explicit design change.
- If the existing approved dish catalogue cannot meet the constraints, report the shortfall and request targeted candidate-dish generation. Generated dishes require user review before entering the approved catalogue.

## Quality and Safety

- Add tests for every constraint type, parser outcome, persistence operation, and optimizer change.
- Include infeasible and conflicting-constraint test cases.
- Test that AI paths cannot mutate ingredient master data.
- Test malformed LLM output and unknown IDs.
- Test local adjustment to ensure unrelated approved menu items remain unchanged.
- Do not claim a constraint was satisfied unless a validator actually checked it.
- Use synthetic/test data in tests; do not overwrite the user's real YAML data.
- Avoid adding dependencies without documenting why they are needed.

## Implementation Workflow

1. Inspect the existing repository and current documentation before editing.
2. Propose a short plan for changes spanning multiple modules.
3. Implement in small increments.
4. Run relevant automated tests and report the actual result.
5. Update documentation when behavior, schemas, commands, or decisions change.
6. Clearly distinguish completed work, untested work, known limitations, and open decisions.

## Current Open Decisions

The following are not fully confirmed in the first documentation draft:

- Runtime orchestration choice: Claude Agent SDK, another agent runtime, or a simpler application-controlled workflow.
- Web UI and backend framework.
- Local model/provider strategy and whether any hosted model is permitted.
- Final similarity feature weights and thresholds.
- Whether CP-SAT should handle all planning or be combined with local search after prototyping.
- Recipe PDF layout and exact contents.
- Video subtitle, ASR, and vision implementation and platform-access constraints.
- Exact default values for all constraints and optimization weights.


## Reference Repositories

When implementing the Web UI, use the following GitHub repository as a reference for **file and directory architecture only**:

- Repository: https://github.com/VinceCarrot/Family-Accounting-Web-UI
- Scope: directory structure, file organization, module boundaries, and separation of responsibilities.

### Strict Restrictions

- Do NOT copy or reuse the reference repository's business logic, application content, domain models, prompts, configuration values, or implementation code.
- Do NOT assume that its features or requirements apply to this project.
- Do NOT reproduce its UI design or visual styling unless separately requested.
- Use the reference only to inform how this project's Web UI files and modules may be organized.
- Adapt the structure to this project's requirements, existing architecture, and selected technology stack. Do not blindly replicate the reference structure.
- Inspect the repository structure before proposing or creating Web UI files.
- If the repository is inaccessible, report that limitation and ask for an alternative source or instructions. Do not pretend to have inspected it.
- Before implementing the Web UI, briefly explain which structural ideas are relevant and propose an adapted directory tree for this project.

The reference repository is guidance, not a source of requirements or implementation code.
