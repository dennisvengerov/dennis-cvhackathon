#!/usr/bin/env python3
"""
test_semantic_routing_smoke.py

Smoke test suite for the Semantic Router and Task Routing system.
Ensures that manifest parsing, semantic card generation, and task routing/planning works end-to-end deterministically.
"""

import os
import subprocess
import json
import sys

def test_semantic_routing_pipeline():
    print("Testing Semantic Routing Pipeline (Deterministic Fallback)...")
    
    # 1. Clean up old artifacts
    artifacts = [
        "codebase_manifest.txt",
        "codebase_manifest.debug.json",
        "semantic_cards.fallback.jsonl",
        "edit_plan.fallback.md",
        "edit_plan.fallback.json"
    ]
    for art in artifacts:
        if os.path.exists(art):
            os.remove(art)
            
    # 2. Regenerate manifest files
    print("  -> Regenerating manifest...")
    cmd_quant = [
        "python3", "quantizer.py",
        "--repo", "./demo_repo",
        "--out", "codebase_manifest.txt",
        "--target-ratio", "0.55",
        "--format", "both",
        "--debug-out", "codebase_manifest.debug.json"
    ]
    res_quant = subprocess.run(cmd_quant, capture_output=True, text=True)
    if res_quant.returncode != 0:
        print("FAIL (quantizer.py failed)")
        print(res_quant.stderr)
        sys.exit(1)
        
    assert os.path.exists("codebase_manifest.txt"), "codebase_manifest.txt not created"
    assert os.path.exists("codebase_manifest.debug.json"), "codebase_manifest.debug.json not created"
    
    # 3. Generate semantic cards fallback
    print("  -> Generating fallback semantic cards...")
    cmd_cards = [
        "python3", "semantic_cards.py",
        "--manifest", "codebase_manifest.txt",
        "--debug-json", "codebase_manifest.debug.json",
        "--out", "semantic_cards.fallback.jsonl",
        "--task", "Add request validation to the checkout endpoint before payment processing",
        "--max-nodes", "20",
        "--no-llm"
    ]
    res_cards = subprocess.run(cmd_cards, capture_output=True, text=True)
    if res_cards.returncode != 0:
        print("FAIL (semantic_cards.py failed)")
        print(res_cards.stderr)
        sys.exit(1)
        
    assert os.path.exists("semantic_cards.fallback.jsonl"), "semantic_cards.fallback.jsonl not created"
    
    # Validate semantic cards JSONL format
    with open("semantic_cards.fallback.jsonl", "r", encoding="utf-8") as f:
        cards_count = 0
        for line_num, line in enumerate(f, 1):
            line_strip = line.strip()
            if not line_strip:
                continue
            cards_count += 1
            try:
                data = json.loads(line_strip)
            except json.JSONDecodeError as e:
                print(f"FAIL (invalid JSON at line {line_num} in semantic_cards.fallback.jsonl: {e})")
                sys.exit(1)
            # Assert essential fields are present in cards
            required_card_keys = ["node_id", "file_alias", "qualified_name", "risk_level", "edit_relevance"]
            for key in required_card_keys:
                assert key in data, f"Missing key '{key}' in semantic card at line {line_num}"
                
    print(f"     [Pass] Generated and validated {cards_count} semantic cards.")

    # 4. Run Task Router (agent_harness.py)
    print("  -> Running task router...")
    cmd_router = [
        "python3", "agent_harness.py",
        "--manifest", "codebase_manifest.txt",
        "--semantic-cards", "semantic_cards.fallback.jsonl",
        "--task", "Add request validation to the checkout endpoint before payment processing",
        "--out", "edit_plan.fallback.md",
        "--json-out", "edit_plan.fallback.json",
        "--no-llm"
    ]
    res_router = subprocess.run(cmd_router, capture_output=True, text=True)
    if res_router.returncode != 0:
        print("FAIL (agent_harness.py failed)")
        print(res_router.stderr)
        sys.exit(1)
        
    assert os.path.exists("edit_plan.fallback.md"), "edit_plan.fallback.md not created"
    assert os.path.exists("edit_plan.fallback.json"), "edit_plan.fallback.json not created"
    
    # 5. Validate edit_plan.fallback.json
    with open("edit_plan.fallback.json", "r", encoding="utf-8") as f:
        routing_data = json.load(f)
        
    assert "task" in routing_data
    assert "mode" in routing_data
    assert "selected_files" in routing_data
    assert "selected_nodes" in routing_data
    assert "selected_edges" in routing_data
    assert "dependency_paths" in routing_data
    
    selected_files = routing_data["selected_files"]
    selected_nodes = routing_data["selected_nodes"]
    selected_edges = routing_data["selected_edges"]
    dependency_paths = routing_data["dependency_paths"]
    
    assert len(selected_files) > 0, "selected_files is empty"
    assert len(selected_nodes) > 0, "selected_nodes is empty"
    
    # Verify that we selected the checkout file/endpoint
    has_checkout = False
    for f in selected_files:
        if "checkout" in f["path"].lower():
            has_checkout = True
            
    for n in selected_nodes:
        if "checkout" in n["simple_name"].lower() or "checkout" in n["qualified_name"].lower():
            has_checkout = True
            
    assert has_checkout, "Failed to select checkout endpoint node/file"
    
    # Assertion: If the manifest contains validation/model/schema files and task contains those terms,
    # selected_files must include at least one validation/model/schema companion file.
    has_companion_file = False
    for f in selected_files:
        path_lower = f["path"].lower()
        if any(kw in path_lower for kw in ["validation", "validate", "schema", "model"]):
            has_companion_file = True
    assert has_companion_file, "selected_files did not include any validation/model/schema companion file"
    
    # Assertion: selected_edges relation must be one of:
    # call, method_call, class_ref, import, test_call, route, external_call, unknown
    allowed_relations = {
        "call", "method_call", "class_ref", "import", "test_call", "route", "external_call", "unknown"
    }
    for edge in selected_edges:
        relation = edge.get("relation")
        symbol = edge.get("symbol")
        assert relation in allowed_relations, f"Invalid edge relation '{relation}' in selected_edges"
        # relation should not equal symbol unless relation is unknown.
        if relation != "unknown":
            assert relation != symbol, f"Edge relation equals symbol for relation '{relation}'"
            
    # Verify selected_nodes contains at least one concrete function/class/method (which we did by avoiding '<module>')
    has_concrete = False
    for n in selected_nodes:
        if n["type"] in ["function", "method", "class"]:
            has_concrete = True
    assert has_concrete, "selected_nodes does not contain at least one concrete function/class/method"
    
    # Verify we didn't select '<module>' as the only node, or only node name
    for n in selected_nodes:
        assert n["simple_name"] != "<module>", "<module> node should not be in final selected nodes list"
        
    # Verify dependency paths does not contain any item that is exactly ["<module>"]
    for path in dependency_paths:
        assert path != ["<module>"], "Dependency paths should not contain only '<module>'"
        
    # Check that stdout doesn't mention only '<module>' as dependency path
    stdout = res_router.stdout
    assert "Selected dependency path:\n<module>" not in stdout, "Router output collapsed dependency path to <module>"
    
    print("     [Pass] Task routing outputs are structurally sound and target concrete subgraphs.")
    print("PASS")

if __name__ == "__main__":
    print("Running Prompt 2 Semantic Routing Smoke Tests...")
    test_semantic_routing_pipeline()
    print("All Semantic Routing tests PASSED successfully!")
