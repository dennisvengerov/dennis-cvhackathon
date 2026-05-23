#!/usr/bin/env python3
"""
managed_agent_runner.py

Primary entry point for the Google Managed Agents / Antigravity remote sandbox
path of Context Compiler. Attempts a live Interactions API call to the
"antigravity-preview-05-2026" agent in a remote environment, then records an
honest trace at managed_agent_trace.json describing what actually happened.

The local pipeline (quantizer -> semantic cards -> agent harness -> patch agent
-> validator agent) remains the safety net. This module never claims that
remote execution succeeded unless the SDK returns a real Interaction object.
"""

import os
import sys
import json
import traceback
from typing import Optional


MANAGED_AGENT_NAME = "antigravity-preview-05-2026"
MANAGED_AGENT_ENVIRONMENT = "remote"


def _build_managed_agent_prompt(repo_path: str, task: str, target_ratio: float) -> str:
    return f"""You are running Context Compiler in a Google Managed Agent remote sandbox.

Your task is to run or simulate the remote workflow:

1. Inspect the repository structure at: {repo_path}
2. Explain how Context Compiler compresses the repo into codebase_manifest.txt
   (deterministic AST quantizer, signature-only skeletons, dependency graph).
3. Explain how the manifest + codebase_manifest.debug.json routes the task
   "{task}" to a small subset of files instead of dumping the whole repo.
4. Generate a concise managed-agent execution plan for this task.
5. If files in the sandbox are accessible, execute the following local commands
   in order and report stdout/stderr for each:

   python3 quantizer.py --repo {repo_path} --out codebase_manifest.txt \\
       --target-ratio {target_ratio} --format compact \\
       --debug-out codebase_manifest.debug.json
   python3 semantic_cards.py --manifest codebase_manifest.txt \\
       --debug-json codebase_manifest.debug.json \\
       --out semantic_cards.jsonl --task "{task}"
   python3 agent_harness.py --manifest codebase_manifest.txt \\
       --semantic-cards semantic_cards.jsonl --task "{task}" \\
       --out edit_plan.md
   python3 patch_agent.py --repo {repo_path} --manifest codebase_manifest.txt \\
       --semantic-cards semantic_cards.jsonl --task "{task}" \\
       --out proposed_patch.diff
   python3 validator_agent.py --repo {repo_path} \\
       --test-command "pytest -q" --out validation_report.md

6. Return a summary containing:
   - whether code execution actually happened inside the remote sandbox,
   - the list of commands that ran (and which were only simulated),
   - the artifacts that were produced.

Be honest. If you were unable to mount the workspace or execute the commands,
say so explicitly. Do not claim that tests passed unless you actually ran them.
"""


def _empty_trace() -> dict:
    return {
        "managed_agent_attempted": False,
        "managed_agent_succeeded": False,
        "agent": MANAGED_AGENT_NAME,
        "environment": MANAGED_AGENT_ENVIRONMENT,
        "environment_id": None,
        "interaction_id": None,
        "output_text": "",
        "error": None,
        "fallback_required": True,
    }


def _write_trace(trace: dict, output_trace_path: str) -> None:
    try:
        with open(output_trace_path, "w", encoding="utf-8") as trace_file:
            json.dump(trace, trace_file, indent=2)
    except Exception as write_error:
        print(
            f"[managed-agent] WARNING: could not write trace file "
            f"{output_trace_path}: {write_error}",
            file=sys.stderr,
        )


