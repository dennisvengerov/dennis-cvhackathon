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
        
    if "# Context Compiler Manifest v2" not in content:
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


if __name__ == "__main__":
    print("Running Context Compiler Quantizer Smoke Tests...")
    test_quantizer_compact_format()
    test_quantizer_json_format()
    test_quantizer_both_formats()
    print("All smoke tests PASSED successfully!")
