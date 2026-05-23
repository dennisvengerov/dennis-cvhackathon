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
from typing import List, Dict, Any, Set, Tuple, Optional

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
        "--json-out",
        type=str,
        default=None,
        help="Path to write machine-readable JSON routing info (default: None)"
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

def compute_node_score(node: Dict[str, Any], card: Optional[Dict[str, Any]], task_keywords: Set[str]) -> Tuple[float, str]:
    """
    Computes a comprehensive score for routing relevance and a grounding reason.
    """
    score = 0.0
    reasons = []
    
    name = node.get("name", "").lower()
    file = node.get("file", "").lower()
    signature = node.get("signature", "").lower()
    tags = [t.lower() for t in node.get("tags", [])]
    
    # 1. Base on Semantic Card relevance if present
    if card:
        relevance = card.get("edit_relevance", 0.0)
        score += relevance * 50.0
        reasons.append(f"Semantic Card relevance {relevance} ({card.get('task_reason', '')})")
    
    # 2. Keyword matching
    matches = []
    for word in task_keywords:
        if word in name:
            score += 15.0
            matches.append(word)
        if word in file:
            score += 8.0
            matches.append(word)
        if word in signature:
            score += 5.0
            matches.append(word)
            
    if matches:
        reasons.append(f"Keyword matches: {', '.join(set(matches))}")
        
    # 3. Component boosts
    # Checkout boosts
    if any(k in name or k in file for k in ["checkout", "order"]):
        score += 20.0
        reasons.append("Checkout component match")
        if "endpoint" in tags or "route" in tags or "api" in file or "router" in file:
            score += 25.0
            reasons.append("Route/Endpoint checkout handler boost")
            
    # Validation / Schema boosts
    if any(k in name or k in file or k in signature for k in ["validate", "validation", "schema", "productbase", "checkoutrequest"]):
        score += 30.0
        reasons.append("Validation/Schema component match")
        if node.get("type") in ["class", "function", "method"]:
            score += 15.0
            reasons.append("Concrete validation schema/handler")
            
    # Payment / Stripe boosts
    if any(k in name or k in file or k in signature for k in ["payment", "stripe"]):
        score += 20.0
        reasons.append("Payment/Stripe component match")
        if node.get("type") in ["method", "function"]:
            score += 15.0
            reasons.append("Payment execution method")

    # Product / stock boosts
    if any(k in name or k in file for k in ["product", "inventory", "stock"]):
        score += 10.0
        reasons.append("Product/Inventory component match")

    # 4. Node type preferences
    if node.get("name") == "<module>":
        score = -100.0  # Strongly avoid choosing <module> directly
        reasons.append("Module node (penalized)")
    elif node.get("type") in ["function", "method"]:
        score += 10.0
        reasons.append("Preferred executable node type")
    elif node.get("type") == "class":
        score += 8.0
        reasons.append("Preferred class definition node type")

    # 5. Centrality boost
    in_deg = node.get("in_degree", 0)
    out_deg = node.get("out_degree", 0)
    score += min(5.0, (in_deg + out_deg) * 0.2)

    reason_str = "; ".join(reasons) if reasons else "Heuristic structural match"
    return max(0.0, score), reason_str

def map_edge_relation(edge: Dict[str, Any], parser: ManifestParser) -> str:
    """
    Standardizes relation types based on defined schemas and nodes information.
    """
    src_node = parser.get_node(edge["source"])
    dst_node = parser.get_node(edge["target"])
    
    if edge.get("type") == "import":
        return "import"
        
    if src_node and (src_node.get("type") == "test" or src_node.get("name", "").startswith("test_")):
        return "test_call"
        
    if edge["target"].startswith("EXT:"):
        return "external_call"
        
    if dst_node:
        t_type = dst_node.get("type", "").lower()
        if t_type == "class":
            return "class_ref"
        elif t_type in ["method"]:
            return "method_call"
        elif t_type in ["function", "fn"]:
            return "call"
            
    # Fallback heuristic
    symbol = edge.get("symbol", "").lower()
    if "." in symbol:
        parts = symbol.split(".")
        if len(parts) > 1 and parts[0][0].islower():
            return "method_call"
        return "call"
        
    return "unknown"

