#!/usr/bin/env python3
"""
semantic_cards.py

Generates tiny semantic cards for the most important nodes.
Supports Gemini enrichment and deterministic fallback when Gemini is unavailable or disabled.
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
        description="Generate semantic enrichment cards for codebase manifest nodes."
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
        "--out",
        type=str,
        default="semantic_cards.jsonl",
        help="Path to output jsonl cards (default: semantic_cards.jsonl)"
    )
    parser.add_argument(
        "--task",
        type=str,
        default="Add request validation to the checkout endpoint before payment processing",
        help="The target task to analyze relevance for"
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
        help="Force deterministic heuristic fallback mode without LLM"
    )
    parser.add_argument(
        "--max-nodes",
        type=int,
        default=12,
        help="Maximum number of nodes to enrich with cards (default: 12)"
    )
    return parser.parse_args()

def extract_task_keywords(task: str) -> Set[str]:
    """
    Tokenizes the task into a set of normalized keywords.
    """
    # Lowercase and split on non-alphanumeric characters
    words = re.findall(r"[a-zA-Z0-9_]+", task.lower())
    # Filter out common stop words
    stop_words = {
        "add", "to", "the", "before", "after", "and", "or", "for", "in", "on", "at", 
        "a", "an", "is", "of", "with", "from", "by", "using", "how", "endpoint", "endpoints"
    }
    return {w for w in words if w not in stop_words and len(w) >= 3}

def compute_heuristic_relevance(node: Dict[str, Any], task_words: Set[str]) -> float:
    """
    Computes a deterministic score of how relevant a node is to the task keywords.
    """
    score = 0.0
    name = node.get("name", "").lower()
    file = node.get("file", "").lower()
    signature = node.get("signature", "").lower()
    tags = [t.lower() for t in node.get("tags", [])]
    skel = node.get("behavior_skeleton", {})
    skel_str = str(skel).lower() if skel else ""
    body = node.get("body", "").lower()
    
    # Keyword matching
    for word in task_words:
        if word in name:
            score += 15.0
            if word == name:
                score += 10.0 # exact name match boost
        if word in file:
            score += 6.0
        if word in signature:
            score += 4.0
        if any(word in tag for tag in tags):
            score += 8.0
        if word in skel_str:
            score += 3.0
        if word in body:
            score += 2.0
            
    # Category semantic boosts
    # Checkout boost
    if "checkout" in task_words or "payment" in task_words or "stripe" in task_words:
        is_checkout_node = "checkout" in name or "checkout" in file or "payment" in name or "payment" in file or "stripe" in name or "stripe" in file
        if is_checkout_node:
            score += 10.0
            if "endpoint" in tags or "route" in tags:
                score += 10.0 # checkout endpoint boost!
                
    # Validation boost
    if "validation" in task_words or "validate" in task_words or "verify" in task_words:
        is_val_node = "validation" in name or "validation" in file or "schema" in name or "schema" in file or "validator" in name or "validate" in name
        if is_val_node:
            score += 12.0
            
    # General API router/endpoint boosts if task talks about endpoint/request
    if "endpoint" in task_words or "request" in task_words:
        if "endpoint" in tags or "route" in tags:
            score += 5.0
            
    # Degree boosts to prioritize central nodes slightly
    in_deg = node.get("in_degree", 0)
    out_deg = node.get("out_degree", 0)
    score += min(5.0, (in_deg + out_deg) * 0.2)
    
    return score

def generate_heuristic_fallback_card(node: Dict[str, Any], task: str, task_words: Set[str], rel_score: float, max_score: float) -> Dict[str, Any]:
    """
    Generates a high-quality deterministic semantic card as fallback.
    """
    name = node.get("name", "")
    file = node.get("file", "")
    tags = node.get("tags", [])
    skel = node.get("behavior_skeleton", {})
    
    # Normalize edit relevance
    norm_relevance = round(min(1.0, rel_score / (max_score if max_score > 0 else 1.0)), 2)
    if norm_relevance < 0.1:
        norm_relevance = 0.1 # floor at 0.1
        
    # Infer purpose
    purpose = node.get("docstring", "").strip()
    if not purpose:
        purpose = f"Module/Function representing '{name}' in file '{file}' with tags: {', '.join(tags)}."
        
    # Infer risk
    risk = "low"
    if any(t in ["payment", "auth", "external_api", "security"] for t in tags) or any(k in name.lower() for k in ["payment", "stripe", "checkout", "authorize"]):
        risk = "high"
    elif any(t in ["database", "validation", "schema"] for t in tags) or "route" in tags or "endpoint" in tags:
        risk = "medium"
        
    # Infer inputs
    inputs = []
    # parse from signature parameters
    sig = node.get("signature", "")
    param_match = re.search(r"\((.*?)\)", sig)
    if param_match:
        params_str = param_match.group(1)
        # split on commas, strip
        params = [p.split(":")[0].strip() for p in params_str.split(",") if p.strip()]
        inputs = [p for p in params if p not in ["self", "cls"]]
    if not inputs and "reads" in skel:
        inputs = skel["reads"]
        
    # Infer outputs
    outputs = []
    ret_match = re.search(r"->\s*([^:]+)", sig)
    if ret_match:
        outputs = [ret_match.group(1).strip()]
    elif "returns" in skel and skel["returns"] != "unknown":
        outputs = [skel["returns"]]
        
    # Side effects
    side_effects = skel.get("effects", [])
    if not side_effects:
        if "payment" in tags or "stripe" in tags:
            side_effects = ["external stripe transaction"]
        elif "database" in tags or "db_write" in tags:
            side_effects = ["database state mutation"]
        else:
            side_effects = []
            
    # Task reason
    matched = [w for w in task_words if w in name.lower() or w in file.lower() or any(w in t.lower() for t in tags)]
    if matched:
        task_reason = f"Node matches task keywords: {', '.join(matched)}."
    else:
        task_reason = "Selected due to graph dependency or structural importance in the neighborhood."
        
    # Needs full source
    needs_source = node.get("mode") in ("sig", "skel") and norm_relevance >= 0.5
    
    return {
        "node_id": node.get("alias", "N_unknown"),
        "file_alias": node.get("file_alias", "F_unknown"),
        "qualified_name": node.get("qualified_name", f"{file}::{name}"),
        "purpose": purpose,
        "side_effects": side_effects,
        "inputs": inputs if inputs else ["unknown"],
        "outputs": outputs if outputs else ["unknown"],
        "risk_level": risk,
        "edit_relevance": norm_relevance,
        "task_reason": task_reason,
        "needs_full_source": needs_source
    }

def main():
    args = parse_args()
    
    # Load and unify manifest + debug JSON
    manifest_exists = os.path.exists(args.manifest)
    debug_exists = os.path.exists(args.debug_json)
    
    if not manifest_exists:
        print(f"Error: manifest file '{args.manifest}' not found.", file=sys.stderr)
        sys.exit(1)
        
    nodes = ManifestParser.get_unified_nodes(args.manifest, args.debug_json if debug_exists else None)
    
    # Extract task keywords
    task_keywords = extract_task_keywords(args.task)
    
    # Compute heuristic relevance for all nodes
    scored_nodes = []
    for node in nodes:
        score = compute_heuristic_relevance(node, task_keywords)
        scored_nodes.append((score, node))
        
    # Sort by relevance in descending order
    scored_nodes.sort(key=lambda x: x[0], reverse=True)
    max_score = scored_nodes[0][0] if scored_nodes else 1.0
    
    # Select candidate nodes up to max_nodes
    selected_node_entries = scored_nodes[:args.max_nodes]
    selected_nodes = [node for score, node in selected_node_entries]
    
    # Determine mode: Gemini or Fallback
    api_key_set = bool(os.environ.get("GEMINI_API_KEY"))
    use_llm = not args.no_llm and api_key_set
    
    final_cards = []
    actual_model_used = args.model if use_llm else "deterministic fallback"
    mode_str = "Gemini" if use_llm else "deterministic fallback"
    
    if use_llm:
        # Load prompt template
        prompt_template_path = "prompts/semantic_card_prompt.md"
        if os.path.exists(prompt_template_path):
            with open(prompt_template_path, "r", encoding="utf-8") as pf:
                prompt_tpl = pf.read()
        else:
            prompt_tpl = "USER TASK: {task}\nCANDIDATE NODES:\n{nodes_data}\nPlease produce strict JSON output for semantic cards."
            
        # Format candidate nodes data for LLM
        nodes_data_list = []
        for score, node in selected_node_entries:
            body_content = node.get("body", "")
            node_desc = (
                f"Node ID: {node.get('alias')}\n"
                f"File path: {node.get('file')} (Alias: {node.get('file_alias')})\n"
                f"Qualified Name: {node.get('qualified_name')}\n"
                f"Type: {node.get('type')}\n"
                f"Signature: {node.get('signature')}\n"
                f"Docstring: {node.get('docstring')}\n"
                f"Tags: {node.get('tags')}\n"
                f"Behavior Skeleton: {node.get('behavior_skeleton')}\n"
            )
            if body_content:
                node_desc += f"Code Body:\n{body_content}\n"
            else:
                node_desc += "Code Body: (No body available, only signature/skeleton)\n"
            node_desc += "---------------------\n"
            nodes_data_list.append(node_desc)
            
        nodes_data_str = "".join(nodes_data_list)
        
        # Max token/length guard
        # If nodes_data_str is too large, we can truncate bodies
        max_card_chars = 45000 # ~12000 tokens
        if len(nodes_data_str) > max_card_chars:
            # truncate bodies of lower scoring nodes to fit safely
            nodes_data_list_truncated = []
            char_count = 0
            for score, node in selected_node_entries:
                body_content = node.get("body", "")
                node_desc = (
                    f"Node ID: {node.get('alias')}\n"
                    f"File path: {node.get('file')} (Alias: {node.get('file_alias')})\n"
                    f"Qualified Name: {node.get('qualified_name')}\n"
                    f"Type: {node.get('type')}\n"
                    f"Signature: {node.get('signature')}\n"
                    f"Docstring: {node.get('docstring')}\n"
                    f"Tags: {node.get('tags')}\n"
                    f"Behavior Skeleton: {node.get('behavior_skeleton')}\n"
                )
                if body_content:
                    if char_count + len(body_content) > max_card_chars:
                        node_desc += "Code Body: (Truncated to safeguard prompt length)\n"
                    else:
                        node_desc += f"Code Body:\n{body_content}\n"
                        char_count += len(body_content)
                else:
                    node_desc += "Code Body: (No body available, only signature/skeleton)\n"
                node_desc += "---------------------\n"
                nodes_data_list_truncated.append(node_desc)
            nodes_data_str = "".join(nodes_data_list_truncated)
            
        prompt = prompt_tpl.format(task=args.task, nodes_data=nodes_data_str)
        
        # Call Gemini
        response_text = llm_client.generate_content(prompt, model=args.model, json_mode=True)
        parsed_response = llm_client.extract_json_block(response_text) if response_text else None
        
        if parsed_response and "cards" in parsed_response:
            final_cards = parsed_response["cards"]
        else:
            print("Warning: Gemini enrichment failed or returned invalid JSON. Falling back to deterministic card generation.", file=sys.stderr)
            use_llm = False
            mode_str = "deterministic fallback (due to LLM parse failure)"
            actual_model_used = "deterministic fallback"
            
    if not use_llm:
        # Generate cards deterministically
        for score, node in selected_node_entries:
            card = generate_heuristic_fallback_card(node, args.task, task_keywords, score, max_score)
            final_cards.append(card)
            
    # Write semantic_cards.jsonl
    with open(args.out, "w", encoding="utf-8") as out_f:
        for card in final_cards:
            out_f.write(json.dumps(card) + "\n")
            
    # Print the required hackathon logs!
    print("Semantic Agent Layer")
    print("--------------------")
    print(f"Mode: {mode_str}")
    print(f"Cards generated: {len(final_cards)}")
    print(f"Model: {actual_model_used}")
    print(f"Task: {args.task}")
    print()

if __name__ == "__main__":
    main()
