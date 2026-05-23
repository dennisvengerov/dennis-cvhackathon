#!/usr/bin/env python3
"""
patch_agent.py

Patch Generation and Application Module for Context Compiler.
Produces proposed_patch.diff and patch_report.md, and applies patches safely.
"""

import os
import sys
import re
import json
import argparse
import shutil
import subprocess
from typing import List, Dict, Any, Tuple, Optional

from manifest_parser import ManifestParser
import llm_client

# Define the known deterministic fallback diff for the checkout request validation task
FALLBACK_DIFF = """diff --git a/app/api/checkout.py b/app/api/checkout.py
index 1234567..89abcde 100644
--- a/app/api/checkout.py
+++ b/app/api/checkout.py
@@ -7,4 +7,10 @@ def checkout_endpoint(request: CheckoutRequest) -> dict:
     \"\"\"Submit a checkout request, verify stock, assess fraud risk, and capture payment.\"\"\"
     log_info(f"Received checkout request for user {request.user_id}")
 
+    # Validate request
+    from app.utils.validation import validate_checkout_request
+    if not validate_checkout_request(request):
+        log_error(f"Request validation failed for user {request.user_id}")
+        return {"success": False, "error": "ValidationError", "details": "Invalid checkout request"}
+
     # 1. Verify stock for each item
diff --git a/tests/test_checkout.py b/tests/test_checkout.py
index abcdefg..hijklmn 100644
--- a/tests/test_checkout.py
+++ b/tests/test_checkout.py
@@ -23,3 +23,12 @@ def test_out_of_stock_checkout():
     response = checkout_endpoint(req)
     assert response["success"] is False
     assert response["error"] == "OutOfStock"
+
+def test_invalid_checkout_validation():
+    \"\"\"Test that an invalid checkout request fails validation.\"\"\"
+    req = CheckoutRequest(
+        user_id="",
+        items=[],
+        amount=0.0
+    )
+    response = checkout_endpoint(req)
+    assert response["success"] is False
+    assert response["error"] == "ValidationError"
"""

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Patch agent for generating and applying unified diffs."
    )
    parser.add_argument(
        "--repo",
        type=str,
        default="./demo_repo",
        help="Path to original source repository (default: ./demo_repo)"
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
        help="Path to semantic cards (default: semantic_cards.jsonl)"
    )
    parser.add_argument(
        "--task",
        type=str,
        default="Add request validation to the checkout endpoint before payment processing",
        help="The target task to generate a patch for"
    )
    parser.add_argument(
        "--out",
        type=str,
        default="proposed_patch.diff",
        help="Path to write the proposed unified diff (default: proposed_patch.diff)"
    )
    parser.add_argument(
        "--report-out",
        type=str,
        default="patch_report.md",
        help="Path to write the patch explanation report (default: patch_report.md)"
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Safely apply the generated patch to the repository"
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

def is_git_repo(path: str) -> bool:
    return os.path.exists(os.path.join(path, ".git"))

def is_git_clean(path: str) -> bool:
    if not is_git_repo(path):
        return False
    try:
        res = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=path,
            capture_output=True,
            text=True,
            check=True
        )
        return res.stdout.strip() == ""
    except Exception:
        return False

def git_restore_repo(path: str):
    if not is_git_repo(path):
        return
    try:
        subprocess.run(["git", "checkout", "."], cwd=path, capture_output=True)
        subprocess.run(["git", "clean", "-fd"], cwd=path, capture_output=True)
    except Exception as e:
        print(f"Warning: Failed to restore git repo: {e}", file=sys.stderr)

def find_file(repo_path: str, manifest_path: str) -> Optional[str]:
    """
    Attempts to locate a file within the repo_path.
    """
    if os.path.exists(manifest_path):
        return manifest_path
    joined = os.path.normpath(os.path.join(repo_path, manifest_path))
    if os.path.exists(joined):
        return joined
    parts = os.path.normpath(manifest_path).split(os.sep)
    repo_dir_name = os.path.basename(os.path.normpath(repo_path))
    if parts and (parts[0] == repo_dir_name or parts[0] == repo_path):
        joined_stripped = os.path.normpath(os.path.join(repo_path, *parts[1:]))
        if os.path.exists(joined_stripped):
            return joined_stripped
    return None

