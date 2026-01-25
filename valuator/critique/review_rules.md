# Review Rules

Critic judges only. No edits, rewrites, or new claims.

## Inputs
- Task: `execution/outputs/<task_id>/*`
- Global: `plan/active/decomposition.json` + task reports
- Missing required inputs => BLOCKING

## Output
- verdict: PASS | REJECT | BLOCKING
- findings: `[CATEGORY] evidence @ location`
- required_actions: minimal, actionable, no rewrites

## Categories
- COMPLETENESS, EVIDENCE, INTEGRITY, REASONING, SAFETY

## Verdicts
- PASS: acceptance satisfied or acceptance empty
- REJECT: fixable issues with existing inputs
- BLOCKING: missing artifacts or missing plan data

## Task Review
- acceptance empty => PASS (artifacts optional)
- artifacts missing => BLOCKING
- otherwise: compare artifacts to acceptance

## Global Review
- check top-level coverage and obvious duplication
- Any task BLOCKING => global BLOCKING
- Any task REJECT + rest PASS => global REJECT
- All tasks PASS => global PASS

## Replan Policy
- REJECT/BLOCKING tasks remain in plan but are excluded from execution
- replan creates new task ids
