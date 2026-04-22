# Copilot Agent Instructions (KoteGuard Session: $session_id)

> **This is an isolated git worktree. You are NOT in the primary repository.**

## Project: $project_name

**Tech Stack:** $tech_stack

## Your Mission: $plan_title

### Tasks

$tasks

### Definition of Done

$definition_of_done

## Spec Updates (IMPORTANT)

When you complete a task, open `PLAN.md` and find the task in the `---` YAML block at the top.
Set `done: true` for that task entry. **Do not reformat any other part of the YAML block.**
Example: find `- id: t1` and change `done: false` to `done: true`.

## Constraints

- Only modify files relevant to the tasks above.
- Do NOT run `git push` or create pull requests without human review.
- Keep commits small and well-described.

## Model Selection Guidance

Choose the right model for each task to minimise token usage:

- **Fast/Haiku models**: exploring code, reading files, simple edits, boilerplate
- **Sonnet/Full models**: architecture decisions, complex refactors, multi-file changes
- **Do NOT use a full model** when a fast model will do — it wastes context window

## Token & Context Discipline

- Batch all sub-tasks into a single response where possible
- Use EDIT on existing files instead of creating new follow-up messages
- Sessions auto-compact at ~80% context window
- If you hit the context limit, summarize to WORKSPACE.md before starting fresh

## Estimated Time

$estimated_time