def apply_unified_diff_python(diff_text: str, repo_dir: str) -> bool:
    """
    Parses and safely applies a unified diff to the files in repo_dir using pure Python.
    Supports fuzzy context matching and reverse-order hunk application.
    """
    lines = diff_text.splitlines()
    files_to_patches: Dict[str, List[Tuple[int, int, List[str]]]] = {}
    current_file = None
    
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith('--- '):
            pass
        elif line.startswith('+++ '):
            path_part = line[4:].strip()
            # Clean possible tab markers or metadata
            if '\t' in path_part:
                path_part = path_part.split('\t')[0]
            # Remove a/ or b/ prefixes
            if path_part.startswith('a/') or path_part.startswith('b/'):
                path_part = path_part[2:]
            current_file = path_part
            if current_file not in files_to_patches:
                files_to_patches[current_file] = []
        elif line.startswith('@@') and current_file:
            match = re.match(r'@@ -(\d+),?(\d*) \+(\d+),?(\d*) @@', line)
            if match:
                old_start = int(match.group(1))
                old_len = int(match.group(2)) if match.group(2) else 1
                
                hunk_lines = []
                i += 1
                while i < len(lines):
                    if lines[i].startswith('--- ') or lines[i].startswith('@@') or lines[i].startswith('diff '):
                        i -= 1
                        break
                    hunk_lines.append(lines[i])
                    i += 1
                files_to_patches[current_file].append((old_start, old_len, hunk_lines))
        i += 1
        
    for f_rel_path, hunks in files_to_patches.items():
        f_abs_path = find_file(repo_dir, f_rel_path)
        if not f_abs_path or not os.path.exists(f_abs_path):
            print(f"Error: Target file for patch not found: {f_rel_path}", file=sys.stderr)
            return False
            
        with open(f_abs_path, 'r', encoding='utf-8') as f:
            file_lines = f.readlines()
            
        # Reverse-sort hunks so line shifting doesn't disrupt subsequent indices
        hunks.sort(key=lambda x: x[0], reverse=True)
        
        for old_start, old_len, hunk_lines in hunks:
            slice_start = old_start - 1
            slice_end = slice_start + old_len
            
            expected_old = []
            replacement_lines = []
            for h_line in hunk_lines:
                if h_line.startswith('-'):
                    expected_old.append(h_line[1:])
                elif h_line.startswith('+'):
                    replacement_lines.append(h_line[1:])
                elif h_line.startswith(' '):
                    expected_old.append(h_line[1:])
                    replacement_lines.append(h_line[1:])
                elif h_line == '':
                    expected_old.append('')
                    replacement_lines.append('')
                    
            # Check if lines match perfectly
            actual_old = file_lines[slice_start:slice_end]
            match_ok = True
            if len(actual_old) != len(expected_old):
                match_ok = False
            else:
                for a, e in zip(actual_old, expected_old):
                    if a.rstrip() != e.rstrip():
                        match_ok = False
                        break
                        
            if not match_ok:
                # Fuzzy context matching: Search the whole file for expected_old lines
                found_idx = -1
                for idx in range(len(file_lines) - len(expected_old) + 1):
                    sub_slice = file_lines[idx:idx+len(expected_old)]
                    sub_match = True
                    for a, e in zip(sub_slice, expected_old):
                        if a.rstrip() != e.rstrip():
                            sub_match = False
                            break
                    if sub_match:
                        found_idx = idx
                        break
                        
                if found_idx != -1:
                    slice_start = found_idx
                    slice_end = found_idx + len(expected_old)
                else:
                    print(f"Error: Hunk context mismatch in file {f_rel_path} around line {old_start}.", file=sys.stderr)
                    return False
                    
            # Inject replacements
            replacement_with_newlines = [l if l.endswith('\n') else l + '\n' for l in replacement_lines]
            file_lines[slice_start:slice_end] = replacement_with_newlines
            
        with open(f_abs_path, 'w', encoding='utf-8') as f:
            f.writelines(file_lines)
            
    return True

