#!/usr/bin/env python3
"""
demo_pipeline.py

One-command local demo runner for Context Compiler.
Chains:
1. quantizer.py
2. semantic_cards.py
3. agent_harness.py
4. source_loader.py
5. patch_agent.py
6. (Optional) safe patch application
7. validator_agent.py (runs test suite or compileall)
"""

import os
import sys
import json
import argparse
import shutil
import subprocess
from typing import List, Dict, Tuple, Optional

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="End-to-end pipeline runner for Context Compiler."
    )
    parser.add_argument(
        "--repo",
        type=str,
        default="./demo_repo",
        help="Path to the repository to compile/patch (default: ./demo_repo)"
    )
    parser.add_argument(
        "--task",
        type=str,
        default="Add request validation to the checkout endpoint before payment processing",
        help="The target task for the pipeline (default: checkout request validation)"
    )
    parser.add_argument(
        "--target-ratio",
        type=float,
        default=0.15,
        help="Target compression ratio for quantizer (default: 0.15)"
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply the patch permanently. Default is dry-run with temporary validation."
    )
    parser.add_argument(
        "--test-command",
        type=str,
        default="pytest -q",
        help="Command to run tests (default: pytest -q)"
    )
    parser.add_argument(
        "--model",
        type=str,
        default="gemini-2.5-flash",
        help="Gemini model to use if API key is set (default: gemini-2.5-flash)"
    )
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="Force deterministic fallback mode without LLM"
    )
    return parser.parse_args()

def run_command(cmd: List[str], description: str) -> int:
    print(f"\n==========================================")
    print(f"Running Step: {description}")
    print(f"Command: {' '.join(cmd)}")
    print(f"==========================================")
    res = subprocess.run(cmd)
    if res.returncode != 0:
        print(f"Warning: {description} completed with non-zero exit code {res.returncode}.", file=sys.stderr)
    return res.returncode

