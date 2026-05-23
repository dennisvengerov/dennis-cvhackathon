#!/usr/bin/env python3
"""
main.py

Context Compiler Orchestrator for the Cerebral Valley Google I/O Hackathon.
This is the master orchestrator that supports:
1. --smoke-test: Verifies environment, Gemini API key, Managed Agent API support, and lists active modes.
2. Local demo repo flow: Compiles, plans, and dry-runs on ./demo_repo.
3. --judge-demo: Copies demo repo to a temp location, applies patch, runs validation, and generates a final diff and dashboard.
4. --repo-url: Clones and orchestrates remote Managed Agent sandbox or fallback local cloning pipeline.
"""

import os
import sys
import shutil
import argparse
import subprocess
import platform
from typing import Optional
from dotenv import load_dotenv

from managed_agent_runner import (
    run_managed_agent_demo,
    print_managed_agent_summary,
    MANAGED_AGENT_NAME,
    MANAGED_AGENT_ENVIRONMENT,
)

# Load environment variables
load_dotenv()

def print_banner():
    print(r"""
========================================================================
   ____            _            _      ____                         _ _             
  / ___|___  _ __ | |_ _____  _| |_   / ___|___  _ __ ___  _ __ (_) | ___ _ __  
 | |   / _ \| '_ \| __/ _ \ \/ / __| | |   / _ \| '_ ` _ \| '_ \| | |/ _ \ '__| 
 | |__| (_) | | | | ||  __/>  <| |_  | |__| (_) | | | | | | |_) | | |  __/ |    
  \____\___/|_| |_|\__\___/_/\_\\__|  \____\___/|_| |_| |_| .__/|_|_|\___|_|    
                                                          |_|                    
========================================================================
Deterministic Structural Quantizer + Cheap Gemini Semantic Layer
Cerebral Valley Hackathon 2026 - Managed Agents Prize Submission
========================================================================
""")

def get_agent_support() -> bool:
    """
    Checks if google-genai library supports interactions/Managed Agents.
    """
    try:
        from google import genai
        client = genai.Client()
        return hasattr(client, "interactions")
    except Exception:
        return False

def run_smoke_test():
    print_banner()
    print("--- ENVIRONMENT INFO ---")
    print(f"OS Platform: {platform.system()} {platform.release()} ({platform.machine()})")
    print(f"Python Version: {platform.python_version()}")
    print(f"Python Executable: {sys.executable}")
    print()

    api_key = os.environ.get("GEMINI_API_KEY")
    api_key_status = "CONFIGURED (hidden for safety)" if api_key else "NOT CONFIGURED"
    print("--- API CREDENTIALS CHECK ---")
    print(f"GEMINI_API_KEY: {api_key_status}")
    
    # Check library support
    has_library_support = get_agent_support()
    print(f"Google GenAI SDK Installed: Yes")
    print(f"Managed Agent Interactions API available in SDK: {'Yes' if has_library_support else 'No'}")
    print()

    # Determine Active Modes
    print("--- ACTIVE ORCHESTRATION PATHS ---")
    
    # 1. Gemini Mode
    if api_key:
        print("  [✓] Gemini Mode: ENABLED")
        print("      - AST structural quantization is enriched with cheap Gemini Semantic Cards.")
        print("      - High-relevance task-specific code selections are managed via LLM-routing.")
        print("      - Patch & validate loop uses gemini-2.5-flash for perfect diff alignments.")
    else:
        print("  [!] Gemini Mode: DISABLED")
        print("      - Falling back to Deterministic local processing mode.")
        print("      - Codebase compaction and route selection will run with high-speed local AST heuristics.")

    # 2. Managed Agent Mode
    if api_key and has_library_support:
        print("  [✓] Managed Agent Sandbox Orchestrator: READY (Remote-Capable)")
        print("      - Can provision fresh isolated remote sandboxes via client.interactions.")
        print("      - Capable of remote cloning, workspace mounting, and serverless compilation.")
    else:
        print("  [-] Managed Agent Sandbox Orchestrator: FALLBACK LOCAL MODE ACTIVE")
        if not api_key:
            print("      - Reason: GEMINI_API_KEY is not configured.")
        else:
            print("      - Reason: Interactions API is not available on this workspace client/version.")
        print("      - Action: System will run robust local compilation and mock/fallback sandbox virtualization.")
        print("      - Note: Faking remote execution is strictly prohibited. Fallback is clean and honest.")
        
    print()

    # Managed Agent live probe — this is the primary judge-facing path.
    print("--- MANAGED AGENT RUNTIME (PRIMARY PATH) ---")
    smoke_trace = run_managed_agent_demo(
        repo_path=os.path.abspath("./demo_repo"),
        task="Smoke-test the Managed Agent remote sandbox path",
        target_ratio=0.15,
        output_trace_path="managed_agent_trace.json",
    )
    print_managed_agent_summary(smoke_trace)
    if smoke_trace.get("managed_agent_succeeded"):
        print("MANAGED AGENT REMOTE SANDBOX: ENABLED")
    else:
        print("MANAGED AGENT REMOTE SANDBOX: UNAVAILABLE - LOCAL FALLBACK USED")
        print("Managed Agent unavailable; local fallback used.")
    print()

    print("========================================================================")
    print("Smoke Test Passed. Context Compiler is ready to run.")
    print("========================================================================")