def find_all_paths(parser: ManifestParser, selected_nodes_list: List[Dict[str, Any]]) -> List[List[str]]:
    """
    Finds direct or multi-hop paths among the selected nodes using parsed edges.
    If no connected paths exist, returns direct outbound relations.
    """
    adj = {}
    for edge in parser.edges:
        src = edge["source"]
        if src not in adj:
            adj[src] = []
        adj[src].append(edge)
        
    selected_aliases = {n["alias"] for n in selected_nodes_list}
    
    # Sort selected nodes to try route/endpoints/functions as sources first
    sources = []
    for n in selected_nodes_list:
        if "route" in n.get("tags", []) or "endpoint" in n.get("tags", []) or n.get("type") in ["function", "method"]:
            sources.append(n)
    for n in selected_nodes_list:
        if n not in sources:
            sources.append(n)
            
    paths = []
    visited_pairs = set()
    
    for src_node in sources:
        src_alias = src_node["alias"]
        queue = [[src_alias]]
        while queue:
            curr_path = queue.pop(0)
            u = curr_path[-1]
            
            if u != src_alias and u in selected_aliases:
                pair = (src_alias, u)
                if pair not in visited_pairs:
                    visited_pairs.add(pair)
                    name_path = [parser.get_node_display_name(alias) for alias in curr_path]
                    paths.append(name_path)
            
            for edge in adj.get(u, []):
                v = edge["target"]
                if v not in curr_path:
                    queue.append(curr_path + [v])
                    
    # Fallback to direct edges from selected nodes
    if not paths:
        for n in selected_nodes_list:
            for edge in parser.get_edges_for_node(n["alias"]):
                if edge["source"] == n["alias"]:
                    paths.append([n["name"], edge["symbol"]])
                    
    # Clean duplicates and subpaths
    unique_paths = []
    for p in paths:
        if p not in unique_paths:
            unique_paths.append(p)
            
    return unique_paths[:5]

