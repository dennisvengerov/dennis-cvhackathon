# Context Compiler: Graph-Driven Codebase Distillation for Managed Agents

## 0. One-Sentence Summary

Context Compiler is a Managed-Agent-powered static analysis system that converts a large codebase into a compact, graph-structured execution manifest, allowing Gemini agents to reason over the repository, identify relevant files/functions, and produce targeted code changes without loading the entire raw codebase into context.

---

## 1. Core Hackathon Claim

Modern coding agents struggle with large repositories because raw source code is expensive, noisy, redundant, and often too large to fit into a single useful reasoning context.

Context Compiler solves this by inserting a compiler layer between the repository and the coding agent.

Instead of passing the entire codebase to the model, we:

1. Mount or clone a repository into a Google Managed Agent remote Linux sandbox.
2. Parse the repository into an Abstract Syntax Tree dependency graph.
3. Score each code node by structural importance per token.
4. Preserve high-value implementation bodies.
5. Collapse low-value code into typed signatures.
6. Emit a compressed `codebase_manifest.json`.
7. Use the compressed manifest to guide an agent toward the correct files, functions, and edit locations.
8. Produce an edit plan or patch mapped back to the original source tree.

This is not a basic RAG app.  
This is a static-analysis compiler pass for agent context.

---

## 2. Why This Matters

Large-context models still face three practical bottlenecks:

1. **Token Waste:** Raw repositories contain boilerplate, repeated utilities, generated files, comments, tests, and irrelevant code paths.
2. **Reasoning Noise:** More context does not automatically mean better reasoning. Agents can become distracted by unrelated implementation details.
3. **Patch Localization:** Coding agents need file paths, line ranges, dependency relationships, and API boundaries more than they need every single implementation body.

Context Compiler creates a dense structural representation of the codebase that keeps the information most useful for agentic code modification.

---

## 3. Mathematical Model

### 3.1 Codebase as a Directed Multi-Graph

We represent a codebase as a directed multi-graph:

\[
G = (V, E)
\]

where:

\[
V = \{v_1, v_2, \ldots, v_n\}
\]

is the set of code nodes, including:

- modules
- classes
- methods
- functions
- endpoints
- schemas
- public APIs

and:

\[
E \subseteq V \times V \times \mathcal{R}
\]

is the set of typed directed edges, where each edge:

\[
e = (u, v, r)
\]

means that code node \(u\) depends on code node \(v\) through relation type \(r\).

Supported relation types:

\[
\mathcal{R} =
\{
\text{call},
\text{import},
\text{inheritance},
\text{reference}
\}
\]

Examples:

- If `checkout_endpoint()` calls `process_payment()`, then:

\[
(\texttt{checkout\_endpoint}, \texttt{process\_payment}, \text{call}) \in E
\]

- If `PaymentService` inherits from `BaseService`, then:

\[
(\texttt{PaymentService}, \texttt{BaseService}, \text{inheritance}) \in E
\]

---

## 4. Node Cost Model

Each code node \(v \in V\) has a raw token cost:

\[
\tau_{\text{full}}(v)
\]

representing the approximate number of tokens needed to include the full implementation body of \(v\).

Each node also has a compressed signature cost:

\[
\tau_{\text{sig}}(v)
\]

representing the approximate number of tokens needed to include only:

- file path
- line range
- node type
- qualified name
- signature
- docstring
- import/call metadata

Usually:

\[
\tau_{\text{sig}}(v) \ll \tau_{\text{full}}(v)
\]

The original codebase token count is:

\[
T(G) = \sum_{v \in V} \tau_{\text{full}}(v)
\]

The compressed manifest token count is:

