#!/usr/bin/env python3
"""
agent_harness.py

Task Routing and Edit Planning Layer.
Analyzes compact codebase manifest and semantic cards to generate a targeted edit plan.
"""

import os
import sys
import json
import argparse
import re
from typing import List, Dict, Any, Set

from manifest_parser import ManifestParser
import llm_client

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Task routing and edit planner for Context Compiler."
    )
    parser.add_argument(
        "--manifest",
        type=str,
        default="codebase_manifest.txt",
        help="Path to compact manifest (default: codebase_manifest.txt)"
    )
    parser.add_argument(
        "--debug-json",
        type=str,
        default="codebase_manifest.debug.json",
        help="Path to debug JSON manifest (default: codebase_manifest.debug.json)"
    )
    parser.add_argument(
        "--semantic-cards",
        type=str,
        default="semantic_cards.jsonl",
        help="Path to semantic cards jsonl (default: semantic_cards.jsonl)"
    )
    parser.add_argument(
        "--task",
        type=str,
        default="Add request validation to the checkout endpoint before payment processing",
        help="The target task to produce an edit plan for"
    )
    parser.add_argument(
        "--out",
        type=str,
        default="edit_plan.md",
        help="Path to write the proposed edit plan markdown (default: edit_plan.md)"
    )
    parser.add_argument(
        "--model",
        type=str,
        default="gemini-2.5-flash",
        help="Gemini model to use (default: gemini-2.5-flash)"
    )
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="Force deterministic fallback mode without LLM"
    )
    return parser.parse_args()

def load_semantic_cards(path: str) -> List[Dict[str, Any]]:
    """
    Loads semantic cards from JSON Lines format.
    """
    cards = []
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line_strip = line.strip()
            if line_strip:
                try:
                    cards.append(json.loads(line_strip))
                except json.JSONDecodeError:
                    pass
    return cards

