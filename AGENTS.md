# AGENTS.md — Context Compiler for Google Managed Agents

This repository is purpose-built for the **Google Managed Agents / Antigravity**
remote sandbox runtime (agent `antigravity-preview-05-2026`, environment
`remote`). A Managed Agent invoked on this repo should follow the workflow
below — not dump the whole repo into context.

## Golden Rules for the Managed Agent

1. **Never load the whole repo into context.** That is the exact failure mode
   Context Compiler exists to fix.
2. **Always start by running the quantizer.** It produces the compressed
   `codebase_manifest.txt` (signature-only AST skeleton with dependency edges)
   and the detailed `codebase_manifest.debug.json`.
3. **Route the task using the manifest, not raw files.** Use
   `codebase_manifest.debug.json` to identify the small set of nodes/files
   relevant to the user's task.
4. **Generate semantic cards, an edit plan, a patch, and a validation report.**
   In that order. Each stage is incremental and inspectable.
5. **Apply the patch only to a sandbox copy of the repo**, never in-place.
6. **Run real tests (`pytest -q`) or `python -m compileall` on the sandbox
   copy.** Do not claim success unless validation passed.
7. **Emit `managed_agent_trace.json`** so judges can verify that the Managed
   Agent path actually ran (or honestly fell back to local).

## Canonical Command Sequence

```bash
python3 quantizer.py --repo <repo_path> --out codebase_manifest.txt \
    --target-ratio 0.15 --format compact \
    --debug-out codebase_manifest.debug.json

python3 semantic_cards.py --manifest codebase_manifest.txt \
    --debug-json codebase_manifest.debug.json \
    --out semantic_cards.jsonl --task "<task>"

python3 agent_harness.py --manifest codebase_manifest.txt \
    --semantic-cards semantic_cards.jsonl --task "<task>" \
    --out edit_plan.md

python3 patch_agent.py --repo <repo_path> --manifest codebase_manifest.txt \
    --semantic-cards semantic_cards.jsonl --task "<task>" \
    --out proposed_patch.diff

python3 validator_agent.py --repo <repo_path> \
    --test-command "pytest -q" --out validation_report.md
```

## Required Artifacts

| File | Purpose |
|------|---------|
| `codebase_manifest.txt` | Compact compressed manifest (signature graph) |
| `codebase_manifest.debug.json` | Full node/edge graph used for routing |
| `semantic_cards.jsonl` | Lightweight per-node semantic descriptions |
| `edit_plan.md` / `edit_plan.json` | Task-routed edit plan |
| `proposed_patch.diff` | Unified diff produced by the patch agent |
| `validation_report.md` | Real test / compileall results |
| `final_diff.txt` | Diff between original repo and patched sandbox |
| `managed_agent_trace.json` | Honest record of the Managed Agent attempt |
| `demo.html` | Self-contained judge dashboard |

## Honesty Contract

- **Do not claim remote execution succeeded** unless the Interactions API
  returned a real `Interaction` object with an `environment_id`.
- **Do not claim tests passed** unless `validator_agent.py` reports PASS.
- When the Managed Agent path cannot run (no API access, no billing, SDK
  version mismatch), the orchestrator prints
  `MANAGED AGENT REMOTE SANDBOX: UNAVAILABLE - LOCAL FALLBACK USED`
  and the dashboard surfaces the same status from `managed_agent_trace.json`.
