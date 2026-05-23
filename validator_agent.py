#!/usr/bin/env python3
"""
validator_agent.py

Validation and repair agent for Context Compiler.
Runs tests/syntax checks, captures logs, and performs single-attempt repair with Gemini.
"""

import os
import sys
import argparse
import subprocess
import shutil
import re
from typing import Tuple, List, Dict, Any, Optional

import llm_client

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validator agent to execute tests and handle automated repairs."
    )
    parser.add_argument(
        "--repo",
        type=str,
        default="./demo_repo",
        help="Path to original source repository (default: ./demo_repo)"
    )
    parser.add_argument(
        "--test-command",
        type=str,
        default="pytest -q",
        help="Command to run tests (default: pytest -q)"
    )
    parser.add_argument(
        "--patch-report",
        type=str,
        default="patch_report.md",
        help="Path to the patch agent's report (default: patch_report.md)"
    )
    parser.add_argument(
        "--out",
        type=str,
        default="validation_report.md",
        help="Path to write the validation report markdown (default: validation_report.md)"
    )
    parser.add_argument(
        "--max-repair-attempts",
        type=int,
        default=1,
        help="Maximum automated repair attempts if tests fail (default: 1)"
    )
    parser.add_argument(
        "--model",
        type=str,
        default="gemini-2.5-flash",
        help="Gemini model to use for repairs (default: gemini-2.5-flash)"
    )
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="Force deterministic fallback mode without LLM repair"
    )
    return parser.parse_args()

def run_syntax_checks(repo_path: str) -> Tuple[bool, str]:
    """
    Runs compileall as a fallback syntax check if no tests are found.
    """
    print("Running compilation/syntax check on repository...")
    cmd = [sys.executable, "-m", "compileall", repo_path]
    res = subprocess.run(cmd, capture_output=True, text=True)
    success = (res.returncode == 1 or res.returncode == 0) # compileall returns 0 if all ok, or 1 if syntax errors
    # Actually compileall returns 1 if there's a compilation error, so success is returncode == 0
    success = (res.returncode == 0)
    output = f"Command: {' '.join(cmd)}\nExit Code: {res.returncode}\n\nSTDOUT:\n{res.stdout}\n\nSTDERR:\n{res.stderr}"
    return success, output

def run_custom_tests_fallback(repo_path: str) -> Tuple[bool, str]:
    """
    Pure Python lightweight test runner to run tests in tests/ test_*.py.
    Provides a seamless zero-dependency fallback.
    """
    import importlib.util
    import glob
    
    abs_repo = os.path.abspath(repo_path)
    if abs_repo not in sys.path:
        sys.path.insert(0, abs_repo)
        
    test_files = glob.glob(os.path.join(repo_path, "tests", "test_*.py"))
    if not test_files:
        test_files = glob.glob(os.path.join(repo_path, "**/test_*.py"), recursive=True)
        
    if not test_files:
        return False, "No test files discovered for fallback execution."
        
    passed = 0
    failed = 0
    logs = []
    
    logs.append(f"Discovered test files: {[os.path.basename(f) for f in test_files]}")
    
    for f_path in test_files:
        module_name = os.path.basename(f_path).replace(".py", "")
        spec = importlib.util.spec_from_file_location(module_name, f_path)
        if not spec or not spec.loader:
            continue
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except Exception as e:
            logs.append(f"CRITICAL: Failed to load test module {module_name} ({f_path}): {e}")
            failed += 1
            continue
            
        test_funcs = [
            getattr(module, attr) for attr in dir(module)
            if attr.startswith("test_") and callable(getattr(module, attr))
        ]
        
        for func in test_funcs:
            func_name = func.__name__
            logs.append(f"Running: {module_name}.{func_name}...")
            try:
                func()
                logs.append(f"  [PASS] {module_name}.{func_name}")
                passed += 1
            except AssertionError as ae:
                logs.append(f"  [FAIL] {module_name}.{func_name} - AssertionError")
                import traceback
                logs.append(traceback.format_exc())
                failed += 1
            except Exception as e:
                logs.append(f"  [FAIL] {module_name}.{func_name} - Exception: {e}")
                import traceback
                logs.append(traceback.format_exc())
                failed += 1
                
    summary = f"\nTest Suite Summary: {passed} passed, {failed} failed\n"
    full_output = "\n".join(logs) + summary
    return (failed == 0), full_output