\[
T(G') =
\sum_{v \in V}
\left[
x_v \tau_{\text{full}}(v)
+
(1 - x_v)\tau_{\text{sig}}(v)
\right]
+
T(E)
\]

where:

\[
x_v =
\begin{cases}
1, & \text{if full body is retained} \\
0, & \text{if only signature is retained}
\end{cases}
\]

and \(T(E)\) is the token cost of serializing graph edges.

---

## 5. Structural Importance Score

The goal is not to keep the shortest nodes or the longest nodes.

The goal is to keep the nodes that provide the most useful structural information per token.

For each node \(v\), define:

\[
d_{\text{in}}(v) =
|\{u : (u, v, r) \in E\}|
\]

\[
d_{\text{out}}(v) =
|\{w : (v, w, r) \in E\}|
\]

where:

- \(d_{\text{in}}(v)\) measures how many other nodes depend on \(v\)
- \(d_{\text{out}}(v)\) measures how many other nodes \(v\) depends on

We also define binary metadata features:

\[
p(v) =
\begin{cases}
1, & \text{if } v \text{ appears to be public or exported} \\
0, & \text{otherwise}
\end{cases}
\]

\[
q(v) =
\begin{cases}
1, & \text{if } v \text{ has a docstring or type annotations} \\
0, & \text{otherwise}
\end{cases}
\]

The primary structural importance score is:

\[
S(v) =
\frac{
2d_{\text{in}}(v)
+
d_{\text{out}}(v)
+
3p(v)
+
q(v)
}{
\log(1 + \tau_{\text{full}}(v))
}
\]

### Intuition

This score rewards nodes that are:

- depended on by many other nodes
- connected to important implementation paths
- public-facing or API-like
- documented or typed
- compact enough to include efficiently

The denominator penalizes large implementation bodies, but only logarithmically, so large important nodes are not automatically discarded.

---

## 6. Optional Edge-Type Entropy

For additional graph structure, each node can also be assigned a dependency entropy score.

Let:

\[
c_r(v)
\]

be the number of incident edges of relation type \(r\) connected to node \(v\), and:

\[
C(v) = \sum_{r \in \mathcal{R}} c_r(v)
\]

Define:

\[
P_r(v) = \frac{c_r(v)}{C(v)}
\]

Then the edge-type entropy of node \(v\) is:

\[
H(v) =
-
\sum_{r \in \mathcal{R}}
P_r(v)\log_2 P_r(v)
\]

A higher \(H(v)\) means the node participates in multiple kinds of relationships, such as calls, imports, inheritance, and references.

The hackathon implementation may use this as an optional bonus term:

\[
S_{\text{final}}(v) =
S(v) + \lambda_H H(v)
\]

where \(\lambda_H\) is a small weighting constant.

For the live demo, the base structural score \(S(v)\) is sufficient and deterministic.

---

## 7. Compression Objective

The compression problem is formulated as a budgeted value maximization problem.

We want to choose which nodes retain full implementations:

\[
x_v \in \{0, 1\}
\]

so that the retained structural value is maximized under a strict token budget:

\[
\max_{x_v}
\sum_{v \in V}
S(v)x_v
\]

subject to:

\[
T(G') \le \alpha T(G)
\]

where:

\[
\alpha \in (0, 0.15]
\]

is the target compression ratio.

For the hackathon demo, the target is:

\[
\alpha = 0.15
\]

meaning the compressed manifest should be at most 15% of the original codebase token volume.

---

## 8. Practical Greedy Approximation

The exact optimization resembles a 0/1 knapsack problem.

For demo reliability, Context Compiler uses a greedy approximation.

For each node, define its marginal value density:

\[
D(v) =
\frac{
S(v)
}{
\tau_{\text{full}}(v) - \tau_{\text{sig}}(v) + 1
}
\]

Nodes are sorted by \(D(v)\), and full bodies are retained until the token budget is reached.

All remaining nodes are converted to signature-only form.

This gives a fast, deterministic algorithm that works well for live demos.

---

## 9. Quantization Operator

The structural quantization operator is:

\[
Q(v) =
\begin{cases}
\text{FullBody}(v), & x_v = 1 \\
\text{SignatureOnly}(v), & x_v = 0
\end{cases}
\]

The compressed graph is:

\[
G' = (V', E)
\]

where:

- \(V'\) contains quantized representations of the original nodes
- \(E\) preserves the dependency topology
- file paths and line numbers are preserved for every node

The important point:

\[
E \text{ is preserved even when implementation bodies are compressed.}
\]

This allows the agent to reason over the structure of the repository even when most code bodies have been removed.

---

## 10. Manifest Format

The compiler emits a single JSON artifact:

```json
{
  "metadata": {
    "repo_path": "./target_repo",
    "original_tokens": 482193,
    "compressed_tokens": 61842,
    "compression_ratio": 0.128,
    "target_ratio": 0.15,
    "node_count": 1248,
    "edge_count": 3912,
    "graph_density": 0.0025,
    "full_body_nodes": 84,
    "signature_only_nodes": 1164
  },
  "nodes": [
    {
      "id": "src/checkout.py::checkout_endpoint",
      "type": "function",
      "name": "checkout_endpoint",
      "qualified_name": "checkout_endpoint",
      "file": "src/checkout.py",
      "start_line": 12,
      "end_line": 68,
      "signature": "def checkout_endpoint(request: CheckoutRequest) -> CheckoutResponse:",
      "docstring": "Handles checkout submission and payment execution.",
      "token_count": 421,
      "in_degree": 8,
      "out_degree": 5,
      "score": 3.82,
      "mode": "full_body",
      "body": "def checkout_endpoint(...): ..."
    }
  ],
  "edges": [
    {
      "source": "src/checkout.py::checkout_endpoint",
      "target": "src/payments.py::process_payment",
      "type": "call"
    }
  ]
}

11. System Architecture
11.1 main.py

Responsible for Google Managed Agent orchestration.

Responsibilities:

initialize the Google GenAI client
create or reuse a remote sandbox environment
mount or clone the target repository
transfer or generate quantizer.py inside the sandbox
execute the compiler inside the remote Linux environment
persist:
environment_id
previous_interaction_id
print clean demo logs

Expected command:

python main.py \
  --repo-url https://github.com/example/example_repo \
  --target-ratio 0.15 \
  --task "Add request validation to the checkout endpoint"
11.2 quantizer.py

Responsible for static analysis and graph compression.

Expected command:

python quantizer.py \
  --repo ./target_repo \
  --out codebase_manifest.json \
  --target-ratio 0.15

Responsibilities:

recursively scan Python files
parse files with Python ast
extract:
modules
classes
methods
functions
async functions
imports
calls
inheritance relationships
compute:
token counts
in-degrees
out-degrees
structural scores
graph density
compression ratio
quantize each node into:
full body
signature only
emit codebase_manifest.json
11.3 agent_harness.py

Responsible for proving that the compressed manifest is useful.

Expected command:

python agent_harness.py \
  --manifest codebase_manifest.json \
  --task "Add request validation to the checkout endpoint"

Responsibilities:

load the compressed manifest
select relevant nodes based on:
task keywords
file paths
function names
signatures
docstrings
dependency neighbors
package the relevant compressed context
ask Gemini or the Managed Agent for an edit plan
output:
likely files to edit
relevant functions/classes
dependency path
proposed patch or implementation plan

The fallback deterministic mode should work even if the API call fails.

11.4 viewer.py

Responsible for visual proof during the live demo.

Expected command:

python viewer.py \
  --manifest codebase_manifest.json \
  --out demo.html

The generated dashboard should show:

original token count
compressed token count
compression ratio
target ratio
number of nodes
number of edges
graph density
full-body retained nodes
signature-only nodes
top retained nodes by score
top depended-on nodes
manifest preview
relevant edit path for the demo task

The viewer must be a static HTML page.

Do not use Streamlit.

12. Demo Repository

The project should include a controlled demo_repo/ with a realistic Python service layout:

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

The demo repo should contain enough structure to show meaningful graph compression, but it should remain small enough for reliable live execution.

The canonical demo task:

Add request validation to the checkout endpoint before payment processing.

Expected behavior:

The manifest should identify checkout.py, validation.py, and payments.py as relevant.
The agent should propose editing the checkout endpoint.
The patch should add validation before calling payment execution.
13. Live Demo Flow

The three-minute live demo should follow this sequence:

Step 1: Remote Sandbox Proof

Run:

python main.py --smoke-test

Show that a Google Managed Agent remote Linux sandbox is created and returns:

environment ID
OS info
Python version
Step 2: Compile Repo Context

Run:

python quantizer.py \
  --repo ./demo_repo \
  --out codebase_manifest.json \
  --target-ratio 0.15

Show metrics:

Original tokens: 482193
Compressed tokens: 61842
Compression ratio: 12.8%
Nodes found: 1248
Edges found: 3912
Full-body nodes retained: 84
Signature-only nodes: 1164
Graph density: 0.0025
Step 3: Visualize Manifest

Run:

python viewer.py \
  --manifest codebase_manifest.json \
  --out demo.html

Open the dashboard and show:

compression bar
retained high-value nodes
dependency graph summary
manifest preview
Step 4: Agent Uses Compressed Context

Run:

python agent_harness.py \
  --manifest codebase_manifest.json \
  --task "Add request validation to the checkout endpoint"

Show:

selected relevant files
dependency path
proposed patch
original file mapping
Step 5: Closing Claim

End with:

We did not build a repo chatbot. We built a compiler pass that transforms codebases into agent-optimized execution manifests.
14. Implementation Priorities
Must Have
Working Managed Agent smoke test
Working AST parser
Working manifest generation
Working compression ratio calculation
Working static HTML dashboard
Working task-to-file relevance search
Clear demo task
Public GitHub repository
Should Have
Remote sandbox execution of the quantizer
Persistent environment ID reuse
Dependency graph visualization
Gemini-generated edit plan
Patch-like output
Nice to Have
PageRank centrality
Edge-type entropy term
Multi-repo benchmark
Actual patch application
Git diff rendering
Support for JavaScript/TypeScript
Do Not Build During Hackathon
Neural compression
Full semantic code understanding
Multi-language AST system
IDE extension
Production-grade dependency resolution
Large-scale benchmark suite
Streamlit app
15. Hackathon Rule Compliance

This repository must be public.

The demo must clearly distinguish:

Code written during the hackathon.
Third-party repositories used only as input data.
Generated artifacts such as codebase_manifest.json and demo.html.

The team must not claim ownership over any third-party repository used for testing.

The demo must highlight only the features built during the hackathon:

Managed Agent orchestration
AST graph extraction
structural scoring
quantization
manifest generation
dashboard
compressed-context edit planning
16. Evaluation Metrics

The project should report the following metrics in stdout and in the dashboard:

Compression Ratio=
T(G)
T(G
′
)
	​

Token Savings=1−
T(G)
T(G
′
)
	​

Graph Density=
∣V∣(∣V∣−1)
∣E∣
	​

Full Body Retention Rate=
∣V∣
∣{v:x
v
	​

=1}∣
	​

Signature Compression Rate=
∣V∣
∣{v:x
v
	​

=0}∣
	​


Example stdout:

Context Compiler Summary
------------------------
Original tokens: 482193
Compressed tokens: 61842
Compression ratio: 0.128
Token savings: 87.2%
Target ratio: 0.150

Graph Summary
-------------
Nodes: 1248
Edges: 3912
Graph density: 0.0025
Full-body nodes: 84
Signature-only nodes: 1164

Top retained nodes
------------------
1. app/api/checkout.py::checkout_endpoint
2. app/services/payments.py::process_payment
3. app/models/checkout.py::CheckoutRequest
17. Reliability Requirements

The system should be robust enough for a live hackathon demo.

Requirements:

If a file cannot be parsed, log the error and continue.
If a node has no body, still keep its signature.
If the Managed Agent API fails, use local fallback mode.
If Gemini patch generation fails, use deterministic relevance ranking.
If graph edges cannot be fully resolved, preserve unresolved symbolic calls.
Never crash the demo because of one malformed file.
18. Final Product Definition

The final hackathon product is not merely a script.

The final product is a complete pipeline:

Repository→Managed Agent Sandbox→AST Graph→Structural Quantization→Compressed Manifest→Agent Edit Plan→Original Source Patch

Context Compiler wins by showing that coding agents do not need raw repositories.

They need structured, compressed, dependency-aware execution manifests.