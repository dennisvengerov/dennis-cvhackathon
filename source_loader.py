#!/usr/bin/env python3
"""
source_loader.py

Source snippet extraction module for Context Compiler.
Extracts minimal original source snippets with small surrounding context,
optionally full files for tiny files or companion files, and connected neighbors.
"""

import os
import sys
import json
import argparse
from typing import List, Dict, Any, Tuple, Optional, Set

from manifest_parser import ManifestParser

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Source loader and snippet extractor for Context Compiler."
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
        "--selected",
        type=str,
        default="edit_plan.json",
        help="Path to machine-readable JSON routing/selected info (default: edit_plan.json)"
    )
    parser.add_argument(
        "--out",
        type=str,
        default="selected_context.md",
        help="Path to write the selected context markdown (default: selected_context.md)"
    )
    parser.add_argument(
        "--context-lines",
        type=int,
        default=5,
        help="Number of lines of surrounding context to include (default: 5)"
    )
    parser.add_argument(
        "--tiny-threshold",
        type=int,
        default=100,
        help="Line count threshold under which a file is considered tiny (default: 100)"
    )
    return parser.parse_args()

def find_file(repo_path: str, manifest_path: str) -> Optional[str]:
    """
    Attempts to locate a file within the repo_path.
    """
    # Direct absolute/relative check
    if os.path.exists(manifest_path):
        return manifest_path
        
    # Join with repo_path
    joined = os.path.normpath(os.path.join(repo_path, manifest_path))
    if os.path.exists(joined):
        return joined
        
    # Check if we should strip the root folder name from manifest_path
    # e.g., if manifest_path is "demo_repo/app/api/checkout.py" and repo_path is "./demo_repo"
    parts = os.path.normpath(manifest_path).split(os.sep)
    repo_dir_name = os.path.basename(os.path.normpath(repo_path))
    if parts and (parts[0] == repo_dir_name or parts[0] == repo_path):
        joined_stripped = os.path.normpath(os.path.join(repo_path, *parts[1:]))
        if os.path.exists(joined_stripped):
            return joined_stripped
            
    return None

def merge_intervals(intervals: List[Tuple[int, int, str]]) -> List[Tuple[int, int, List[str]]]:
    """
    Merges overlapping or close line intervals.
    Each interval is (start, end, label).
    Returns a list of merged intervals: (start, end, list_of_labels).
    """
    if not intervals:
        return []
        
    # Sort by start line
    intervals = sorted(intervals, key=lambda x: x[0])
    
    merged: List[Tuple[int, int, List[str]]] = []
    curr_start, curr_end, curr_label = intervals[0]
    curr_labels = [curr_label]
    
    for next_start, next_end, next_label in intervals[1:]:
        # If overlapping or within 5 lines, merge them
        if next_start <= curr_end + 5:
            curr_end = max(curr_end, next_end)
            if next_label not in curr_labels:
                curr_labels.append(next_label)
        else:
            merged.append((curr_start, curr_end, curr_labels))
            curr_start, curr_end, curr_label = next_start, next_end, next_label
            curr_labels = [curr_label]
            
    merged.append((curr_start, curr_end, curr_labels))
    return merged