def execute_tests(repo_path: str, test_command: str) -> Tuple[bool, str]:
    """
    Executes the specified test command. If pytest is missing, falls back to the custom runner.
    """
    # First, let's see if tests folder exists. If not, fallback to syntax check.
    test_dir = os.path.join(repo_path, "tests")
    if not os.path.exists(test_dir):
        # Scan if there's any test_*.py file anywhere
        import glob
        matches = glob.glob(os.path.join(repo_path, "**/test_*.py"), recursive=True)
        if not matches:
            print("No tests found. Falling back to syntax check...")
            return run_syntax_checks(repo_path)
            
    # Try running the command
    print(f"Executing test command: '{test_command}' in repo '{repo_path}'...")
    try:
        # Run with PYTHONPATH set to repo path
        env = os.environ.copy()
        env["PYTHONPATH"] = os.path.abspath(repo_path) + os.pathsep + env.get("PYTHONPATH", "")
        
        # We split the command to run it as list, or shell=True if it has space/args
        res = subprocess.run(
            test_command,
            cwd=repo_path,
            shell=True,
            capture_output=True,
            text=True,
            env=env
        )
        
        # Check if pytest is missing or couldn't run
        output = f"STDOUT:\n{res.stdout}\n\nSTDERR:\n{res.stderr}"
        
        # Handle "command not found" or "No module named pytest"
        if "No module named pytest" in res.stderr or "command not found" in res.stderr or res.returncode == 127:
            print("Warning: pytest execution failed (missing package/executable). Falling back to pure Python test runner...", file=sys.stderr)
            return run_custom_tests_fallback(repo_path)
            
        success = (res.returncode == 0)
        return success, f"Command: {test_command}\nExit Code: {res.returncode}\n\n{output}"
        
    except Exception as e:
        print(f"Warning: Command execution failed with exception: {e}. Falling back to pure Python test runner...", file=sys.stderr)
        return run_custom_tests_fallback(repo_path)

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

def apply_repaired_patch_python(diff_text: str, repo_dir: str) -> bool:
    """
    Applies unified diff patch safely inside validator (similar to patch_agent.py).
    """
    from patch_agent import apply_unified_diff_python
    return apply_unified_diff_python(diff_text, repo_dir)

def attempt_repair(
    repo_path: str,
    test_log: str,
    patch_report_content: str,
    model: str
) -> Tuple[bool, str, str]:
    """
    Asks Gemini for a repair patch to resolve the failing test output.
    Returns (success, repair_diff, repair_explanation).
    """
    print(f"Requesting automated repair from Gemini ({model})...")
    
    prompt = f"""You are a senior Software Engineering Agent.
A previously applied code patch has failed the test suite. Your goal is to analyze the test failure and output a CORRECT, REPAIRED unified diff patch that fixes the failure completely.

Below is the previously applied patch report and context:
{patch_report_content}

Below is the test execution output showing the failure details:
{test_log}

INSTRUCTIONS:
1. Propose a corrected unified diff patch. Make sure it uses relative file paths like 'a/app/api/checkout.py' and 'b/app/api/checkout.py'.
2. Return the corrected diff inside a ```diff code block.
3. Keep your changes minimal and target only the bugs/syntax errors shown in the test log.
4. Provide a 1-2 sentence explanation of the error and how you fixed it.
"""
    response = llm_client.generate_content(prompt, model=model)
    if not response:
        return False, "", "Gemini API call failed during repair."
        
    # Extract the diff
    match = re.search(r"```diff\s*(.*?)\s*```", response, re.DOTALL | re.IGNORECASE)
    repair_diff = ""
    if match:
        repair_diff = match.group(1).strip()
    else:
        # Try generic code block
        match = re.search(r"```\s*(.*?)\s*```", response, re.DOTALL)
        if match:
            content = match.group(1).strip()
            if "---" in content and "+++" in content:
                repair_diff = content
                
    if not repair_diff:
        return False, "", "Could not extract a valid repaired unified diff from Gemini's response."
        
    explanation = response.replace(f"```diff\n{repair_diff}\n```", "").strip()
    explanation = explanation.replace(f"```diff{repair_diff}```", "").strip()
    
    return True, repair_diff, explanation