def main():
    args = parse_args()
    
    # 1. Load manifest and semantic cards
    if not os.path.exists(args.manifest):
        print(f"Error: manifest file '{args.manifest}' not found.", file=sys.stderr)
        sys.exit(1)
        
    manifest_data = ManifestParser.parse_txt(args.manifest)
    nodes = ManifestParser.get_unified_nodes(args.manifest, args.debug_json if os.path.exists(args.debug_json) else None)
    
    cards = load_semantic_cards(args.semantic_cards)
    
    # If no semantic cards found, generate them deterministically as safety net
    if not cards:
        print("Warning: Semantic cards not found. Generating on-the-fly fallback cards.", file=sys.stderr)
        # fallback keywords
        task_words = {w.lower() for w in re.findall(r"[a-zA-Z0-9_]+", args.task.lower()) if len(w) >= 3}
        # Score and get top nodes
        scored = []
        for n in nodes:
            name = n.get("name", "").lower()
            file = n.get("file", "").lower()
            score = 1.0 if any(w in name or w in file for w in task_words) else 0.1
            scored.append((score, n))
        scored.sort(key=lambda x: x[0], reverse=True)
        # Create dummy cards
        for score, n in scored[:6]:
            cards.append({
                "node_id": n["alias"],
                "file_alias": n["file_alias"],
                "qualified_name": n["qualified_name"],
                "purpose": n.get("docstring") or f"Inferred representation of {n['name']}",
                "side_effects": [],
                "inputs": [],
                "outputs": [],
                "risk_level": "medium",
                "edit_relevance": round(score, 2),
                "task_reason": "On-the-fly generated fallback card.",
                "needs_full_source": n["mode"] in ("sig", "skel")
            })

    # Sort cards by edit_relevance descending
    cards.sort(key=lambda x: x.get("edit_relevance", 0.0), reverse=True)
    
    # Select top highly relevant cards (edit_relevance >= 0.25 or top 3)
    selected_cards = [c for c in cards if c.get("edit_relevance", 0.0) >= 0.25]
    if len(selected_cards) < 2:
        selected_cards = cards[:3]
        
    # Get associated node details
    selected_node_aliases = {c["node_id"] for c in selected_cards}
    selected_nodes = [n for n in nodes if n["alias"] in selected_node_aliases]
    
    # 2. Track selected files and reasons
    selected_files = {} # alias -> (path, reason)
    for card in selected_cards:
        node_alias = card["node_id"]
        file_alias = card["file_alias"]
        node_name = card["qualified_name"].split("::")[-1]
        
        # find matching node
        node = next((n for n in selected_nodes if n["alias"] == node_alias), None)
        file_path = node["file"] if node else manifest_data["files"].get(file_alias, "unknown")
        
        reason = card.get("task_reason", f"Highly relevant to task with score {card.get('edit_relevance')}")
        
        if file_alias not in selected_files:
            selected_files[file_alias] = (file_path, f"Contains {node_name} ({reason})")
        else:
            prev_path, prev_reason = selected_files[file_alias]
            selected_files[file_alias] = (prev_path, f"{prev_reason}; also contains {node_name}")
            
    # 3. Trace Dependency Path among selected nodes
    # We parse the edges from the manifest and construct a subgraph of our selected nodes
    adj_list = {n["alias"]: [] for n in selected_nodes}
    sub_in_degree = {n["alias"]: 0 for n in selected_nodes}
    
    for edge in manifest_data["edges"]:
        src = edge["source"]
        dst = edge["target"]
        if src in selected_node_aliases and dst in selected_node_aliases:
            adj_list[src].append(dst)
            sub_in_degree[dst] += 1
            
    # Topological chain or direct sequence
    start_nodes = [alias for alias in selected_node_aliases if sub_in_degree.get(alias, 0) == 0]
    if not start_nodes:
        start_nodes = list(selected_node_aliases)[:1]
        
    def get_name(alias):
        n = next((x for x in selected_nodes if x["alias"] == alias), None)
        return n["name"] if n else alias
        
    path_strings = []
    visited = set()
    def dfs(u, path):
        visited.add(u)
        path.append(get_name(u))
        has_outgoing = False
        for v in adj_list.get(u, []):
            if v not in visited:
                dfs(v, path)
                has_outgoing = True
                break
        if not has_outgoing:
            path_strings.append(" -> ".join(path))
            
    for start in start_nodes[:1]:
        dfs(start, [])
        
    dependency_path_str = path_strings[-1] if path_strings else " -> ".join([get_name(a) for a in selected_node_aliases])
    
    # 4. Determine LLM usage
    api_key_set = bool(os.environ.get("GEMINI_API_KEY"))
    use_llm = not args.no_llm and api_key_set
    
    plan_content = ""
    mode_str = "Gemini" if use_llm else "deterministic fallback"
    model_str = args.model if use_llm else "deterministic fallback"
    
    if use_llm:
        # Load prompt
        prompt_tpl_path = "prompts/task_router_prompt.md"
        if os.path.exists(prompt_tpl_path):
            with open(prompt_tpl_path, "r", encoding="utf-8") as pf:
                prompt_tpl = pf.read()
        else:
            prompt_tpl = "TASK: {task}\nMANIFEST:\n{manifest_excerpt}\nCARDS:\n{semantic_cards_data}\nPlease output a markdown edit plan."
            
        # Format manifest excerpt
        excerpt_lines = []
        for n in selected_nodes:
            excerpt_lines.append(f"Node: {n['alias']} {n['qualified_name']}")
            excerpt_lines.append(f"  Type: {n['type']} Signature: {n['signature']}")
            if n.get("behavior_skeleton"):
                excerpt_lines.append(f"  Skeleton: {n['behavior_skeleton']}")
            if n.get("body"):
                excerpt_lines.append(f"  Body:\n{n['body']}")
            excerpt_lines.append("-" * 30)
        manifest_excerpt = "\n".join(excerpt_lines)
        
        semantic_cards_data = json.dumps(selected_cards, indent=2)
        
        prompt = prompt_tpl.format(
            task=args.task,
            manifest_excerpt=manifest_excerpt,
            semantic_cards_data=semantic_cards_data
        )
        
        plan_content = llm_client.generate_content(prompt, model=args.model)
        if not plan_content:
            print("Warning: Gemini edit plan generation failed. Falling back to deterministic plan.", file=sys.stderr)
            use_llm = False
            mode_str = "deterministic fallback (due to LLM failure)"
            model_str = "deterministic fallback"
            
    if not use_llm:
        # Generate a beautiful structured deterministic markdown edit plan
        snippets = []
        for n in selected_nodes:
            if n.get("body"):
                snippets.append(f"### {n['alias']} {n['qualified_name']}\n```python\n{n['body']}\n```")
            else:
                snippets.append(f"### {n['alias']} {n['qualified_name']}\n*(Signature-only in manifest: `{n['signature']}`)*")
        snippets_str = "\n\n".join(snippets)
        
        files_sec = "\n".join([f"- **{alias} {path}**: {reason}" for alias, (path, reason) in selected_files.items()])
        nodes_sec = "\n".join([f"- **{card['node_id']} {card['qualified_name']}** (edit_relevance: {card['edit_relevance']}): {card['task_reason']}" for card in selected_cards])
        
        plan_content = f"""# Edit Plan & Task Routing Report (Deterministic Fallback)

### Selected Files & Nodes
{files_sec}

**Nodes Selected:**
{nodes_sec}

### Selected Dependency Path
`{dependency_path_str}`

### Proposed Edit Plan
Based on the task: **"{args.task}"**, here is the structured step-by-step edit plan:

1. **Request Validation Definition**:
   - Locate/extend `{selected_nodes[0]['file'] if selected_nodes else 'src/schemas.py'}` to define or import input validation schemas.
   - For example, if adding request validation before checkout, create or extend a schema `CheckoutRequest` inheriting from `BaseModel`.

2. **Integration into Endpoint**:
   - Inspect the checkout endpoint `{get_name(selected_nodes[0]['alias']) if selected_nodes else 'create_checkout_session'}` in file `{selected_nodes[0]['file'] if selected_nodes else 'src/routers/ui_routes.py'}`.
   - Inject the validation step before invoking the Stripe session creator or payment processor.
   - Ensure you catch parsing or validation exceptions and raise proper `HTTPException(status_code=400, detail=...)`.

3. **Dependency and State Verification**:
   - Ensure the dependency path flow `{dependency_path_str}` executes successfully and validates parameters before payment processing starts.

### Snippets Needed / Full Source Requests
{snippets_str}
"""
        
    # Write edit plan
    with open(args.out, "w", encoding="utf-8") as out_f:
        out_f.write(plan_content)
        
    # Print the required hackathon logs!
    print("Task Router")
    print("-----------")
    print("Selected files:")
    for idx, (alias, (f_path, reason)) in enumerate(selected_files.items(), 1):
        print(f"{idx}. {alias} {f_path} reason={reason}")
    print()
    print("Selected dependency path:")
    print(dependency_path_str)
    print()

if __name__ == "__main__":
    main()