def get_modified_files_from_diff(diff_path: str) -> List[str]:
    """
    Parses a diff file and returns relative paths of modified files.
    """
    modified_files = []
    if not os.path.exists(diff_path):
        return []
    with open(diff_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.startswith("+++ "):
                path_part = line[4:].strip()
                if '\t' in path_part:
                    path_part = path_part.split('\t')[0]
                if path_part.startswith("a/") or path_part.startswith("b/"):
                    path_part = path_part[2:]
                if path_part and path_part not in modified_files:
                    modified_files.append(path_part)
    return modified_files

def main():
    args = parse_args()
    
    # Files
    manifest_txt = "codebase_manifest.txt"
    manifest_debug = "codebase_manifest.debug.json"
    semantic_cards = "semantic_cards.jsonl"
    edit_plan_md = "edit_plan.md"
    edit_plan_json = "edit_plan.json"
    selected_context = "selected_context.md"
    proposed_patch = "proposed_patch.diff"
    patch_report = "patch_report.md"
    validation_report = "validation_report.md"
    
    # 1. Quantizer
    quantizer_cmd = [
        sys.executable, "quantizer.py",
        "--repo", args.repo,
        "--target-ratio", str(args.target_ratio),
        "--out", manifest_txt,
        "--debug-out", manifest_debug,
        "--format", "both"
    ]
    run_command(quantizer_cmd, "Codebase Quantization")
    
    # 2. Semantic Cards
    cards_cmd = [
        sys.executable, "semantic_cards.py",
        "--manifest", manifest_txt,
        "--debug-json", manifest_debug,
        "--task", args.task,
        "--out", semantic_cards,
        "--model", args.model
    ]
    if args.no_llm:
        cards_cmd.append("--no-llm")
    run_command(cards_cmd, "Semantic Cards Enrichment")
    
    # 3. Agent Harness (Edit Planner)
    harness_cmd = [
        sys.executable, "agent_harness.py",
        "--manifest", manifest_txt,
        "--debug-json", manifest_debug,
        "--semantic-cards", semantic_cards,
        "--task", args.task,
        "--out", edit_plan_md,
        "--json-out", edit_plan_json,
        "--model", args.model
    ]
    if args.no_llm:
        harness_cmd.append("--no-llm")
    run_command(harness_cmd, "Agent Harness Edit Planning")
    
    # 4. Source Loader
    loader_cmd = [
        sys.executable, "source_loader.py",
        "--repo", args.repo,
        "--manifest", manifest_txt,
        "--debug-json", manifest_debug,
        "--selected", edit_plan_json,
        "--out", selected_context
    ]
    run_command(loader_cmd, "Source Loader Context Extraction")
    
    # 5. Patch Agent (Generation only)
    patch_cmd = [
        sys.executable, "patch_agent.py",
        "--repo", args.repo,
        "--manifest", manifest_txt,
        "--debug-json", manifest_debug,
        "--semantic-cards", semantic_cards,
        "--task", args.task,
        "--out", proposed_patch,
        "--report-out", patch_report,
        "--model", args.model
    ]
    if args.no_llm:
        patch_cmd.append("--no-llm")
    run_command(patch_cmd, "Patch Generation")
    
    # Handle Application & Validation
    patch_applied = "no"
    validation_status = "not run"
    
    # Find files to modify
    files_to_modify = get_modified_files_from_diff(proposed_patch)
    
    # Safe pipeline backup
    backups = {}
    for f_rel in files_to_modify:
        f_abs = os.path.join(args.repo, f_rel)
        if os.path.exists(f_abs):
            bak = f_abs + ".pipeline_bak"
            try:
                shutil.copy2(f_abs, bak)
                backups[f_abs] = bak
            except Exception as e:
                print(f"Warning: Could not create backup for {f_rel}: {e}", file=sys.stderr)
                
    try:
        # Determine whether to apply (permanently or temporarily)
        if args.apply:
            # Apply permanently
            print("\nApplying patch permanently...")
            apply_cmd = patch_cmd + ["--apply"]
            ret = run_command(apply_cmd, "Safe Patch Application (Permanent)")
            if ret == 0:
                patch_applied = "yes"
            else:
                patch_applied = "failed"
                
            # Run validator
            val_cmd = [
                sys.executable, "validator_agent.py",
                "--repo", args.repo,
                "--test-command", args.test_command,
                "--patch-report", patch_report,
                "--out", validation_report,
                "--model", args.model
            ]
            if args.no_llm:
                val_cmd.append("--no-llm")
                
            ret_val = run_command(val_cmd, "Validator Agent (Permanent)")
            validation_status = "pass" if ret_val == 0 else "fail"
            
            # Clean up temporary pipeline backups since we applied permanently
            for bak in backups.values():
                if os.path.exists(bak):
                    os.remove(bak)
        else:
            # Dry-run with temporary validation
            print("\nPerforming dry-run validation (temporary patch apply & restore)...")
            apply_cmd = patch_cmd + ["--apply"]
            ret = run_command(apply_cmd, "Safe Patch Application (Temporary)")
            
            if ret == 0:
                patch_applied = "yes (dry-run, reverted)"
                # Run validator
                val_cmd = [
                    sys.executable, "validator_agent.py",
                    "--repo", args.repo,
                    "--test-command", args.test_command,
                    "--patch-report", patch_report,
                    "--out", validation_report,
                    "--model", args.model
                ]
                if args.no_llm:
                    val_cmd.append("--no-llm")
                    
                ret_val = run_command(val_cmd, "Validator Agent (Dry-Run)")
                validation_status = "pass" if ret_val == 0 else "fail"
            else:
                patch_applied = "no (failed to apply)"
                validation_status = "not run"
                
            # Restore files from pipeline backups to leave repo unmodified
            print("\nRestoring repository to unpatched state...")
            for f_abs, bak in backups.items():
                if os.path.exists(bak):
                    shutil.copy2(bak, f_abs)
                    os.remove(bak)
            print("Repository clean and restored successfully.")
            
    except Exception as ex:
        print(f"Error in application/validation loop: {ex}", file=sys.stderr)
        # Safe restore fallback
        print("Ensuring repository is restored...")
        for f_abs, bak in backups.items():
            if os.path.exists(bak):
                shutil.copy2(bak, f_abs)
                os.remove(bak)
                
    # Parse Manifest Details
    raw_tokens = "N/A"
    compact_tokens = "N/A"
    comp_ratio = "N/A"
    if os.path.exists(manifest_debug):
        try:
            with open(manifest_debug, "r") as f:
                md_json = json.load(f)
                meta = md_json.get("metadata", {})
                raw_tokens = meta.get("original_tokens", "N/A")
                compact_tokens = meta.get("compressed_tokens", "N/A")
                comp_ratio = meta.get("compression_ratio", "N/A")
                if isinstance(comp_ratio, float):
                    comp_ratio = f"{comp_ratio:.2%}"
        except Exception:
            pass
            
    # Parse Card Count
    card_count = 0
    if os.path.exists(semantic_cards):
        try:
            with open(semantic_cards, "r") as f:
                card_count = sum(1 for line in f if line.strip())
        except Exception:
            pass
            
    # Parse Selected Files
    sel_files_str = "[]"
    if os.path.exists(edit_plan_json):
        try:
            with open(edit_plan_json, "r") as f:
                ep_json = json.load(f)
                paths = [sf.get("path") for sf in ep_json.get("selected_files", [])]
                sel_files_str = ", ".join(paths) if paths else "[]"
        except Exception:
            pass
            
    # Output the required demo report!
    print("\n==================================================")
    print("Context Compiler End-to-End Demo")
    print("--------------------------------")
    print(f"Raw repo tokens: {raw_tokens}")
    print(f"Compact manifest tokens: {compact_tokens}")
    print(f"Compression ratio: {comp_ratio}")
    print(f"Semantic cards: {card_count}")
    print(f"Selected files: {sel_files_str}")
    print(f"Patch generated: {'yes' if os.path.exists(proposed_patch) else 'no'}")
    print(f"Patch applied: {patch_applied}")
    print(f"Validation: {validation_status}")
    print("Artifacts:")
    print(f"- {manifest_txt}")
    print(f"- {manifest_debug}")
    print(f"- {semantic_cards}")
    print(f"- {edit_plan_md}")
    print(f"- {selected_context}")
    print(f"- {proposed_patch}")
    print(f"- {patch_report}")
    print(f"- {validation_report}")
    print("==================================================")

if __name__ == "__main__":
    main()