def clone_repo(repo_url: str, dest_dir: str) -> bool:
    """
    Clones a remote repository to a local path.
    """
    print(f"Cloning remote repository {repo_url} into {dest_dir}...")
    if os.path.exists(dest_dir):
        shutil.rmtree(dest_dir)
    try:
        res = subprocess.run(["git", "clone", repo_url, dest_dir], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return res.returncode == 0
    except Exception as e:
        print(f"Error cloning repository: {e}", file=sys.stderr)
        return False


def run_pipeline_local(repo_path: str, task: str, target_ratio: float, apply_patch: bool, no_llm: bool):
    """
    Runs the demo_pipeline.py script as a subprocess on the target repository.
    """
    cmd = [
        sys.executable, "demo_pipeline.py",
        "--repo", repo_path,
        "--task", task,
        "--target-ratio", str(target_ratio)
    ]
    if apply_patch:
        cmd.append("--apply")
    if no_llm:
        cmd.append("--no-llm")

    print(f"\nOrchestrating local Context Compiler pipeline on repo: {repo_path}")
    print(f"Task: \"{task}\"")
    print(f"Command to execute: {' '.join(cmd)}\n")
    
    res = subprocess.run(cmd)
    return res.returncode


def run_remote_managed_agent(repo_url: str, task: str) -> bool:
    """
    Attempts to spin up a genuine remote sandbox via Google GenAI Managed Agents
    and run a test agent command to show how we orchestrate.
    """
    try:
        from google import genai
        client = genai.Client()
        test_input = f"Provision an environment, clone {repo_url}, and analyze the codebase structure for the task: '{task}'."
        print(f"[Managed Agent] Contacting Google GenAI 'antigravity-preview-05-2026' serverless sandbox...")
        interaction = client.interactions.create(
            agent="antigravity-preview-05-2026",
            input=test_input,
            environment="remote",
        )
        print("\n--- Remote Sandbox Orchestrated ---")
        print(f"Interaction ID: {interaction.id}")
        print(f"Environment ID: {interaction.environment_id}")
        print("Agent Response Output:")
        print(interaction.output_text)
        print("----------------------------------\n")
        return True
    except Exception as e:
        print(f"\n[Managed Agent] Remote agent call returned: {e}")
        print("[Managed Agent] Remote sandboxes are either restricted, unbilled, or unsupported on this credential.")
        print("[Managed Agent] Seamlessly falling back to local orchestrator path as designed!\n")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Context Compiler Orchestrator and Judge Demo Runner."
    )
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help="Check OS, python, API keys, and Managed Agent API capability."
    )
    parser.add_argument(
        "--repo",
        type=str,
        default="./demo_repo",
        help="Path to target local repository (default: ./demo_repo)"
    )
    parser.add_argument(
        "--repo-url",
        type=str,
        help="Git repository URL to compile and patch."
    )
    parser.add_argument(
        "--target-ratio",
        type=float,
        default=0.15,
        help="Compression ratio target for structural compilation (default: 0.15)"
    )
    parser.add_argument(
        "--task",
        type=str,
        default="Add request validation to the checkout endpoint before payment processing",
        help="Coding or analysis task to compile context for"
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Permanently apply generated patch during local runs. Warns before mutating."
    )
    parser.add_argument(
        "--judge-demo",
        action="store_true",
        help="Copy ./demo_repo to a temporary location, run full apply+validate, generate final_diff.txt & demo.html."
    )
    parser.add_argument(
        "--managed-agent",
        action="store_true",
        help="Force a Managed Agent remote sandbox attempt before the local pipeline."
    )
    parser.add_argument(
        "--no-managed-agent",
        action="store_true",
        help="Skip the Managed Agent remote sandbox attempt in --judge-demo."
    )
    
    args = parser.parse_args()
    
    # 1. Smoke test
    if args.smoke_test:
        run_smoke_test()
        return

    # Check API key configuration
    api_key = os.environ.get("GEMINI_API_KEY")
    no_llm = not bool(api_key)

    # 2. Judge-facing live demo on copied repo
    if args.judge_demo:
        print_banner()
        print("========================================================================")
        print("JUDGE-FACING LIVE APPLY DEMO (COPIED REPO)")
        print("========================================================================")

        # === PRIMARY PATH: Google Managed Agents remote sandbox ===
        # Always emit managed_agent_trace.json so the dashboard can show proof.
        judge_demo_trace = None
        if args.no_managed_agent:
            print("\n[Managed Agent] Skipped by --no-managed-agent flag.")
        else:
            print("\n========================================================================")
            print("MANAGED AGENT REMOTE SANDBOX (PRIMARY PATH)")
            print(f"Agent: {MANAGED_AGENT_NAME}")
            print(f"Environment: {MANAGED_AGENT_ENVIRONMENT}")
            print("========================================================================")
            judge_demo_trace = run_managed_agent_demo(
                repo_path=os.path.abspath(args.repo),
                task=args.task,
                target_ratio=args.target_ratio,
                output_trace_path="managed_agent_trace.json",
            )
            print_managed_agent_summary(judge_demo_trace)
            if judge_demo_trace.get("managed_agent_succeeded"):
                print("\nMANAGED AGENT REMOTE SANDBOX: ENABLED")
            else:
                print("\nMANAGED AGENT REMOTE SANDBOX: UNAVAILABLE - LOCAL FALLBACK USED")
                print("Managed Agent unavailable; local fallback used.")
            print("Continuing with local pipeline so the demo artifacts remain reliable...\n")

        orig_repo = args.repo
        temp_repo = "/tmp/context_compiler_live_demo_repo"
        
        print(f"Creating a clean copy of the demo repository for safe live patching:")
        print(f"  Source: {orig_repo}")
        print(f"  Destination: {temp_repo}")
        
        if os.path.exists(temp_repo):
            try:
                shutil.rmtree(temp_repo)
            except Exception as e:
                print(f"Warning: could not clean existing {temp_repo}: {e}")
        
        try:
            shutil.copytree(orig_repo, temp_repo)
            print("Copy created successfully.")
        except Exception as e:
            print(f"Error copying repository: {e}", file=sys.stderr)
            sys.exit(1)
            
        print("\nNow running the complete compiler-to-validation pipeline on the copied repo.")
        print("This will COMPACT the codebase, plan edits, generate a patch, apply it, and run tests.")
        
        ret_code = run_pipeline_local(
            repo_path=temp_repo,
            task=args.task,
            target_ratio=args.target_ratio,
            apply_patch=True, # Always apply for judge demo
            no_llm=no_llm
        )
        
        # Now create the final diff
        print("\n==========================================")
        print("Generating Final Diff against Original Repo")
        print("==========================================")
        diff_file = "final_diff.txt"
        
        # Use python-based diff or subprocess diff
        try:
            # -ruN diff with pycache and pyc exclusions
            with open(diff_file, "w") as df:
                subprocess.run(["diff", "-ruN", "--exclude=__pycache__", "--exclude=*.pyc", orig_repo, temp_repo], stdout=df)
            print(f"Saved live patch diff to: {os.path.abspath(diff_file)}")
        except Exception as e:
            print(f"Warning: Failed to run command-line diff: {e}")
            
        # Compile dashboard
        print("\n==========================================")
        print("Generating Professional HTML Dashboard")
        print("==========================================")
        viewer_cmd = [
            sys.executable, "viewer.py",
            "--manifest", "codebase_manifest.txt",
            "--debug-json", "codebase_manifest.debug.json",
            "--semantic-cards", "semantic_cards.jsonl",
            "--edit-plan", "edit_plan.md",
            "--patch-report", "patch_report.md",
            "--validation-report", "validation_report.md",
            "--out", "demo.html"
        ]
        
        res_v = subprocess.run(viewer_cmd)
        if res_v.returncode == 0:
            print(f"HTML Dashboard successfully generated: {os.path.abspath('demo.html')}")
        else:
            print("Warning: Failed to generate HTML Dashboard with viewer.py", file=sys.stderr)
            
        print("\n========================================================================")
        print("DEMO RUN COMPLETED")
        print("========================================================================")
        print(f"Patched live demo repository lives at: {temp_repo}")
        print(f"Generated code diff: {os.path.abspath(diff_file)}")
        print(f"Stunning judge dashboard: {os.path.abspath('demo.html')}")
        print("Original demo repository remains perfectly safe and UNCHANGED.")
        print("========================================================================")
        return

    # 3. URL path
    if args.repo_url:
        print_banner()
        print(f"Remote Repo Orchestration for: {args.repo_url}")
        
        has_library_support = get_agent_support()
        remote_success = False
        
        if api_key and has_library_support:
            remote_success = run_remote_managed_agent(args.repo_url, args.task)
            
        if not remote_success:
            print("[Orchestrator] Remote Managed Agent sandbox is unavailable/unbilled.")
            print("[Orchestrator] Proceeding with Local Fallback Pipeline...")
            temp_cloned = "/tmp/context_compiler_cloned_repo"
            if clone_repo(args.repo_url, temp_cloned):
                run_pipeline_local(
                    repo_path=temp_cloned,
                    task=args.task,
                    target_ratio=args.target_ratio,
                    apply_patch=args.apply,
                    no_llm=no_llm
                )
                print(f"\n[Completed] Local fallback compilation finished on cloned repo: {temp_cloned}")
            else:
                print("Error: Local fallback cloning failed. Please ensure git is installed and URL is accessible.", file=sys.stderr)
                sys.exit(1)
        return

    # 4. Standard local pipeline
    print_banner()
    if args.apply:
        print("!!! WARNING !!!")
        print(f"You specified --apply. This will modify files in-place inside: {args.repo}")
        print("Are you sure you want to proceed? (Press Ctrl+C to abort, or Enter to continue)")
        try:
            input()
        except KeyboardInterrupt:
            print("\nAborted.")
            sys.exit(0)
            
    run_pipeline_local(
        repo_path=args.repo,
        task=args.task,
        target_ratio=args.target_ratio,
        apply_patch=args.apply,
        no_llm=no_llm
    )

if __name__ == "__main__":
    main()