def main():
    args = parse_args()
    
    # 1. Load manifest and semantic cards
    if not os.path.exists(args.manifest):
        print(f"Error: manifest file '{args.manifest}' not found.", file=sys.stderr)
        sys.exit(1)
        
    parser = ManifestParser(args.manifest, args.debug_json if os.path.exists(args.debug_json) else None)
    cards = load_semantic_cards(args.semantic_cards)
    
    # Task keywords for heuristics
    task_keywords = {w.lower() for w in re.findall(r"[a-zA-Z0-9_]+", args.task.lower()) if len(w) >= 3}
    
    # Map cards to node id for faster lookup
    cards_map = {c["node_id"]: c for c in cards}
    
    # 2. Score all nodes
    scored_nodes = []
    for node in parser.nodes:
        alias = node["alias"]
        card = cards_map.get(alias) or cards_map.get(node["id"])
        score, reason = compute_node_score(node, card, task_keywords)
        scored_nodes.append((score, reason, node))
        
    # Sort nodes by score descending
    scored_nodes.sort(key=lambda x: x[0], reverse=True)
    
    # 3. Select top nodes
    # We select concrete nodes with high scores (score >= 15.0 or top 4 concrete nodes)
    selected_node_entries = []
    for score, reason, node in scored_nodes:
        if node["name"] == "<module>":
            continue
        selected_node_entries.append((score, reason, node))
        
    if len(selected_node_entries) < 3:
        # Fallback to top concrete nodes anyway
        selected_node_entries = [entry for entry in scored_nodes if entry[2]["name"] != "<module>"][:4]
        
    # Cap selection to a reasonable limit (e.g. top 6 concrete nodes)
    selected_node_entries = selected_node_entries[:6]
    selected_nodes = [entry[2] for entry in selected_node_entries]
    selected_node_aliases = {n["alias"] for n in selected_nodes}
    selected_file_aliases_with_concrete = {n["file_alias"] for n in selected_nodes}

    # Secondary selection pass for companion validation/model/schema files if triggered by task
    task_lower = args.task.lower()
    companion_keywords = ["validation", "validate", "request validation", "request", "schema", "model", "pydantic", "input", "payload"]
    trigger_companion = any(kw in task_lower for kw in companion_keywords)
    
    companion_files_to_add_empty = []
    if trigger_companion:
        candidate_files = []
        for f_alias, f_path in parser.files.items():
            if f_alias in selected_file_aliases_with_concrete:
                continue
            fp = f_path.lower()
            score = 0
            if "validation" in fp or "validate" in fp:
                score += 10
            if "schema" in fp:
                score += 8
            if "model" in fp:
                score += 6
                if "checkout" in fp:
                    score += 2
                if "payment" in fp:
                    score += 2
            if "request" in fp:
                score += 4
                
            if score > 0:
                candidate_files.append((score, f_alias, f_path))
                
        # Sort candidates by score descending
        candidate_files.sort(key=lambda x: x[0], reverse=True)
        
        # Add up to 3 companion files
        for score, f_alias, f_path in candidate_files[:3]:
            file_nodes = [n for n in parser.nodes if n["file_alias"] == f_alias]
            concrete_nodes = [n for n in file_nodes if n["name"] != "<module>"]
            if concrete_nodes:
                scored_concrete = []
                for cn in concrete_nodes:
                    c_card = cards_map.get(cn["alias"]) or cards_map.get(cn["id"])
                    c_score, c_reason = compute_node_score(cn, c_card, task_keywords)
                    scored_concrete.append((c_score, c_reason, cn))
                scored_concrete.sort(key=lambda x: x[0], reverse=True)
                
                # Add the top concrete node
                top_score, top_reason, top_node = scored_concrete[0]
                if top_node["alias"] not in selected_node_aliases:
                    selected_node_entries.append((
                        top_score,
                        f"Companion validation/model context selected due to request-validation task intent. ({top_reason})",
                        top_node
                    ))
                    selected_nodes.append(top_node)
                    selected_node_aliases.add(top_node["alias"])
                    selected_file_aliases_with_concrete.add(f_alias)
            else:
                # No concrete nodes, we add the file directly as an empty-node companion file
                companion_files_to_add_empty.append((f_alias, f_path))
    
    # 4. Group by files and generate reasons
    selected_files = {} # file_alias -> dict of file details
    for score, reason, node in selected_node_entries:
        file_alias = node["file_alias"]
        f_path = node["file"]
        if file_alias not in selected_files:
            selected_files[file_alias] = {
                "file_alias": file_alias,
                "path": f_path,
                "reasons": [f"Contains {node['name']} ({reason})"],
                "max_score": score,
                "selected_nodes": [node["alias"]]
            }
        else:
            selected_files[file_alias]["reasons"].append(f"contains {node['name']}")
            selected_files[file_alias]["selected_nodes"].append(node["alias"])
            selected_files[file_alias]["max_score"] = max(selected_files[file_alias]["max_score"], score)
            
    # Add empty-node companion files to selected_files with clear reason
    for f_alias, f_path in companion_files_to_add_empty:
        if f_alias not in selected_files:
            selected_files[f_alias] = {
                "file_alias": f_alias,
                "path": f_path,
                "reasons": ["Companion validation/model context selected due to request-validation task intent."],
                "max_score": 10.0,
                "selected_nodes": []
            }
            
    # Format selected_files list for output
    formatted_selected_files = []
    for alias, val in selected_files.items():
        reasons_combined = "; also ".join(val["reasons"])
        formatted_selected_files.append({
            "file_alias": alias,
            "path": val["path"],
            "reason": reasons_combined,
            "score": val["max_score"],
            "selected_nodes": val["selected_nodes"]
        })
        
    # Sort files by score descending
    formatted_selected_files.sort(key=lambda x: x["score"], reverse=True)
    
    # 5. Dependency Paths
    paths = find_all_paths(parser, selected_nodes)
    dependency_path_str_list = [" -> ".join(p) for p in paths]
    if not dependency_path_str_list:
        dependency_path_str_list = [" -> ".join([n["name"] for n in selected_nodes])]
        
    # 6. Selected Edges with cleaned standardized relation and symbols
    selected_edges = []
    for edge in parser.edges:
        if edge["source"] in selected_node_aliases or edge["target"] in selected_node_aliases:
            standardized_relation = map_edge_relation(edge, parser)
            
            tgt_node = parser.get_node(edge["target"])
            symbol = edge["symbol"]
            if tgt_node:
                symbol = tgt_node.get("name", symbol)
                
            selected_edges.append({
                "source": edge["source"],
                "target": edge["target"],
                "relation": standardized_relation,
                "symbol": symbol,
                "resolved": edge["resolved"]
            })
            
    # Determine LLM usage
    api_key_set = bool(os.environ.get("GEMINI_API_KEY"))
    use_llm = not args.no_llm and api_key_set
    
    mode_str = "Gemini" if use_llm else "deterministic fallback"
    model_str = args.model if use_llm else "deterministic fallback"
    
    plan_content = ""
    if use_llm:
        # Gemini-based plan generation
        prompt_tpl_path = "prompts/task_router_prompt.md"
        if os.path.exists(prompt_tpl_path):
            with open(prompt_tpl_path, "r", encoding="utf-8") as pf:
                prompt_tpl = pf.read()
        else:
            prompt_tpl = "TASK: {task}\nMANIFEST EXCERPT:\n{manifest_excerpt}\nCARDS:\n{semantic_cards_data}\nPlease output a markdown edit plan."
            
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
        
        # Filter cards for selected nodes
        matched_cards = [cards_map[a] for a in selected_node_aliases if a in cards_map]
        
        prompt = prompt_tpl.format(
            task=args.task,
            manifest_excerpt=manifest_excerpt,
            semantic_cards_data=json.dumps(matched_cards, indent=2)
        )
        
        plan_content = llm_client.generate_content(prompt, model=args.model)
        if not plan_content:
            print("Warning: Gemini edit plan generation failed. Falling back to deterministic plan.", file=sys.stderr)
            use_llm = False
            mode_str = "deterministic fallback (due to LLM failure)"
            model_str = "deterministic fallback"
            
    if not use_llm:
        # Beautiful structured fallback markdown plan
        snippets = []
        for entry in selected_node_entries:
            score, reason, n = entry
            if n.get("body"):
                snippets.append(f"### {n['alias']} {n['qualified_name']} (score: {score:.2f})\n```python\n{n['body']}\n```")
            else:
                snippets.append(f"### {n['alias']} {n['qualified_name']} (score: {score:.2f})\n*(Signature-only in manifest: `{n['signature']}`)*")
        snippets_str = "\n\n".join(snippets)
        
        files_sec = "\n".join([f"- **{f['file_alias']} {f['path']}**: {f['reason']}" for f in formatted_selected_files])
        nodes_sec = "\n".join([f"- **{entry[2]['alias']} {entry[2]['qualified_name']}** (score: {entry[0]:.2f}): {entry[1]}" for entry in selected_node_entries])
        paths_sec = "\n".join([f"- `{p}`" for p in dependency_path_str_list])
        
        plan_content = f"""# Edit Plan & Task Routing Report (Deterministic Fallback)

### Selected Files & Nodes
{files_sec}

**Nodes Selected:**
{nodes_sec}

### Selected Dependency Path(s)
{paths_sec}

### Proposed Edit Plan
Based on the task: **"{args.task}"**, here is the structured step-by-step edit plan:

1. **Request Validation Definition**:
   - Locate/extend schema or validation helper in the validation files (e.g., definition of schemas, Pydantic models).
   - Define a strong schema (like `CheckoutRequest` or similar) to validate incoming parameters (items, user ID, amounts) before processing.

2. **Integration into Endpoint**:
   - Inspect the checkout endpoint node in the router file (like `checkout_endpoint` in `app/api/checkout.py`).
   - Validate the incoming request parameters against the schema right at the entry point of the endpoint.
   - If validation fails, return an HTTP 400 or appropriate error code immediately.

3. **Stripe & Payment Safety**:
   - Execute payment processing only after all validations have completely succeeded.
   - Protect Stripe session creations or transaction executions behind validation checkpoints to avoid orphaned payment authorizations.

### Snippets Needed / Full Source Requests
{snippets_str}
"""

    # Write edit plan markdown
    with open(args.out, "w", encoding="utf-8") as out_f:
        out_f.write(plan_content)
        
    # Write machine-readable JSON if requested
    if args.json_out:
        json_payload = {
            "task": args.task,
            "mode": mode_str,
            "selected_files": formatted_selected_files,
            "selected_nodes": [
                {
                    "node_id": entry[2]["alias"],
                    "file_alias": entry[2]["file_alias"],
                    "path": entry[2]["file"],
                    "qualified_name": entry[2]["qualified_name"],
                    "simple_name": entry[2]["name"],
                    "type": entry[2]["type"],
                    "tags": entry[2]["tags"],
                    "reason": entry[1],
                    "score": entry[0]
                }
                for entry in selected_node_entries
            ],
            "selected_edges": selected_edges,
            "dependency_paths": paths,
            "warnings": []
        }
        with open(args.json_out, "w", encoding="utf-8") as out_j:
            json.dump(json_payload, out_j, indent=2)
            
    # Print the required hackathon logs!
    print("Task Router")
    print("-----------")
    print(f"Mode: {mode_str}")
    print("Selected files:")
    for idx, f in enumerate(formatted_selected_files, 1):
        print(f"{idx}. {f['file_alias']} {f['path']} reason={f['reason']}")
    print()
    print("Selected nodes:")
    for idx, entry in enumerate(selected_node_entries, 1):
        print(f"{idx}. {entry[2]['alias']} {entry[2]['name']} reason={entry[1]}")
    print()
    print("Selected dependency paths:")
    for p in dependency_path_str_list:
        print(f"- {p}")
    print()
    print("Artifacts:")
    print(f"- {args.out}")
    if args.json_out:
        print(f"- {args.json_out}")
    print()

if __name__ == "__main__":
    main()