def main():
    args = parse_args()
    
    # 1. Verify manifest exists
    if not os.path.exists(args.manifest):
        print(f"Error: Manifest '{args.manifest}' not found.", file=sys.stderr)
        sys.exit(1)
        
    # 2. Parse codebase manifest
    debug_json_path = args.debug_json if os.path.exists(args.debug_json) else None
    parser = ManifestParser(args.manifest, debug_json_path)
    
    # 3. Load selected plan JSON
    selected_path = args.selected
    # Fallback to edit_plan.fallback.json if selected does not exist and is default
    if selected_path == "edit_plan.json" and not os.path.exists(selected_path):
        if os.path.exists("edit_plan.fallback.json"):
            selected_path = "edit_plan.fallback.json"
            print(f"Notice: edit_plan.json not found, using edit_plan.fallback.json", file=sys.stderr)
            
    if not os.path.exists(selected_path):
        print(f"Error: Selected nodes file '{selected_path}' not found.", file=sys.stderr)
        sys.exit(1)
        
    with open(selected_path, "r", encoding="utf-8") as f:
        try:
            selected_data = json.load(f)
        except json.JSONDecodeError as e:
            print(f"Error parsing '{selected_path}': {e}", file=sys.stderr)
            sys.exit(1)
            
    selected_files = selected_data.get("selected_files", [])
    if not selected_files:
        print("Warning: No selected files found in the plan JSON.", file=sys.stderr)
        
    # Track files and nodes
    output_blocks = []
    
    # 4. Process each selected file
    for f_entry in selected_files:
        manifest_path = f_entry.get("path")
        file_alias = f_entry.get("file_alias")
        
        real_file_path = find_file(args.repo, manifest_path)
        if not real_file_path:
            print(f"Warning: Could not find file {manifest_path} under repo path {args.repo}", file=sys.stderr)
            continue
            
        # Read the entire file content
        try:
            with open(real_file_path, "r", encoding="utf-8") as f:
                file_lines = f.readlines()
        except Exception as e:
            print(f"Warning: Failed to read file {real_file_path}: {e}", file=sys.stderr)
            continue
            
        total_lines = len(file_lines)
        
        # Get selected node aliases for this file
        node_aliases = f_entry.get("selected_nodes", [])
        
        intervals: List[Tuple[int, int, str]] = []
        is_tiny = total_lines <= args.tiny_threshold
        
        if is_tiny or not node_aliases:
            # Load the full file
            label = "Full File (Tiny File)" if is_tiny else "Full File (Companion Context)"
            intervals.append((1, total_lines, label))
        else:
            # Extract line ranges for each selected node
            for alias in node_aliases:
                node = parser.get_node(alias)
                if not node:
                    continue
                start = node.get("start_line", 1)
                end = node.get("end_line", total_lines)
                
                # Check for neighbors
                neighbors = parser.get_neighbors(alias)
                for neighbor in neighbors:
                    # Only include in intervals if it is in the SAME file
                    if neighbor.get("file_alias") == file_alias:
                        n_start = neighbor.get("start_line", 1)
                        n_end = neighbor.get("end_line", total_lines)
                        n_name = neighbor.get("name", "unknown")
                        # Add neighbor interval with small padding
                        n_start_pad = max(1, n_start - args.context_lines)
                        n_end_pad = min(total_lines, n_end + args.context_lines)
                        intervals.append((n_start_pad, n_end_pad, f"Neighbor: {n_name}"))
                
                # Add current node interval with padding
                start_pad = max(1, start - args.context_lines)
                end_pad = min(total_lines, end + args.context_lines)
                intervals.append((start_pad, end_pad, f"Selected: {node.get('name')}"))
                
        # Merge overlapping intervals
        merged_intervals = merge_intervals(intervals)
        
        # Extract slices and format block
        file_blocks = []
        for start, end, labels in merged_intervals:
            # 1-indexed to 0-indexed slice
            snippet_lines = file_lines[start-1:end]
            snippet = "".join(snippet_lines)
            
            labels_str = ", ".join(labels)
            block_header = f"## Context: Lines {start}-{end} ({labels_str})"
            file_blocks.append(f"{block_header}\n```python\n{snippet}\n```")
            
        if file_blocks:
            file_section = f"# File: {manifest_path}\n" + "\n\n".join(file_blocks)
            output_blocks.append(file_section)
            
    # 5. Write the extracted context to out
    full_context_md = "\n\n" + "\n\n---\n\n".join(output_blocks) if output_blocks else "# Selected Source Context\nNo matching source file context could be retrieved."
    
    with open(args.out, "w", encoding="utf-8") as out_f:
        out_f.write(full_context_md)
        
    print("Source Loader")
    print("-------------")
    print(f"Extracted context from {len(selected_files)} selected files.")
    print(f"Output saved to: {args.out}")
    print()

if __name__ == "__main__":
    main()
