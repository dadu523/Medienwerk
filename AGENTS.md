# Medienwerk: Agent workflow

## User-selected team

- Delegate bounded implementation and research tasks to subagents using model
  `gpt-6-luna` and reasoning effort `high`.
- The primary agent plans, defines shared contracts, integrates the work, and
  personally performs the final review. A worker's completion message alone is
  not evidence that an implementation works.
- With the current four-slot limit, use at most three workers plus the primary
  agent. Parallelize only independent tasks.
- Give each worker an explicit objective, allowed files, dependencies,
  acceptance criteria, relevant artifacts, and permitted checks. Pass focused
  context rather than the full conversation when selecting the worker model.
- Assign one writer per file area. Serialize edits to shared contracts, database
  migrations, `pipeline.py`, `api_clients.py`, and central queue/config modules.
- Workers must not spawn further agents unless the primary agent explicitly
  delegates that action. Do not silently substitute another worker model.

## Skills and project context

- Load skills selectively by their descriptions and the current task. Read the
  complete `SKILL.md` only for directly useful skills; do not load all skill files.
- Read [docs/STABILIZATION_PLAN.md](docs/STABILIZATION_PLAN.md) and the relevant
  part of [docs/AGENT_WORKFLOW.md](docs/AGENT_WORKFLOW.md) before stabilization work.
- The verified skill shortlist is documented in `docs/AGENT_WORKFLOW.md`.
  Four selected GitHub skills are installed; exact repositories and pinned refs are recorded in docs/STABILIZATION_PROGRESS.md. Other candidates remain uninstalled.
- For web changes, follow `web/AGENTS.md` and the guides bundled with the installed
  Next.js version. Existing dependencies and the local SQLite/FFmpeg architecture
  are the baseline.

## Handoff and review

- Report changed files, contract changes, performed checks and their outcomes,
  unchecked cases, remaining defects, and migration/rollback consequences.
- Distinguish checks actually performed from checks merely planned. Add or run
  implementation tests only when the user's task requests testing or verification.
- Use isolated data directories and databases for permitted checks. Do not use
  real credentials or automatically run campaigns, publishing, or paid generation.
- Do not discard existing local changes, force-remove dirty worktrees, or perform
  commits, pushes, or PR actions outside the assigned task's authorization.
- Keep the primary agent responsible for reviewing the integrated result against
  the acceptance criteria and for reporting limitations to the user.