def extract_patch_from_response(response_text: str) -> Optional[str]:
    """
    Extracts the diff block from the LLM response text.
    """
    # Try markdown diff block
    match = re.search(r"```diff\s*(.*?)\s*```", response_text, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()
    # Try generic code block if diff wasn't explicit
    match = re.search(r"```\s*(.*?)\s*```", response_text, re.DOTALL)
    if match:
        content = match.group(1).strip()
        if "---" in content and "+++" in content:
            return content
    # Fallback to direct text if it contains diff patterns
    if "---" in response_text and "+++" in response_text:
        return response_text.strip()
    return None

def main():
    args = parse_args()
    
    # 1. Ensure selected_context.md is generated/exists
    context_path = "selected_context.md"
    if not os.path.exists(context_path):
        print(f"Notice: '{context_path}' not found. Generating now using source_loader.py...", file=sys.stderr)
        cmd = [
            sys.executable, "source_loader.py",
            "--repo", args.repo,
            "--manifest", args.manifest,
            "--debug-json", args.debug_json,
            "--out", context_path
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            print(f"Error generating context: {res.stderr}", file=sys.stderr)
            sys.exit(1)
            
    with open(context_path, "r", encoding="utf-8") as f:
        selected_context_content = f.read()
        
    # Determine LLM availability
    api_key_set = bool(os.environ.get("GEMINI_API_KEY"))
    use_llm = not args.no_llm and api_key_set
    
    mode_str = "Gemini" if use_llm else "deterministic fallback"
    
    patch_content = ""
    reasoning_report = ""
    
    if use_llm:
        print(f"Generating patch using Gemini ({args.model})...")
        prompt = f"""You are an advanced, reliable Software Engineering Agent.
Your job is to propose a safe, precise unified diff patch to implement the following requested task.

TASK:
"{args.task}"

Here is the extracted context from the codebase containing the exact source files and line ranges where changes are recommended:
{selected_context_content}

INSTRUCTIONS:
1. Provide a unified diff patch that applies clean modifications.
2. The path names in the diff should match the files relative to the repo directory, e.g., 'app/api/checkout.py'. Use 'a/app/api/checkout.py' and 'b/app/api/checkout.py' format.
3. Make sure to only output valid diff format. Put the diff inside a ```diff code block.
4. Also output a clean, detailed, separate description of which files are modified and why. Keep this description separate from the diff block.
"""
        response = llm_client.generate_content(prompt, model=args.model)
        if response:
            extracted_diff = extract_patch_from_response(response)
            if extracted_diff:
                patch_content = extracted_diff
                # Separate reasoning from the response
                reasoning_report = response.replace(f"```diff\n{extracted_diff}\n```", "").strip()
                reasoning_report = reasoning_report.replace(f"```diff{extracted_diff}```", "").strip()
            else:
                print("Warning: Gemini failed to output a valid diff block. Falling back to deterministic patch.", file=sys.stderr)
                use_llm = False
        else:
            print("Warning: Gemini call failed. Falling back to deterministic patch.", file=sys.stderr)
            use_llm = False
            
    if not use_llm:
        # Fallback to the standard deterministic diff
        print("Using deterministic fallback patch...")
        patch_content = FALLBACK_DIFF
        reasoning_report = f"""### Deterministic Patch Explanation

**Task**: "{args.task}"
**Reasoning**:
- Add `validate_checkout_request` from `app.utils.validation` inside `app/api/checkout.py` checkout endpoint.
- Returns a `ValidationError` (400 HTTP equivalent response) if validation fails.
- Validates that checkout is completely correct before conducting stock checks or fraud detection, preventing redundant state/Stripe checks.
- Adds an automated test case `test_invalid_checkout_validation` in `tests/test_checkout.py` to ensure the validation check executes and returns the correct payload, preventing regressions.
"""
        mode_str = "deterministic fallback"

    # Write the proposed diff patch
    with open(args.out, "w", encoding="utf-8") as out_p:
        out_p.write(patch_content)
        
    # Write the explanation/reasoning report
    report_content = f"""# Patch Agent Report ({mode_str.title()})

## Task Analysis
**Target Task**: {args.task}
**Mode**: {mode_str}

{reasoning_report}

## Target Files to Modify
- `app/api/checkout.py` (checkout_endpoint)
- `tests/test_checkout.py` (test_invalid_checkout_validation)

## Proposed Unified Diff
```diff
{patch_content}
```
"""
    with open(args.report_out, "w", encoding="utf-8") as out_r:
        out_r.write(report_content)
        
    # Print Hackathon log
    print("Patch Agent")
    print("-----------")
    print(f"Mode: {mode_str}")
    print(f"Proposed patch saved to: {args.out}")
    print(f"Patch report saved to: {args.report_out}")
    
    # 5. Safe Patch Application if requested
    patch_applied = False
    if args.apply:
        print("\nApplying patch safely...")
        
        # Determine the target files to backup
        files_to_backup = []
        # Simple extraction of paths from diff
        for line in patch_content.splitlines():
            if line.startswith("+++ "):
                p_path = line[4:].strip()
                if '\t' in p_path:
                    p_path = p_path.split('\t')[0]
                if p_path.startswith("a/") or p_path.startswith("b/"):
                    p_path = p_path[2:]
                f_abs = find_file(args.repo, p_path)
                if f_abs and os.path.exists(f_abs) and f_abs not in files_to_backup:
                    files_to_backup.append(f_abs)
                    
        # Backup files
        backups = {}
        for f in files_to_backup:
            bak_path = f + ".bak"
            try:
                shutil.copy2(f, bak_path)
                backups[f] = bak_path
            except Exception as e:
                print(f"Warning: Could not create backup for {f}: {e}", file=sys.stderr)
                
        # Apply patch
        success = apply_unified_diff_python(patch_content, args.repo)
        
        if success:
            print("Patch applied successfully via Python engine!")
            patch_applied = True
            # Clean up backups
            for f, bak in backups.items():
                try:
                    os.remove(bak)
                except Exception:
                    pass
        else:
            print("Python patch application failed. Attempting system patch command...", file=sys.stderr)
            # Fallback to system patch command
            # Try `patch -p1` inside repo
            try:
                # Write diff to a temp file inside repo
                temp_diff_path = os.path.join(args.repo, "temp_patch.diff")
                with open(temp_diff_path, "w", encoding="utf-8") as tmp:
                    tmp.write(patch_content)
                
                res = subprocess.run(
                    ["patch", "-p1", "-i", "temp_patch.diff"],
                    cwd=args.repo,
                    capture_output=True,
                    text=True
                )
                
                # Cleanup temp diff
                if os.path.exists(temp_diff_path):
                    os.remove(temp_diff_path)
                    
                if res.returncode == 0:
                    print("Patch applied successfully via system patch tool!")
                    patch_applied = True
                    # Clean up backups
                    for f, bak in backups.items():
                        try:
                            os.remove(bak)
                        except Exception:
                            pass
                else:
                    print(f"System patch failed: {res.stderr}", file=sys.stderr)
                    # Restore backups
                    print("Restoring original files from backup...")
                    for f, bak in backups.items():
                        try:
                            shutil.copy2(bak, f)
                            os.remove(bak)
                        except Exception as e:
                            print(f"Error restoring backup for {f}: {e}", file=sys.stderr)
            except Exception as ex:
                print(f"System patch command exception: {ex}", file=sys.stderr)
                # Restore backups
                print("Restoring original files from backup...")
                for f, bak in backups.items():
                    try:
                        shutil.copy2(bak, f)
                        os.remove(bak)
                    except Exception as e:
                        print(f"Error restoring backup for {f}: {e}", file=sys.stderr)
                        
        if not patch_applied:
            # Append failure status to report
            with open(args.report_out, "a", encoding="utf-8") as out_r:
                out_r.write("\n\n## Patch Application Status\n**Status**: FAILED\n*The patch application failed to apply cleanly to the codebase context. Backups have been restored.*")
            print("Error: Patch application was unsuccessful.", file=sys.stderr)
            sys.exit(1)
        else:
            # Append success status to report
            with open(args.report_out, "a", encoding="utf-8") as out_r:
                out_r.write("\n\n## Patch Application Status\n**Status**: SUCCESS\n*The patch has been cleanly applied to the codebase.*")
            print("Safe patch application completed successfully.")
            
    print()

if __name__ == "__main__":
    main()
