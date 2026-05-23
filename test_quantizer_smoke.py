#!/usr/bin/env python3
import os
import subprocess
import json
import sys

def test_quantizer_compact_format():
    print("Testing compact format...", end=" ")
    out_file = "codebase_manifest_smoke.txt"
    if os.path.exists(out_file):
        os.remove(out_file)
        
    cmd = [
        "python3", "quantizer.py",
        "--repo", "./demo_repo",
        "--out", out_file,
        "--target-ratio", "0.80",
        "--format", "compact"
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print("FAIL")
        print(result.stderr)
        sys.exit(1)
        
    if not os.path.exists(out_file):
        print("FAIL (Output file not created)")
        sys.exit(1)
    
    with open(out_file, "r") as f:
        content = f.read()
        
    if "# Context Compiler Manifest v3" not in content:
        print("FAIL (Header missing)")
        sys.exit(1)
    if "META repo=demo_repo" not in content:
        print("FAIL (META block missing)")
        sys.exit(1)
    if "FILES" not in content or "NODES" not in content or "EDGES" not in content or "NOTES" not in content:
        print("FAIL (Sections missing)")
        sys.exit(1)
    if "checkout_endpoint" not in content or "log_info" not in content:
        print("FAIL (Core functions missing)")
        sys.exit(1)
        
    os.remove(out_file)
    print("PASS")


def test_quantizer_json_format():
    print("Testing json format...", end=" ")
    out_file = "codebase_manifest_smoke.json"
    if os.path.exists(out_file):
        os.remove(out_file)
        
    cmd = [
        "python3", "quantizer.py",
        "--repo", "./demo_repo",
        "--out", out_file,
        "--target-ratio", "0.80",
        "--format", "json"
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print("FAIL")
        print(result.stderr)
        sys.exit(1)
        
    if not os.path.exists(out_file):
        print("FAIL (Output file not created)")
        sys.exit(1)
    
    try:
        with open(out_file, "r") as f:
            data = json.load(f)
    except Exception as e:
        print(f"FAIL (Invalid JSON: {e})")
        sys.exit(1)
        
    if "metadata" not in data or "nodes" not in data or "edges" not in data:
        print("FAIL (Missing root fields)")
        sys.exit(1)
        
    metadata = data["metadata"]
    if metadata.get("repo_path") != "demo_repo":
        print("FAIL (Incorrect repo path)")
        sys.exit(1)
        
    os.remove(out_file)
    print("PASS")


def test_quantizer_both_formats():
    print("Testing both formats...", end=" ")
    out_file = "codebase_manifest_smoke.txt"
    debug_out_file = "codebase_manifest_smoke.debug.json"
    if os.path.exists(out_file):
        os.remove(out_file)
    if os.path.exists(debug_out_file):
        os.remove(debug_out_file)
        
    cmd = [
        "python3", "quantizer.py",
        "--repo", "./demo_repo",
        "--out", out_file,
        "--target-ratio", "0.80",
        "--format", "both",
        "--debug-out", debug_out_file
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print("FAIL")
        print(result.stderr)
        sys.exit(1)
        
    if not os.path.exists(out_file) or not os.path.exists(debug_out_file):
        print("FAIL (Output files not created)")
        sys.exit(1)
        
    os.remove(out_file)
    os.remove(debug_out_file)
    print("PASS")


def test_manifest_usefulness_audit():
    print("Testing manifest usefulness audit...", end=" ")
    out_file = "codebase_manifest_audit.txt"
    if os.path.exists(out_file):
        os.remove(out_file)
        
    cmd = [
        "python3", "quantizer.py",
        "--repo", "./demo_repo",
        "--out", out_file,
        "--target-ratio", "0.25",
        "--format", "compact"
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print("FAIL (Execution failed)")
        print(result.stderr)
        sys.exit(1)
        
    if not os.path.exists(out_file):
        print("FAIL (Output file not created)")
        sys.exit(1)
        
    with open(out_file, "r") as f:
        lines = [line.strip() for line in f]
        
    # Check sections exist
    content_str = "\n".join(lines)
    if "# Context Compiler Manifest v3" not in content_str:
        print("FAIL (Manifest v3 header missing)")
        sys.exit(1)
        
    # Find META line
    meta_line = None
    for line in lines:
        if line.startswith("META "):
            meta_line = line
            break
    if not meta_line:
        print("FAIL (META line missing)")
        sys.exit(1)
        
    # Parse META fields
    meta_fields = {}
    for part in meta_line[5:].split():
        if "=" in part:
            k, v = part.split("=", 1)
            meta_fields[k] = v
            
    # Check META fields exist
    required_meta = [
        "repo", "original_tokens", "compressed_tokens", "ratio", "target",
        "files", "nodes", "debug_edges_total", "serialized_edges_total",
        "serialized_resolved_edges", "serialized_unresolved_edges",
        "body", "excerpt", "skel", "sig", "min", "status"
    ]
    for field in required_meta:
        if field not in meta_fields:
            print(f"FAIL (META missing field: {field})")
            sys.exit(1)
            
    # Count sections
    files_start = nodes_start = skels_start = edges_start = bodies_start = notes_start = -1
    for idx, line in enumerate(lines):
        if line == "FILES":
            files_start = idx
        elif line == "NODES":
            nodes_start = idx
        elif line == "SKELS":
            skels_start = idx
        elif line == "EDGES":
            edges_start = idx
        elif line == "BODIES":
            bodies_start = idx
        elif line == "NOTES":
            notes_start = idx
            
    if -1 in (files_start, nodes_start, skels_start, edges_start, bodies_start, notes_start):
        print("FAIL (Missing one or more sections)")
        sys.exit(1)
        
    # Count line items in each section
    files_list = []
    for idx in range(files_start + 1, nodes_start):
        line = lines[idx]
        if line and not line.isspace():
            files_list.append(line)
            
    nodes_list = []
    for idx in range(nodes_start + 1, skels_start):
        line = lines[idx]
        if line and not line.isspace():
            nodes_list.append(line)
            
    skels_list = []
    for idx in range(skels_start + 1, edges_start):
        line = lines[idx]
        if line and not line.isspace():
            skels_list.append(line)
            
    edges_list = []
    for idx in range(edges_start + 1, bodies_start):
        line = lines[idx]
        if line and not line.isspace():
            edges_list.append(line)
            
    # Check Route/API Node
    has_route_node = False
    for node in nodes_list:
        if "checkout_endpoint" in node or "register_user" in node or "list_products" in node or ("tags=" in node and ("route" in node or "endpoint" in node)):
            has_route_node = True
            break
    if not has_route_node:
        print("FAIL (No route/endpoint node found)")
        sys.exit(1)
        
    # Check at least one SKEL (target ratio is 0.25 >= 0.25)
    if len(skels_list) == 0:
        print("FAIL (No SKEL entries found at target-ratio 0.25)")
        sys.exit(1)
        
    # Check at least one EDGE
    if len(edges_list) == 0:
        print("FAIL (No EDGE entries found)")
        sys.exit(1)
        
    # Check metric contradictions
    meta_files = int(meta_fields["files"])
    meta_nodes = int(meta_fields["nodes"])
    meta_serialized_edges = int(meta_fields["serialized_edges_total"])
    meta_resolved = int(meta_fields["serialized_resolved_edges"])
    meta_unresolved = int(meta_fields["serialized_unresolved_edges"])
    meta_body = int(meta_fields["body"])
    meta_excerpt = int(meta_fields["excerpt"])
    meta_skel = int(meta_fields["skel"])
    meta_sig = int(meta_fields["sig"])
    meta_min = int(meta_fields["min"])
    
    # 1. Resolved + Unresolved = Serialized Edges Total
    if meta_resolved + meta_unresolved != meta_serialized_edges:
        print(f"FAIL (Metric contradiction: resolved({meta_resolved}) + unresolved({meta_unresolved}) != serialized_edges({meta_serialized_edges}))")
        sys.exit(1)
        
    # 2. Sum of modes matches nodes count
    modes_sum = meta_body + meta_excerpt + meta_skel + meta_sig + meta_min
    if modes_sum != meta_nodes:
        print(f"FAIL (Metric contradiction: body({meta_body}) + excerpt({meta_excerpt}) + skel({meta_skel}) + sig({meta_sig}) + min({meta_min}) != nodes({meta_nodes}))")
        sys.exit(1)
        
    # 3. Section counts match META declaration
    if len(files_list) != meta_files:
        print(f"FAIL (Metric contradiction: parsed files list length {len(files_list)} != META files {meta_files})")
        sys.exit(1)
    if len(nodes_list) != meta_nodes:
        print(f"FAIL (Metric contradiction: parsed nodes list length {len(nodes_list)} != META nodes {meta_nodes})")
        sys.exit(1)
    if len(edges_list) != meta_serialized_edges:
        print(f"FAIL (Metric contradiction: parsed edges list length {len(edges_list)} != META edges {meta_serialized_edges})")
        sys.exit(1)
        
    os.remove(out_file)
    print("PASS")


if __name__ == "__main__":
    print("Running Context Compiler Quantizer Smoke Tests...")
    test_quantizer_compact_format()
    test_quantizer_json_format()
    test_quantizer_both_formats()
    test_manifest_usefulness_audit()
    print("All smoke tests PASSED successfully!")