def main():
    args = parse_args()
    
    # 1. Load the patch report if it exists
    patch_report_content = ""
    if os.path.exists(args.patch_report):
        with open(args.patch_report, "r", encoding="utf-8") as rf:
            patch_report_content = rf.read()
            
    # 2. Run the tests
    success, test_log = execute_tests(args.repo, args.test_command)
    
    repair_history = []
    
    # Check if we need repair
    api_key_set = bool(os.environ.get("GEMINI_API_KEY"))
    can_repair = not success and not args.no_llm and api_key_set and args.max_repair_attempts > 0
    
    if not success:
        print("\nTest execution FAILED!")
        if can_repair:
            print("Initiating automated repair sequence...")
            attempt = 1
            while attempt <= args.max_repair_attempts and not success:
                print(f"\n--- Repair Attempt {attempt}/{args.max_repair_attempts} ---")
                
                # Ask Gemini for a fix
                repair_ok, repair_diff, repair_explain = attempt_repair(
                    args.repo, test_log, patch_report_content, args.model
                )
                
                if not repair_ok:
                    print(f"Repair request failed: {repair_explain}")
                    repair_history.append({
                        "attempt": attempt,
                        "success": False,
                        "error": repair_explain
                    })
                    break
                    
                # Back up before applying repair
                print("Backing up files before applying repair...")
                files_to_backup = []
                for line in repair_diff.splitlines():
                    if line.startswith("+++ "):
                        p_path = line[4:].strip()
                        if '\t' in p_path:
                            p_path = p_path.split('\t')[0]
                        if p_path.startswith("a/") or p_path.startswith("b/"):
                            p_path = p_path[2:]
                        f_abs = find_file(args.repo, p_path)
                        if f_abs and os.path.exists(f_abs) and f_abs not in files_to_backup:
                            files_to_backup.append(f_abs)
                            
                backups = {}
                for f in files_to_backup:
                    bak_path = f + ".bak"
                    try:
                        shutil.copy2(f, bak_path)
                        backups[f] = bak_path
                    except Exception as e:
                        print(f"Warning: Backup failed for {f}: {e}")
                        
                # Apply repair patch
                apply_ok = apply_repaired_patch_python(repair_diff, args.repo)
                
                if apply_ok:
                    print("Repair patch applied. Re-running tests...")
                    success, repair_test_log = execute_tests(args.repo, args.test_command)
                    
                    if success:
                        print("Repair succeeded! All tests are now PASSING.")
                        test_log = repair_test_log
                        # Delete backups
                        for f, bak in backups.items():
                            try:
                                os.remove(bak)
                            except Exception:
                                pass
                    else:
                        print("Repair patch applied but tests still failed.")
                        # Restore backups to previous state
                        print("Restoring files to previous state...")
                        for f, bak in backups.items():
                            try:
                                shutil.copy2(bak, f)
                                os.remove(bak)
                            except Exception:
                                pass
                else:
                    print("Repair patch failed to apply cleanly.")
                    # Restore backups
                    print("Restoring backups...")
                    for f, bak in backups.items():
                        try:
                            shutil.copy2(bak, f)
                            os.remove(bak)
                        except Exception:
                            pass
                    repair_test_log = "Repair patch application failed."
                    
                repair_history.append({
                    "attempt": attempt,
                    "applied": apply_ok,
                    "success": success,
                    "diff": repair_diff,
                    "explanation": repair_explain,
                    "log": repair_test_log
                })
                attempt += 1
        else:
            if not api_key_set and not args.no_llm:
                print("Notice: Automated repair skipped because GEMINI_API_KEY is not configured.", file=sys.stderr)
    else:
        print("\nAll tests PASSED successfully!")
        
    # 3. Write validation report markdown
    status_str = "PASS" if success else "FAIL"
    
    repair_section = ""
    if repair_history:
        repair_section = "## Repair History\n"
        for h in repair_history:
            repair_section += f"""### Attempt {h['attempt']}
- **Patch Applied**: {'Yes' if h.get('applied', False) else 'No'}
- **Validation Status**: {'PASS' if h.get('success', False) else 'FAIL'}
- **Explanation**: {h.get('explanation', h.get('error', ''))}

#### Repaired Unified Diff:
```diff
{h.get('diff', '')}
```

#### Subsequent Test Execution Output:
```text
{h.get('log', '')}
```
---
"""
            
    report_content = f"""# Validator Agent Report

## Summary
- **Test Command**: `{args.test_command}`
- **Overall Status**: **{status_str}**

## Test Execution Log
```text
{test_log}
```

{repair_section}
"""
    with open(args.out, "w", encoding="utf-8") as f_out:
        f_out.write(report_content)
        
    # Print Hackathon log
    print("Validator Agent")
    print("---------------")
    print(f"Overall Status: {status_str}")
    print(f"Validation report saved to: {args.out}")
    print()
    
    if not success:
        sys.exit(1)

if __name__ == "__main__":
    main()