def run_managed_agent_demo(
    repo_path: str,
    task: str,
    target_ratio: float,
    output_trace_path: str = "managed_agent_trace.json",
) -> dict:
    """
    Attempt a live Google Managed Agents Interactions API call for Context
    Compiler. Always writes managed_agent_trace.json and returns the trace dict.
    """
    trace = _empty_trace()

    # Resolve API key for the SDK (supports GEMINI_API_KEY or GOOGLE_API_KEY).
    gemini_api_key: Optional[str] = (
        os.environ.get("GEMINI_API_KEY")
        or os.environ.get("GOOGLE_API_KEY")
    )

    try:
        from google import genai  # type: ignore
    except Exception as import_error:
        trace["error"] = f"google-genai SDK import failed: {import_error}"
        trace["output_text"] = (
            "google-genai SDK is not installed in this environment. "
            "Install with `pip install google-genai`."
        )
        _write_trace(trace, output_trace_path)
        return trace

    trace["managed_agent_attempted"] = True

    managed_agent_prompt = _build_managed_agent_prompt(repo_path, task, target_ratio)

    try:
        # The SDK reads GEMINI_API_KEY / GOOGLE_API_KEY from env, but we pass
        # explicitly when available so the failure mode is clear.
        if gemini_api_key:
            client = genai.Client(api_key=gemini_api_key)
        else:
            client = genai.Client()

        if not hasattr(client, "interactions"):
            raise RuntimeError(
                "google-genai client has no `interactions` attribute on this "
                "version; Managed Agents Interactions API is unavailable."
            )

        interaction = client.interactions.create(
            agent=MANAGED_AGENT_NAME,
            input=managed_agent_prompt,
            environment=MANAGED_AGENT_ENVIRONMENT,
        )

        # Best-effort extraction; field names follow the SDK convention.
        interaction_id = getattr(interaction, "id", None)
        environment_id = getattr(interaction, "environment_id", None)
        output_text = getattr(interaction, "output_text", None) or ""

        trace["managed_agent_succeeded"] = True
        trace["interaction_id"] = interaction_id
        trace["environment_id"] = environment_id
        trace["output_text"] = output_text
        trace["fallback_required"] = False
        trace["error"] = None

    except Exception as call_error:
        trace["managed_agent_succeeded"] = False
        trace["fallback_required"] = True
        trace["error"] = f"{type(call_error).__name__}: {call_error}"
        trace["output_text"] = (
            "Managed Agent unavailable; local fallback used.\n"
            f"Reason: {trace['error']}\n"
            "Traceback (truncated):\n" + "".join(traceback.format_exc().splitlines(True)[-6:])
        )

    _write_trace(trace, output_trace_path)
    return trace


def print_managed_agent_summary(trace: dict) -> None:
    """Console-friendly summary suitable for both --smoke-test and --judge-demo."""
    print("--- Managed Agent Runtime ---")
    print(f"Agent: {trace.get('agent')}")
    print(f"Environment: {trace.get('environment')}")
    print(f"SDK import: {'OK' if trace.get('managed_agent_attempted') else 'FAIL'}")
    print(f"API attempt: {'OK' if trace.get('managed_agent_succeeded') else 'FAIL'}")
    print(f"Environment ID: {trace.get('environment_id')}")
    print(f"Interaction ID: {trace.get('interaction_id')}")
    print(f"Fallback required: {str(trace.get('fallback_required')).lower()}")
    if trace.get("error"):
        print(f"Error: {trace.get('error')}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Run the Google Managed Agents path for Context Compiler."
    )
    parser.add_argument("--repo", default="./demo_repo")
    parser.add_argument("--task", default="Smoke-test Managed Agent path")
    parser.add_argument("--target-ratio", type=float, default=0.15)
    parser.add_argument("--out", default="managed_agent_trace.json")
    cli_args = parser.parse_args()

    result_trace = run_managed_agent_demo(
        repo_path=cli_args.repo,
        task=cli_args.task,
        target_ratio=cli_args.target_ratio,
        output_trace_path=cli_args.out,
    )
    print_managed_agent_summary(result_trace)
    if result_trace.get("managed_agent_succeeded"):
        print("MANAGED AGENT REMOTE SANDBOX: ENABLED")
    else:
        print("MANAGED AGENT REMOTE SANDBOX: UNAVAILABLE - LOCAL FALLBACK USED")
