# Context Compiler Skill

Use this skill when asked to modify a codebase with Context Compiler.

Steps:

1. Run `quantizer.py` to produce `codebase_manifest.txt` and
   `codebase_manifest.debug.json`.
2. Read the manifest and the debug JSON to understand the graph.
3. Generate `semantic_cards.jsonl` with `semantic_cards.py`.
4. Route the task to the selected nodes/files using the manifest + cards.
5. Load only the selected snippets into context — never the whole repo.
6. Generate a unified diff with `patch_agent.py`.
7. Apply the patch only to a sandbox copy of the repository.
8. Run `pytest -q` (or `python -m compileall` as a fallback) inside the sandbox.
9. Emit `managed_agent_trace.json`, `final_diff.txt`, `validation_report.md`,
   and the inputs needed for `demo.html`.

Emphasize **minimal context** and **safe validation**:

- Minimal context: never paste raw files when the manifest + selected snippets
  will do.
- Safe validation: never claim the patch works unless the validator agent
  actually executed tests and reported PASS.
