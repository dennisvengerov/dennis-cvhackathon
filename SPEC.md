# Context Compiler: Agentic Codebase Compression for Managed Coding Agents

## 0. One-Sentence Summary

Context Compiler turns a raw code repository into a compact, graph-structured, semantically enriched execution manifest that Google Managed Agents and Gemini agents can use to localize tasks, generate targeted patches, and validate changes without loading the entire repository into context.

---

## 1. Core Hackathon Claim

Large coding agents do not need the whole repository in raw form.

They need:

1. exact file/function/class boundaries,
2. dependency-aware structure,
3. compact semantic summaries,
4. task-relevant source snippets,
5. a safe patch-and-validation loop.

Context Compiler provides this missing compiler layer.

The system transforms:

```text
Raw Repository
→ AST Dependency Graph
→ Structural Quantization
→ Compact Manifest
→ Gemini Semantic Cards
→ Task Router
→ Patch Agent
→ Validator Agent
→ Original Source Diff

This is not a repo chatbot.

This is a compiler and agent orchestration layer for coding agents.

2. Why This Matters

Modern coding agents face three bottlenecks:

2.1 Token Waste

Raw repositories include boilerplate, tests, generated files, comments, repeated utilities, framework setup, and irrelevant modules.

2.2 Reasoning Noise

More context does not automatically produce better code edits. Irrelevant code distracts the model and weakens task localization.

2.3 Patch Localization

For code modification, an agent usually needs:

file paths,
line ranges,
function/class signatures,
dependency paths,
selected implementation bodies,
test/validation feedback.

It usually does not need every raw source file.

Context Compiler converts a repository into the representation coding agents actually need.

3. Final Product Definition

The final product is a complete master orchestrator `main.py` and pipeline supporting:

1. `--smoke-test`: System check that prints environment details, Gemini API keys, and active modes.
2. `--repo ./demo_repo`: Full local pipeline compilation on a specified local workspace folder.
3. `--judge-demo`: Copy repo safely, run live compilation, apply the patch, run tests inside sandbox, emit final diffs, and generate `demo.html` dashboard.
4. `--repo-url`: Clones remote git URLs, attempts Genuine Managed Agent Sandbox orchestration, and falls back locally.

The demo proves that a coding agent can reason over a compressed repository representation, select relevant files/functions, propose a targeted patch, and validate the result.

4. Design Principle

Context Compiler uses a hybrid, highly-resilient design:

Deterministic compiler front-end

Used for exact, non-negotiable structure:
- file discovery,
- Python AST parsing,
- function/class/method extraction,
- line ranges,
- imports,
- calls,
- inheritance,
- route decorators,
- source snippets,
- token accounting,
- graph construction,
- compression budgeting.

This layer is deterministic because source boundaries and dependency metadata should not hallucinate.

Gemini / Managed-Agent semantic back-end

Used for semantic reasoning:
- compact semantic cards,
- task-specific relevance scoring,
- edit plan generation,
- patch generation,
- validation repair suggestions,
- remote sandbox orchestration.

This layer is agentic because semantic intent, task relevance, and patch planning benefit from language-model reasoning.

Raw structural compaction is deterministic. Semantic enrichment, task-specific routing, and patch generation use Gemini/Managed Agents when available. Deterministic fallback keeps the demo completely reliable when credentials/API are missing.

5. Codebase as a Directed Multi-Graph

We represent a codebase as:

G = (V, E)

where V contains code nodes such as:

modules,
classes,
methods,
functions,
async functions,
route handlers,
schemas,
public APIs.

E contains typed directed edges:

(source_node, target_node, relation_type)

Supported relation types include:

call,
import,
inherit,
reference,
route.

Examples:

checkout_endpoint -> validate_checkout call
checkout_endpoint -> process_payment call
CheckoutRequest -> BaseModel inherit
checkout_endpoint -> APIRouter.post route

Edges may be resolved or unresolved.

Unresolved edges are classified as:

builtin,
stdlib,
third_party,
framework,
unknown.
6. Structural Quantization

Each node has two possible representations:

Full-body mode

Includes:

file path,
line range,
type,
signature,
metadata,
selected dependency edges,
exact source body.
Signature-only mode

Includes:

file path alias,
line range,
type,
qualified name,
signature,
tags,
score,
compact edge metadata.
Ultra-minimal mode

Used only when the signature baseline exceeds the token budget.

Includes:

node alias,
file alias,
line range,
type,
short name,
tags.
7. Token Budget

The target compression ratio is:

compressed_manifest_tokens / raw_repository_tokens <= target_ratio

For the demo, the target is usually:

target_ratio = 0.15

The system must report the real serialized output size. It must not estimate success from the internal graph alone.

Budgeting order:

Count raw repository tokens.
Build full debug graph.
Serialize minimal compact baseline.
If baseline is below budget, greedily promote valuable nodes to full-body mode.
If baseline exceeds budget, enable aggressive compaction:
trim low-value docstrings,
prune noisy unresolved edges,
cap edge count per node,
collapse low-score nodes,
preserve file/line mapping.
Serialize final compact manifest.
Re-count final manifest tokens.
Report true compression ratio.
8. Structural Scoring

Each node receives a structural score based on:

inbound dependency count,
outbound dependency count,
public/API exposure,
route/endpoint status,
schema/model status,
docstrings/type annotations,
task-relevant naming patterns,
resolved edge participation,
estimated token cost.

A practical score can include:

score =
  2.0 * inbound_degree
+ 1.0 * outbound_degree
+ 3.0 * public_api_bonus
+ 4.0 * route_or_endpoint_bonus
+ 2.0 * schema_or_model_bonus
+ 1.5 * service_or_utility_bonus
+ 1.0 * annotation_or_doc_bonus
+ task_keyword_bonus

The value density for retaining a full body is:

value_density = score / max(full_body_tokens - signature_tokens, 1)

Nodes are promoted to full-body mode in descending value density until the token budget is reached.

9. Compact Manifest Format

The primary artifact for agents is:

codebase_manifest.txt

This is a compact, line-oriented text representation optimized for LLM context.

It uses aliases:

F0 = app/api/checkout.py
N0 = app/api/checkout.py::checkout_endpoint

Example:

# Context Compiler Manifest v2
META repo=demo_repo original_tokens=482193 compressed_tokens=61842 ratio=0.128 target=0.150 files=48 nodes=312 edges=1021 resolved=820 unresolved=201 full=22 sig=290

FILES
F0 app/api/checkout.py
F1 app/services/payments.py
F2 app/utils/validation.py

NODES
N0 F0:12-68 function checkout_endpoint sig="def checkout_endpoint(request: CheckoutRequest):" score=9.84 in=3 out=5 mode=body tags=route,endpoint,public
N1 F2:7-22 function validate_checkout sig="def validate_checkout(payload):" score=7.31 in=4 out=1 mode=sig tags=utility,public
N2 F1:14-44 function process_payment sig="def process_payment(order):" score=8.02 in=2 out=2 mode=body tags=service,public

EDGES
N0 -> N1 call validate_checkout resolved
N0 -> N2 call process_payment resolved
N0 -> EXT:fastapi.APIRouter.post route framework

BODIES
### N0 app/api/checkout.py::checkout_endpoint
<retained exact source body>

A verbose debug artifact may also be emitted:

codebase_manifest.debug.json

The debug JSON is for dashboard/debugging, not for main LLM context.

10. Semantic Cards

The second artifact is:

semantic_cards.jsonl

Semantic cards are generated by cheap Gemini agents when available, or by deterministic fallback when no API is configured.

Each card summarizes one important node in a tiny, task-aware format.

Example:

{
  "node_id": "N0",
  "qualified_name": "app.api.checkout::checkout_endpoint",
  "purpose": "Handles checkout requests and calls payment processing.",
  "side_effects": ["charges payment", "updates order"],
  "inputs": ["CheckoutRequest"],
  "outputs": ["CheckoutResponse"],
  "risk_level": "high",
  "edit_relevance": 0.94,
  "task_reason": "The task asks to add validation before payment processing.",
  "needs_full_source": true
}

Semantic cards are not raw repo summaries. They are compact, graph-grounded, task-aware annotations over the deterministic manifest.

11. Agent Roles

Context Compiler uses a small multi-agent workflow.

11.1 Compiler Agent

Runs deterministic analysis:

repo → AST graph → compact manifest

Usually implemented by quantizer.py.

11.2 Semantic Card Agent

Reads compact manifest excerpts and retained source bodies.

Outputs tiny semantic cards:

compact manifest → semantic_cards.jsonl
11.3 Task Router Agent

Combines:

task keywords,
graph structure,
node tags,
semantic cards,
dependency neighbors.

Outputs:

selected files,
selected nodes,
dependency path,
source snippets needed.
11.4 Patch Agent

Reads only the selected source snippets and task context.

Outputs:

proposed unified diff,
patch report,
explanation of edit.
11.5 Validator Agent

Runs tests or syntax checks.

Outputs:

validation report,
failure summary,
optional repair suggestion.
11.6 Managed Sandbox Agent

Runs the workflow inside a Google Managed Agent remote Linux environment when credentials are available.

Fallback local mode is required for demo reliability.

12. Main Components
12.1 quantizer.py

Responsible for deterministic structural compilation.

Command:

python quantizer.py \
  --repo ./demo_repo \
  --out codebase_manifest.txt \
  --target-ratio 0.15 \
  --format compact \
  --debug-out codebase_manifest.debug.json

Responsibilities:

recursively scan Python files,
ignore virtualenv/cache/generated files,
parse AST,
extract modules/classes/functions/methods,
resolve imports/calls/inheritance/routes,
classify unresolved symbols,
compute node scores,
enforce token budget,
emit compact manifest,
emit debug JSON,
print compression and graph metrics.
12.2 semantic_cards.py

Responsible for semantic compression.

Command:

python semantic_cards.py \
  --manifest codebase_manifest.txt \
  --debug-json codebase_manifest.debug.json \
  --out semantic_cards.jsonl \
  --task "Add request validation to the checkout endpoint before payment processing"

Responsibilities:

select important nodes,
call Gemini if configured,
fall back to deterministic card generation,
emit JSONL semantic cards,
keep cards compact and grounded.
12.3 agent_harness.py

Responsible for task routing and edit planning.

Command:

python agent_harness.py \
  --manifest codebase_manifest.txt \
  --semantic-cards semantic_cards.jsonl \
  --task "Add request validation to the checkout endpoint before payment processing" \
  --out edit_plan.md

Responsibilities:

select relevant files,
select relevant nodes,
compute dependency path,
explain why each node matters,
identify source snippets needed,
optionally ask Gemini for an edit plan,
provide deterministic fallback.
12.4 source_loader.py

Responsible for loading only selected original snippets.

Command:

python source_loader.py \
  --repo ./demo_repo \
  --debug-json codebase_manifest.debug.json \
  --selected edit_plan.json \
  --out selected_context.md

Responsibilities:

map node aliases to file paths,
extract exact line ranges,
include minimal surrounding context,
avoid dumping unrelated files.
12.5 patch_agent.py

Responsible for producing a patch.

Command:

python patch_agent.py \
  --repo ./demo_repo \
  --manifest codebase_manifest.txt \
  --semantic-cards semantic_cards.jsonl \
  --task "Add request validation to the checkout endpoint before payment processing" \
  --out proposed_patch.diff

Responsibilities:

load selected context,
call Gemini if configured,
produce unified diff,
write patch report,
optionally apply patch only with --apply.
12.6 validator_agent.py

Responsible for validation.

Command:

python validator_agent.py \
  --repo ./demo_repo \
  --test-command "pytest -q" \
  --out validation_report.md

Responsibilities:

run tests,
fall back to python -m compileall,
capture stdout/stderr,
summarize pass/fail,
optionally suggest repair.
12.7 main.py

Responsible for Managed Agent orchestration.

Commands:

python main.py --smoke-test
python main.py \
  --repo-url https://github.com/example/example_repo \
  --target-ratio 0.15 \
  --task "Add request validation to the checkout endpoint before payment processing"

Responsibilities:

initialize Google Managed Agent client when configured,
create or reuse remote sandbox,
clone/mount repo,
run pipeline remotely,
retrieve artifacts,
fall back to local execution if remote mode is unavailable.
12.8 viewer.py

Responsible for static dashboard generation.

Command:

python viewer.py \
  --manifest codebase_manifest.txt \
  --debug-json codebase_manifest.debug.json \
  --semantic-cards semantic_cards.jsonl \
  --edit-plan edit_plan.md \
  --patch-report patch_report.md \
  --validation-report validation_report.md \
  --out demo.html

Responsibilities:

show compression metrics,
show graph metrics,
show selected files/nodes,
show semantic cards,
show dependency path,
show proposed patch,
show validation status,
remain fully static HTML.
13. Canonical Demo Task

The controlled demo repository should contain a realistic Python service:

demo_repo/
  app/
    api/
      checkout.py
      users.py
      catalog.py
    services/
      payments.py
      fraud.py
      inventory.py
    models/
      checkout.py
      user.py
      payment.py
    utils/
      validation.py
      logging.py
      money.py
  tests/
    test_checkout.py

Canonical task:

Add request validation to the checkout endpoint before payment processing.

Expected system behavior:

Quantizer identifies:
checkout endpoint,
validation helper,
payment processor,
checkout request schema,
relevant tests.
Semantic cards mark checkout as high edit relevance.
Task router selects:
app/api/checkout.py,
app/utils/validation.py,
app/services/payments.py,
related test file.
Patch agent proposes adding validation before payment execution.
Validator runs tests or syntax checks.
Dashboard shows compressed context → selected files → patch → validation.
14. Live Demo Flow
Step 1 — Managed Agent smoke test
python main.py --smoke-test

Show:

environment ID if remote mode works,
OS info,
Python version,
fallback local mode if credentials unavailable.
Step 2 — Compile repository context
python quantizer.py \
  --repo ./demo_repo \
  --out codebase_manifest.txt \
  --target-ratio 0.15 \
  --format compact \
  --debug-out codebase_manifest.debug.json

Show:

original tokens,
compressed tokens,
compression ratio,
token savings,
nodes,
edges,
resolved edge rate,
retained body nodes.
Step 3 — Generate semantic cards
python semantic_cards.py \
  --manifest codebase_manifest.txt \
  --debug-json codebase_manifest.debug.json \
  --out semantic_cards.jsonl \
  --task "Add request validation to the checkout endpoint before payment processing"

Show:

Gemini mode or fallback mode,
cards generated,
high-relevance checkout card.
Step 4 — Route task and generate edit plan
python agent_harness.py \
  --manifest codebase_manifest.txt \
  --semantic-cards semantic_cards.jsonl \
  --task "Add request validation to the checkout endpoint before payment processing" \
  --out edit_plan.md

Show:

selected files,
dependency path,
reason for each selected node.
Step 5 — Generate patch and validate
python patch_agent.py \
  --repo ./demo_repo \
  --manifest codebase_manifest.txt \
  --semantic-cards semantic_cards.jsonl \
  --task "Add request validation to the checkout endpoint before payment processing" \
  --out proposed_patch.diff

Optional:

python patch_agent.py ... --apply
python validator_agent.py --repo ./demo_repo --test-command "pytest -q" --out validation_report.md

Show:

proposed diff,
validation status.
Step 6 — Open dashboard
python viewer.py \
  --manifest codebase_manifest.txt \
  --debug-json codebase_manifest.debug.json \
  --semantic-cards semantic_cards.jsonl \
  --edit-plan edit_plan.md \
  --patch-report patch_report.md \
  --validation-report validation_report.md \
  --out demo.html

Closing line:

We did not build a repo chatbot. We built a compiler layer and managed-agent workflow that turns codebases into compressed execution manifests for targeted code edits.
15. Metrics

The system reports:

Compression Ratio = compressed_manifest_tokens / raw_repository_tokens
Token Savings = 1 - Compression Ratio
Resolved Edge Rate = resolved_edges / total_edges
Full Body Retention Rate = full_body_nodes / total_nodes
Signature Retention Rate = signature_nodes / total_nodes
Semantic Card Coverage = semantic_cards / selected_important_nodes
Patch Context Ratio = selected_source_tokens / raw_repository_tokens
Validation Status = pass / fail / not run

Example stdout:

Context Compiler Quantizer Summary
----------------------------------
Repository: demo_repo
Original tokens: 482193
Compressed tokens: 61842
Compression ratio: 0.128
Token savings: 87.2%
Target ratio: 0.150
Budget status: HIT

Graph Summary
-------------
Files: 48
Nodes: 312
Edges: 1021
Resolved edges: 820
Unresolved edges: 201
Resolved edge rate: 80.3%
Full-body nodes: 22
Signature-only nodes: 290

Semantic Agent Layer
--------------------
Mode: Gemini
Cards generated: 24
Task: Add request validation to the checkout endpoint before payment processing

Task Router
-----------
Selected files:
1. app/api/checkout.py
2. app/utils/validation.py
3. app/services/payments.py

Patch Agent
-----------
Patch generated: yes
Patch applied: dry-run

Validator
---------
Validation: not run
16. Reliability Requirements

The demo must not crash because of one fragile component.

Required fallbacks:

If a file cannot be parsed, log and continue.
If a node has no body, keep signature metadata.
If target ratio cannot be reached because metadata baseline is too large, enable aggressive compaction and report honestly.
If Gemini fails, use deterministic semantic cards.
If Managed Agent remote mode fails, use local fallback.
If patch generation fails, still output selected files and edit plan.
If tests are missing, run syntax checks.
If patch application fails, write failure report and preserve repo state.
17. Hackathon Rule Compliance

The repository must be public.

The demo must distinguish:

code written during the hackathon,
third-party repositories used only as input data,
generated artifacts such as manifests, semantic cards, dashboards, and patches.

The project must not claim ownership of third-party repositories.

The demo should highlight the features built during the hackathon:

Managed Agent orchestration,
AST graph extraction,
structural quantization,
compact manifest generation,
Gemini semantic-card agents,
task routing,
patch generation,
validation,
static dashboard.
18. Implementation Priorities
Must Have
Working compact manifest generation.
True compression metrics.
Improved graph resolution.
Deterministic fallback for all agentic steps.
Semantic cards from Gemini or fallback.
Task-to-file routing.
Patch-like output.
Static dashboard.
Public GitHub repository.
Clean 3-minute demo.
Should Have
Managed Agent smoke test.
Remote sandbox execution.
Persistent environment reuse.
Test or compile validation.
Git diff rendering.
Demo script.
Nice to Have
PageRank centrality.
Edge-type entropy.
Multi-repo benchmark.
JavaScript/TypeScript support.
One-step remote demo.
Do Not Build During Hackathon
IDE extension.
Production-grade dependency resolution.
Full multi-language compiler.
Neural compression over raw code.
Large benchmark suite.
Database-backed service.
Streamlit app.
Heavy frontend framework.
19. Winning Positioning

Context Compiler wins by showing that agentic code editing should not start by dumping an entire repository into context.

Instead:

Compile first.
Compress structurally.
Enrich semantically.
Route task-specific context.
Patch safely.
Validate in sandbox.