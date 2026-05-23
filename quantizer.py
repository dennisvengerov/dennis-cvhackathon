#!/usr/bin/env python3
"""
Context Compiler: Graph-Driven Codebase Distillation for Managed Agents.

This script parses a Python repository, builds a directed dependency graph of
modules, classes, methods, and functions, scores each code node based on its
structural importance, and greedily fits the most valuable node bodies into
a target token budget. The rest are stored as signatures or ultra-minimal blocks.
"""

import os
import sys
import ast
import re
import math
import json
import argparse
import builtins
from typing import List, Dict, Set, Tuple, Any, Optional
from collections import Counter

# --- NOISY SYMBOLS LIST ---
NOISY_SYMBOLS = {
    "print", "open", "str", "list", "dict", "HTTPException", "APIRouter", "router.get",
    "int", "float", "bool", "len", "set", "range", "enumerate", "isinstance", "getattr",
    "setattr", "hasattr", "super", "Exception", "repr", "dir", "id", "type", "round",
    "router.post", "router.put", "router.delete", "router.patch", "router", "get", "post",
    "put", "delete", "patch", "dict.get", "list.append", "append", "sum", "min", "max",
    "abs", "zip", "map", "filter", "any", "all", "next", "iter", "callable", "hash",
    "self", "json.dumps", "json.loads", "dumps", "loads", "log_info", "log_error", 
    "logger", "logging", "info", "error", "warning", "debug", "assert", "pytest",
    "logger.info", "logger.error", "logger.warning", "logger.debug", "logging.info",
    "logging.error", "logging.warning", "logging.debug"
}

# --- CLI ARGUMENT PARSING ---

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compile a codebase into a compact, graph-structured execution manifest."
    )
    parser.add_argument(
        "--repo",
        type=str,
        default="./demo_repo",
        help="Path to the repository to compile (default: ./demo_repo)"
    )
    parser.add_argument(
        "--out",
        type=str,
        default=None,
        help="Path to output the generated manifest (defaults to codebase_manifest.txt for compact/both, codebase_manifest.debug.json for json)"
    )
    parser.add_argument(
        "--target-ratio",
        type=float,
        default=0.15,
        help="Target compression ratio for token budget (default: 0.15)"
    )
    parser.add_argument(
        "--debug-out",
        type=str,
        default=None,
        help="Path to output the generated debug JSON manifest when format is 'both' (default: codebase_manifest.debug.json)"
    )
    parser.add_argument(
        "--format",
        type=str,
        choices=["compact", "json", "debug", "both"],
        default=None,
        help="Output format to write: compact text, json debug, or both (defaults based on output file extension)"
    )
    parser.add_argument(
        "--max-edges",
        type=int,
        default=120,
        help="Maximum edges to emit in compact manifest (default: 120)"
    )
    parser.add_argument(
        "--max-unresolved-edges",
        type=int,
        default=25,
        help="Maximum unresolved edges to emit in compact manifest (default: 25)"
    )
    parser.add_argument(
        "--max-docstring-tokens",
        type=int,
        default=24,
        help="Maximum tokens of docstring to preserve in compact manifest (default: 24)"
    )
    parser.add_argument(
        "--min-full-body-nodes",
        type=int,
        default=3,
        help="Minimum full body nodes to attempt to retain even if slightly exceeding budget (default: 3)"
    )
    parser.add_argument(
        "--max-full-body-nodes",
        type=int,
        default=12,
        help="Maximum full body nodes to retain (default: 12)"
    )
    
    args = parser.parse_args()
    
    # Infer format and output if needed
    if args.format is None:
        if args.out is not None:
            if args.out.endswith(".json"):
                args.format = "json"
            elif args.out.endswith(".txt") or args.out.endswith(".md"):
                args.format = "compact"
            else:
                args.format = "compact"
        else:
            args.format = "compact"
            
    if args.format == "debug":
        args.format = "json"
            
    if args.out is None:
        if args.format in ("compact", "both"):
            args.out = "codebase_manifest.txt"
        else:
            args.out = "codebase_manifest.json"
            
    if args.format == "both" and args.debug_out is None:
        args.debug_out = "codebase_manifest.debug.json"
        
    return args


# --- TOKEN COUNTING ---

def approximate_token_count(text: str) -> int:
    """Compute a deterministic approximate token count of the given text.
    
    Splits text on words and punctuation to approximate tokenizer subwords.
    """
    if not text:
        return 0
    # Match alphanumeric sequences (words) or any single non-whitespace punctuation/symbol
    tokens = re.findall(r"\w+|[^\w\s]", text)
    return len(tokens)


def truncate_tokens(text: str, max_tokens: int) -> str:
    """Truncate a string to at most max_tokens, keeping formatting intact."""
    if not text:
        return ""
    # Find all tokens and spaces
    tokens = re.findall(r"\w+|[^\w\s]|\s+", text)
    count = 0
    result_pieces = []
    for token in tokens:
        if token.strip():
            count += 1
        result_pieces.append(token)
        if count >= max_tokens:
            result_pieces.append("...")
            break
    return "".join(result_pieces).strip()


def is_noisy_symbol(symbol: str) -> bool:
    """Check if the symbol is a noisy standard call or built-in helper."""
    if not symbol:
        return True
    parts = symbol.split(".")
    for part in parts:
        if part in NOISY_SYMBOLS:
            return True
    return False


# --- DETERMINISTIC SKELETONS & EXCERPTS HELPERS ---

def is_call_important(call_node: ast.AST) -> bool:
    if isinstance(call_node, ast.Call):
        name = get_call_name(call_node.func)
        if name and not is_noisy_symbol(name):
            return True
    return False


def contains_important_call(node: ast.AST) -> bool:
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            if is_call_important(child):
                return True
    return False


def get_important_lines(node: ast.AST) -> Set[int]:
    """Recursively identify which line numbers in the AST node body should be kept."""
    lines_to_keep = set()
    
    def process_body(body_list: List[ast.stmt]):
        for stmt in body_list:
            if isinstance(stmt, (ast.Return, ast.Raise, ast.Yield, ast.YieldFrom)):
                for l in range(stmt.lineno, (getattr(stmt, "end_lineno", None) or stmt.lineno) + 1):
                    lines_to_keep.add(l)
            elif isinstance(stmt, (ast.Assign, ast.AnnAssign, ast.Expr)):
                if contains_important_call(stmt):
                    for l in range(stmt.lineno, (getattr(stmt, "end_lineno", None) or stmt.lineno) + 1):
                        lines_to_keep.add(l)
            elif isinstance(stmt, (ast.If, ast.For, ast.While, ast.Try)):
                sub_lines = get_important_lines(stmt)
                if sub_lines:
                    lines_to_keep.add(stmt.lineno)
                    if isinstance(stmt, ast.Try):
                        for handler in stmt.handlers:
                            lines_to_keep.add(handler.lineno)
                    lines_to_keep.update(sub_lines)
            elif isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                pass
                
    if hasattr(node, "body"):
        process_body(node.body)
        if hasattr(node, "orelse") and node.orelse:
            process_body(node.orelse)
        if hasattr(node, "finalbody") and node.finalbody:
            process_body(node.finalbody)
                
    return lines_to_keep


def get_indent(line: str) -> str:
    return line[:len(line) - len(line.lstrip())]


def generate_excerpt(node: ast.AST, file_lines: List[str]) -> str:
    """Generate a deterministic excerpt of a function/method body."""
    if not hasattr(node, "body") or not node.body:
        return ""
        
    body_start_line = node.body[0].lineno
    sig_lines = file_lines[node.lineno - 1 : body_start_line - 1]
    
    lines_to_keep = get_important_lines(node)
    
    excerpt_body_lines = []
    in_gap = False
    gap_indent = ""
    
    end_line = getattr(node, "end_lineno", None) or node.body[-1].lineno
    
    for l in range(body_start_line, end_line + 1):
        if l - 1 < len(file_lines):
            line_content = file_lines[l - 1]
            if l in lines_to_keep:
                if in_gap:
                    excerpt_body_lines.append(f"{gap_indent}...\n")
                    in_gap = False
                excerpt_body_lines.append(line_content)
            else:
                if not in_gap:
                    gap_indent = get_indent(line_content)
                    in_gap = True
                
    if in_gap:
        excerpt_body_lines.append(f"{gap_indent}...\n")
        
    return "".join(sig_lines) + "".join(excerpt_body_lines)


def extract_behavior_skeleton(
    node: ast.AST,
    local_types: Dict[str, str],
    file_path: str,
    resolve_symbol_fn: Any,
    source_node: Dict[str, Any]
) -> Dict[str, Any]:
    """Extract a dictionary of deterministic behavior skeleton facts from a function/method AST."""
    direct_calls = []
    resolved_calls = []
    constructors = []
    raises = []
    assigned = []
    writes = []
    reads = []
    literals = []
    control_flow = []
    
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            call_name = get_call_name(child.func)
            if call_name and not is_noisy_symbol(call_name):
                is_const = False
                last_part = call_name.split(".")[-1]
                if last_part and last_part[0].isupper():
                    is_const = True
                elif call_name in local_types:
                    is_const = True
                
                if is_const:
                    if call_name not in constructors:
                        constructors.append(call_name)
                else:
                    if call_name not in direct_calls:
                        direct_calls.append(call_name)
                        
                target_id, resolved = resolve_symbol_fn(call_name, file_path, source_node)
                if resolved and target_id:
                    short_name = target_id.split("::")[-1]
                    if short_name not in resolved_calls:
                        resolved_calls.append(short_name)
        
        elif isinstance(child, ast.Raise):
            if child.exc:
                exc_name = None
                if isinstance(child.exc, ast.Call):
                    exc_name = get_call_name(child.exc.func)
                elif isinstance(child.exc, ast.Name):
                    exc_name = child.exc.id
                if exc_name and exc_name not in raises:
                    raises.append(exc_name)
                    
        elif isinstance(child, (ast.Assign, ast.AnnAssign)):
            targets = [child.target] if isinstance(child, ast.AnnAssign) else child.targets
            for tgt in targets:
                flat_targets = []
                def flatten_tgt(t):
                    if isinstance(t, (ast.Tuple, ast.List)):
                        for el in t.elts:
                            flatten_tgt(el)
                    else:
                        flat_targets.append(t)
                flatten_tgt(tgt)
                
                for ftgt in flat_targets:
                    if isinstance(ftgt, ast.Name):
                        var_name = ftgt.id
                        var_lower = var_name.lower()
                        important_vars = {"payment", "order", "user", "result", "status", "response", "client", "db", "items", "data", "payload", "config", "token", "auth"}
                        if any(iv in var_lower for iv in important_vars) and len(var_name) > 1:
                            if var_name not in assigned:
                                assigned.append(var_name)
                    elif isinstance(ftgt, ast.Attribute):
                        attr_str = get_call_name(ftgt)
                        if attr_str and (attr_str.startswith("self.") or any(part in attr_str for part in ("status", "payment", "order", "user"))):
                            if attr_str not in writes:
                                writes.append(attr_str)
                                
        elif isinstance(child, ast.Attribute):
            attr_str = get_call_name(child)
            if attr_str:
                parts = attr_str.split(".")
                obj_name = parts[0]
                if obj_name in ("request", "payload", "data", "user", "order", "item") or obj_name in local_types:
                    if attr_str not in reads:
                        reads.append(attr_str)
                        
        elif isinstance(child, ast.Constant):
            val = child.value
            if isinstance(val, str):
                val_lower = val.lower()
                if val.startswith("/"):
                    if val not in literals:
                        literals.append(val)
                elif val in ("GET", "POST", "PUT", "DELETE", "PATCH"):
                    if val not in literals:
                        literals.append(val)
                elif re.match(r"^[A-Z][A-Z0-9_]{3,}$", val):
                    if val not in literals:
                        literals.append(val)
                elif any(kw in val_lower for kw in ("success", "failed", "error", "invalid", "not found", "payment", "order", "user", "auth")):
                    if len(val) < 40:
                        if val not in literals:
                            literals.append(val)
            elif isinstance(val, int) and not isinstance(val, bool):
                if val in (200, 201, 400, 401, 403, 404, 500):
                    if str(val) not in literals:
                        literals.append(str(val))
                        
        elif isinstance(child, ast.If):
            if "if" not in control_flow:
                control_flow.append("if")
        elif isinstance(child, (ast.For, ast.While)):
            if "loop" not in control_flow:
                control_flow.append("loop")
        elif isinstance(child, ast.Try):
            if "try" not in control_flow and "except" not in control_flow:
                control_flow.extend(["try", "except"])

    return_count = 0
    has_nested_return = False
    for child in ast.walk(node):
        if isinstance(child, ast.Return):
            return_count += 1
            
    def check_nested_return(body_list):
        nonlocal has_nested_return
        for stmt in body_list:
            if isinstance(stmt, (ast.If, ast.For, ast.While, ast.Try)):
                for sub in ast.walk(stmt):
                    if isinstance(sub, ast.Return):
                        has_nested_return = True
                        return
                        
    if hasattr(node, "body"):
        check_nested_return(node.body)
        
    if return_count > 1 or has_nested_return:
        if "early_return" not in control_flow:
            control_flow.append("early_return")

    returns_val = "unknown"
    return_nodes = [n for n in ast.walk(node) if isinstance(n, ast.Return)]
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.returns:
        ret_ann = get_call_name(node.returns)
        if ret_ann:
            returns_val = ret_ann
    elif return_nodes:
        last_ret = return_nodes[-1]
        if last_ret.value is None:
            returns_val = "None"
        elif isinstance(last_ret.value, (ast.Dict, ast.DictComp)):
            returns_val = "dict"
        elif isinstance(last_ret.value, (ast.List, ast.ListComp)):
            returns_val = "list"
        elif isinstance(last_ret.value, (ast.Tuple)):
            returns_val = "tuple"
        elif isinstance(last_ret.value, ast.Call):
            func_name = get_call_name(last_ret.value.func)
            if func_name:
                returns_val = f"call:{func_name}"
        elif isinstance(last_ret.value, ast.Constant):
            val = last_ret.value.value
            returns_val = type(val).__name__ if val is not None else "None"
            
    flow_steps = []
    if hasattr(node, "body"):
        for stmt in node.body:
            if isinstance(stmt, (ast.If)):
                flow_steps.append("if")
            elif isinstance(stmt, (ast.For, ast.While)):
                flow_steps.append("loop")
            elif isinstance(stmt, ast.Try):
                flow_steps.append("try")
            elif isinstance(stmt, (ast.Assign, ast.AnnAssign, ast.Expr)):
                stmt_calls = find_calls_in_node(stmt)
                for sc in stmt_calls:
                    if not is_noisy_symbol(sc):
                        short_sc = sc.split(".")[-1]
                        verb = short_sc.lower()
                        if "validate" in verb or "check" in verb:
                            flow_steps.append("validate")
                        elif "payment" in verb or "charge" in verb or "pay" in verb:
                            flow_steps.append("pay")
                        elif "create" in verb or "insert" in verb or "write" in verb or "save" in verb or "add" in verb or "persist" in verb:
                            flow_steps.append("persist")
                        elif "get" in verb or "find" in verb or "read" in verb or "query" in verb or "fetch" in verb:
                            flow_steps.append("fetch")
                        else:
                            flow_steps.append(short_sc)
            elif isinstance(stmt, ast.Return):
                flow_steps.append("return")
                
    clean_flow = []
    for step in flow_steps:
        if not clean_flow or clean_flow[-1] != step:
            clean_flow.append(step)
            
    if return_nodes and "return" not in clean_flow:
        clean_flow.append("return")
        
    flow_str = "->".join(clean_flow) if clean_flow else "unknown"

    effects = []
    all_names = [node.name.lower()] + [c.lower() for c in direct_calls] + [c.lower() for c in constructors]
    all_literals = [str(l).lower() for l in literals]
    
    if hasattr(node, "decorator_list"):
        for dec in node.decorator_list:
            dec_name = get_call_name(dec)
            if dec_name:
                all_names.append(dec_name.lower())
                
    def check_keywords(kws):
        return any(any(kw in name for kw in kws) for name in all_names) or any(any(kw in lit for kw in kws) for lit in all_literals)

    if check_keywords(["validate", "check", "verify", "schema", "pydantic"]):
        effects.append("validation")
    if check_keywords(["auth", "login", "jwt", "token", "password", "security", "permission"]):
        effects.append("auth")
    if check_keywords(["payment", "charge", "stripe", "pay", "transaction", "invoice", "checkout"]):
        effects.append("payment")
    if check_keywords(["get", "find", "read", "query", "fetch", "select", "db"]):
        effects.append("db_read")
    if check_keywords(["create", "update", "delete", "insert", "save", "write", "persist", "commit", "db"]):
        effects.append("db_write")
    if check_keywords(["open", "read", "write", "filepath", "os.path"]):
        effects.append("file_io")
    if check_keywords(["requests", "httpx", "aiohttp", "urllib", "socket"]):
        effects.append("network")
    if check_keywords(["redis", "cache", "memcached"]):
        effects.append("cache")
    if check_keywords(["print", "log", "logger", "logging", "info", "error", "warning", "debug"]):
        effects.append("logging")
    if check_keywords(["stripe", "sendgrid", "google", "api"]):
        effects.append("external_api")
    if check_keywords(["email", "mail", "sendgrid", "smtp"]):
        effects.append("email")
    if check_keywords(["json", "dump", "load", "serialize", "deserialize"]):
        effects.append("serialization")

    all_calls_combined = direct_calls + constructors

    return {
        "calls": all_calls_combined,
        "resolved_calls": resolved_calls,
        "flow": flow_str,
        "effects": effects,
        "raises": raises,
        "returns": returns_val,
        "reads": reads,
        "control_flow": control_flow,
        "assigned": assigned,
        "writes": writes,
        "literals": literals
    }


# --- AST TRAVERSAL & EXTRACTION HELPERS ---

def resolve_relative_module(current_module: str, import_from_module: str, level: int) -> str:
    """Resolve a relative python import to its absolute dot-separated module path."""
    parts = current_module.split(".")
    if len(parts) >= level:
        base_parts = parts[:-level]
    else:
        base_parts = []
    
    if import_from_module:
        base_parts.append(import_from_module)
    return ".".join(base_parts)


def get_call_name(node: ast.AST) -> Optional[str]:
    """Recursively reconstruct name/attribute identifiers into a dot-separated string."""
    if isinstance(node, ast.Name):
        return node.id
    elif isinstance(node, ast.Attribute):
        val = get_call_name(node.value)
        if val:
            return f"{val}.{node.attr}"
        return node.attr
    return None


def find_calls_in_node(node: ast.AST) -> List[str]:
    """Find all unique best-effort calls inside a code block, pruning nested definitions."""
    calls: List[str] = []
    
    def traverse(n: ast.AST) -> None:
        if isinstance(n, ast.Call):
            name = get_call_name(n.func)
            if name:
                calls.append(name)
        
        # Traverse children, but skip nested functions and classes
        for child in ast.iter_child_nodes(n):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            traverse(child)
            
    # For the root node, traverse its body but ignore nested definitions
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        traverse(child)
        
    # Remove duplicates preserving order
    return list(dict.fromkeys(calls))


def find_imports_in_node(node: ast.AST, current_module: str) -> List[Dict[str, Any]]:
    """Find all module-level or local imports inside a code block, pruning nested definitions."""
    imports: List[Dict[str, Any]] = []
    
    def traverse(n: ast.AST) -> None:
        if isinstance(n, ast.Import):
            for alias in n.names:
                imports.append({
                    "module": alias.name,
                    "name": alias.name,
                    "alias": alias.asname,
                    "type": "import"
                })
        elif isinstance(n, ast.ImportFrom):
            level = n.level
            module_name = n.module or ""
            if level > 0:
                resolved_module = resolve_relative_module(current_module, module_name, level)
            else:
                resolved_module = module_name
                
            for alias in n.names:
                imports.append({
                    "module": resolved_module,
                    "name": alias.name,
                    "alias": alias.asname,
                    "type": "from_import"
                })
                
        for child in ast.iter_child_nodes(n):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            traverse(child)
            
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        traverse(child)
        
    return imports


def get_base_classes(node: ast.ClassDef) -> List[str]:
    """Extract list of base class names from a class definition node."""
    bases: List[str] = []
    for base in node.bases:
        name = get_call_name(base)
        if name:
            bases.append(name)
    return bases


def check_has_type_annotations(node: ast.AST) -> bool:
    """Determine whether a given AST node has type annotations or typed variables."""
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        if node.returns is not None:
            return True
        for arg in node.args.args:
            if arg.annotation is not None:
                return True
        for arg in node.args.kwonlyargs:
            if arg.annotation is not None:
                return True
        if node.args.vararg and node.args.vararg.annotation is not None:
            return True
        if node.args.kwarg and node.args.kwarg.annotation is not None:
            return True
    elif isinstance(node, ast.ClassDef):
        for child in node.body:
            if isinstance(child, ast.AnnAssign):
                return True
    elif isinstance(node, ast.Module):
        for child in node.body:
            if isinstance(child, ast.AnnAssign):
                return True
    return False


def get_signature(lines: List[str], start_line: int, end_line: int) -> str:
    """Extract and reconstruct the exact declaration signature of a function/class."""
    sig_start_idx = -1
    for idx in range(start_line - 1, end_line):
        line = lines[idx]
        stripped = line.strip()
        if stripped.startswith("def ") or stripped.startswith("async def ") or stripped.startswith("class "):
            sig_start_idx = idx
            break
            
    if sig_start_idx == -1:
        sig_start_idx = start_line - 1

    chars: List[str] = []
    nesting = 0
    in_single_quote = False
    in_double_quote = False
    in_triple_single = False
    in_triple_double = False
    found_end = False
    
    for idx in range(sig_start_idx, end_line):
        line = lines[idx]
        for i, char in enumerate(line):
            chars.append(char)
            
            # Simple string / quote literal parsing inside signature to ignore colons
            if not (in_single_quote or in_double_quote or in_triple_single or in_triple_double):
                if char == "#":
                    chars.pop()  # Drop hash symbol
                    break        # Skip rest of comment line
            
            curr_str = "".join(chars[-3:])
            if curr_str == "'''" and not in_double_quote and not in_triple_double:
                in_triple_single = not in_triple_single
                continue
            if curr_str == '"""' and not in_single_quote and not in_triple_single:
                in_triple_double = not in_triple_double
                continue
                
            if in_triple_single or in_triple_double:
                continue
                
            if char == "'" and not in_double_quote:
                if len(chars) > 1 and chars[-2] == "\\":
                    continue
                in_single_quote = not in_single_quote
            elif char == '"' and not in_single_quote:
                if len(chars) > 1 and chars[-2] == "\\":
                    continue
                in_double_quote = not in_double_quote
                
            if in_single_quote or in_double_quote:
                continue
                
            # Track parentheses/braces nesting level
            if char in "([{":
                nesting += 1
            elif char in ")]}":
                nesting = max(0, nesting - 1)
            elif char == ":" and nesting == 0:
                found_end = True
                break
        if found_end:
            break
            
    return "".join(chars).strip()


def extract_body(lines: List[str], start_line: int, end_line: int) -> str:
    """Extract code slice between start and end lines (1-based indices)."""
    if start_line is None or end_line is None:
        return ""
    selected = lines[start_line - 1 : end_line]
    return "".join(selected)


# --- TYPE EXTRACTION HELPERS FOR DETAILED AST EDGE RESOLUTION ---

def extract_module_local_types(module_tree: ast.Module) -> Dict[str, str]:
    """Find module-level assignments of local variables to class types."""
    local_types = {}
    for child in module_tree.body:
        if isinstance(child, ast.Assign):
            for target in child.targets:
                if isinstance(target, ast.Name):
                    if isinstance(child.value, ast.Call):
                        call_name = get_call_name(child.value.func)
                        if call_name:
                            local_types[target.id] = call_name
        elif isinstance(child, ast.AnnAssign):
            if isinstance(child.target, ast.Name):
                ann_name = get_call_name(child.annotation)
                if ann_name:
                    local_types[child.target.id] = ann_name
    return local_types


def extract_local_types_from_func(func_node: ast.AST) -> Dict[str, str]:
    """Extract types of local variables inside a function or method definition."""
    local_types = {}
    # 1. Parameter annotations
    if isinstance(func_node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        for arg in func_node.args.args:
            if arg.annotation:
                ann_name = get_call_name(arg.annotation)
                if ann_name:
                    local_types[arg.arg] = ann_name
        for arg in func_node.args.kwonlyargs:
            if arg.annotation:
                ann_name = get_call_name(arg.annotation)
                if ann_name:
                    local_types[arg.arg] = ann_name
                    
    # 2. Variable assignments in body
    for child in ast.walk(func_node):
        if isinstance(child, ast.Assign):
            for target in child.targets:
                if isinstance(target, ast.Name):
                    if isinstance(child.value, ast.Call):
                        call_name = get_call_name(child.value.func)
                        if call_name:
                            local_types[target.id] = call_name
        elif isinstance(child, ast.AnnAssign):
            if isinstance(child.target, ast.Name):
                ann_name = get_call_name(child.annotation)
                if ann_name:
                    local_types[child.target.id] = ann_name
                    
    return local_types


def get_decorator_info(decorator_node: ast.AST) -> Dict[str, Any]:
    """Extract details about a decorator call or name identifier."""
    if isinstance(decorator_node, ast.Call):
        name = get_call_name(decorator_node.func)
        args = []
        for arg in decorator_node.args:
            if isinstance(arg, ast.Constant):
                args.append(str(arg.value))
            elif isinstance(arg, ast.Str):
                args.append(arg.s)
        return {"name": name, "args": args}
    else:
        name = get_call_name(decorator_node)
        return {"name": name, "args": []}


# --- TAGGING AND METADATA ANALYSIS ---

def assign_tags_and_metadata(node: Dict[str, Any]) -> List[str]:
    """Determine categorizing tags for a node based on context, type, and patterns."""
    tags = []
    node_type = node["type"]
    name = node["name"]
    filepath = node["file"]
    
    # 1. Type tags
    if node_type == "class":
        tags.append("class")
    elif node_type in ("method", "async_method"):
        tags.append("method")
        
    if "async" in node_type:
        tags.append("async")
        
    if node["is_public"]:
        tags.append("public")
    else:
        tags.append("private")
        
    # 2. Path-based tagging
    path_lower = filepath.lower()
    if "test" in path_lower or name.lower().startswith("test") or name.lower().endswith("test"):
        tags.append("test")
    if "route" in path_lower or "router" in path_lower or "api" in path_lower:
        if node_type in ("function", "async_function", "method", "async_method") and node["is_public"]:
            tags.append("endpoint")
            
    if "models" in path_lower:
        tags.append("model")
    if "schemas" in path_lower:
        tags.append("schema")
    if "services" in path_lower:
        tags.append("service")
    if "utils" in path_lower or "helpers" in path_lower:
        tags.append("utility")
        
    # 3. Class-based tags (for class or members of a class)
    if node_type == "class":
        class_name_lower = name.lower()
        if "model" in class_name_lower:
            tags.append("model")
        if "schema" in class_name_lower or "request" in class_name_lower or "response" in class_name_lower:
            tags.append("schema")
        if "service" in class_name_lower:
            tags.append("service")
            
        for base in node.get("base_classes", []):
            base_lower = base.lower()
            if "basemodel" in base_lower or "schema" in base_lower:
                tags.append("schema")
            if "model" in base_lower or "base" in base_lower or "declarativebase" in base_lower:
                tags.append("model")
                
    # 4. Decorator-based route tagging
    for dec in node.get("decorators", []):
        dec_name = dec["name"] or ""
        dec_name_lower = dec_name.lower()
        route_methods = {"get", "post", "put", "delete", "patch", "route", "api_route"}
        parts = dec_name_lower.split(".")
        if any(part in route_methods for part in parts):
            if "route" not in tags:
                tags.append("route")
            if "endpoint" not in tags:
                tags.append("endpoint")
                
    # Deduplicate tags and return
    return sorted(list(set(tags)))


# --- CODEBASE WALK & AST PARSING ---

def parse_file(filepath: str, repo_dir: str, warnings: List[str]) -> List[Dict[str, Any]]:
    """Parse a single Python file, returning all extracted code nodes."""
    rel_path = os.path.relpath(filepath, repo_dir).replace('\\', '/')
    
    # Calculate module dot path relative to the repo
    if rel_path.endswith("__init__.py"):
        if rel_path == "__init__.py":
            module_name = ""
        else:
            module_name = rel_path[:-12].replace('/', '.')
    else:
        module_name = rel_path[:-3].replace('/', '.')

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            source_code = f.read()
    except Exception as e:
        warnings.append(f"Skipped file {rel_path} - unable to read: {e}")
        return []

    try:
        tree = ast.parse(source_code, filename=filepath)
    except Exception as e:
        warnings.append(f"Parse error in {rel_path}: {e}")
        return []

    lines = source_code.splitlines(keepends=True)
    num_lines = len(lines) if lines else 1
    
    nodes: List[Dict[str, Any]] = []
    
    module_local_types = extract_module_local_types(tree)

    # 1. Module Node
    module_doc = ast.get_docstring(tree) or ""
    module_node = {
        "id": f"{rel_path}::<module>",
        "type": "module",
        "name": "<module>",
        "qualified_name": "<module>",
        "file": rel_path,
        "start_line": 1,
        "end_line": num_lines,
        "signature": rel_path,
        "docstring": module_doc,
        "token_count": approximate_token_count(source_code),
        "full_body": source_code,
        "calls": find_calls_in_node(tree),
        "imports": find_imports_in_node(tree, module_name),
        "base_classes": [],
        "is_public": 1 if not os.path.basename(filepath).startswith("_") else 0,
        "has_docstring": 1 if module_doc else 0,
        "has_type_annotations": 1 if check_has_type_annotations(tree) else 0,
        "in_degree": 0,
        "out_degree": 0,
        "score": 0.0,
        "value_density": 0.0,
        "mode": "signature_only",
        "decorators": [],
        "local_types": module_local_types,
        "tags": [],
        "ast_node": tree
    }
    nodes.append(module_node)

    # Walk module top-level body definitions
    for child in tree.body:
        if isinstance(child, ast.ClassDef):
            # 2. Class Node
            class_doc = ast.get_docstring(child) or ""
            class_body = extract_body(lines, child.lineno, child.end_lineno)
            
            # Decorators for class
            class_decorators = []
            for dec in child.decorator_list:
                dec_info = get_decorator_info(dec)
                if dec_info["name"]:
                    class_decorators.append(dec_info)
                    
            class_node = {
                "id": f"{rel_path}::{child.name}",
                "type": "class",
                "name": child.name,
                "qualified_name": child.name,
                "file": rel_path,
                "start_line": child.lineno,
                "end_line": child.end_lineno,
                "signature": get_signature(lines, child.lineno, child.end_lineno),
                "docstring": class_doc,
                "token_count": approximate_token_count(class_body),
                "full_body": class_body,
                "calls": find_calls_in_node(child),
                "imports": find_imports_in_node(child, module_name),
                "base_classes": get_base_classes(child),
                "is_public": 1 if not child.name.startswith("_") else 0,
                "has_docstring": 1 if class_doc else 0,
                "has_type_annotations": 1 if check_has_type_annotations(child) else 0,
                "in_degree": 0,
                "out_degree": 0,
                "score": 0.0,
                "value_density": 0.0,
                "mode": "signature_only",
                "decorators": class_decorators,
                "local_types": module_local_types.copy(),
                "tags": [],
                "ast_node": child
            }
            nodes.append(class_node)

            # 3. Class Methods (nested inside ClassDef)
            for subchild in child.body:
                if isinstance(subchild, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    method_doc = ast.get_docstring(subchild) or ""
                    method_body = extract_body(lines, subchild.lineno, subchild.end_lineno)
                    is_async = isinstance(subchild, ast.AsyncFunctionDef)
                    
                    method_decorators = []
                    method_dec_calls = []
                    for dec in subchild.decorator_list:
                        dec_info = get_decorator_info(dec)
                        if dec_info["name"]:
                            method_decorators.append(dec_info)
                            method_dec_calls.append(dec_info["name"])
                            
                    method_calls = find_calls_in_node(subchild)
                    for mc in method_dec_calls:
                        if mc not in method_calls:
                            method_calls.append(mc)
                            
                    method_node = {
                        "id": f"{rel_path}::{child.name}.{subchild.name}",
                        "type": "async_method" if is_async else "method",
                        "name": subchild.name,
                        "qualified_name": f"{child.name}.{subchild.name}",
                        "file": rel_path,
                        "start_line": subchild.lineno,
                        "end_line": subchild.end_lineno,
                        "signature": get_signature(lines, subchild.lineno, subchild.end_lineno),
                        "docstring": method_doc,
                        "token_count": approximate_token_count(method_body),
                        "full_body": method_body,
                        "calls": method_calls,
                        "imports": find_imports_in_node(subchild, module_name),
                        "base_classes": [],
                        "is_public": 1 if not subchild.name.startswith("_") else 0,
                        "has_docstring": 1 if method_doc else 0,
                        "has_type_annotations": 1 if check_has_type_annotations(subchild) else 0,
                        "in_degree": 0,
                        "out_degree": 0,
                        "score": 0.0,
                        "value_density": 0.0,
                        "mode": "signature_only",
                        "decorators": method_decorators,
                        "local_types": {**module_local_types, **extract_local_types_from_func(subchild)},
                        "tags": [],
                        "ast_node": subchild
                    }
                    nodes.append(method_node)

        elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            # 4. Standalone Function Node
            func_doc = ast.get_docstring(child) or ""
            func_body = extract_body(lines, child.lineno, child.end_lineno)
            is_async = isinstance(child, ast.AsyncFunctionDef)
            
            func_decorators = []
            func_dec_calls = []
            for dec in child.decorator_list:
                dec_info = get_decorator_info(dec)
                if dec_info["name"]:
                    func_decorators.append(dec_info)
                    func_dec_calls.append(dec_info["name"])
                    
            func_calls = find_calls_in_node(child)
            for fc in func_dec_calls:
                if fc not in func_calls:
                    func_calls.append(fc)
                    
            func_node = {
                "id": f"{rel_path}::{child.name}",
                "type": "async_function" if is_async else "function",
                "name": child.name,
                "qualified_name": child.name,
                "file": rel_path,
                "start_line": child.lineno,
                "end_line": child.end_lineno,
                "signature": get_signature(lines, child.lineno, child.end_lineno),
                "docstring": func_doc,
                "token_count": approximate_token_count(func_body),
                "full_body": func_body,
                "calls": func_calls,
                "imports": find_imports_in_node(child, module_name),
                "base_classes": [],
                "is_public": 1 if not child.name.startswith("_") else 0,
                "has_docstring": 1 if func_doc else 0,
                "has_type_annotations": 1 if check_has_type_annotations(child) else 0,
                "in_degree": 0,
                "out_degree": 0,
                "score": 0.0,
                "value_density": 0.0,
                "mode": "signature_only",
                "decorators": func_decorators,
                "local_types": {**module_local_types, **extract_local_types_from_func(child)},
                "tags": [],
                "ast_node": child
            }
            nodes.append(func_node)

    return nodes


# --- UNRESOLVED SYMBOLS CLASSIFIER ---

def classify_unresolved_symbol(symbol: str, imports: List[Dict[str, Any]]) -> str:
    """Classify an external symbol into a category like framework, stdlib, third_party, etc."""
    parts = symbol.split(".")
    first_segment = parts[0]
    
    if first_segment in dir(builtins):
        return "builtin"
        
    full_module = None
    for imp in imports:
        imp_name = imp["name"]
        imp_module = imp["module"]
        imp_alias = imp["alias"]
        local_name = imp_alias if imp_alias else imp_name.split(".")[0] if imp["type"] == "import" else imp_name
        
        if first_segment == local_name:
            full_module = imp_module or imp_name
            break
            
    root_pkg = first_segment
    if full_module:
        root_pkg = full_module.split(".")[0]
        
    stdlib_modules = set()
    if hasattr(sys, "stdlib_module_names"):
        stdlib_modules = sys.stdlib_module_names
    else:
        stdlib_modules = {
            "os", "sys", "time", "datetime", "json", "math", "re", "collections", "urllib", "hashlib", "hmac", 
            "typing", "functools", "logging", "asyncio", "uuid", "abc", "argparse", "pathlib", "shutil", 
            "tempfile", "unittest", "traceback", "random", "csv", "sqlite3", "base64", "io", "struct", "pickle"
        }
        
    if root_pkg in stdlib_modules:
        return "stdlib"
        
    frameworks = {
        "fastapi", "flask", "django", "pydantic", "sqlalchemy", "pytest", "starlette", "jinja2", "uvicorn", "ast"
    }
    if root_pkg in frameworks:
        return "framework"
        
    third_parties = {
        "stripe", "requests", "numpy", "pandas", "yaml", "dotenv", "jose", "passlib", "httpx", "aiohttp", 
        "redis", "pika", "celery", "boto3", "psycopg2", "cryptography", "jwt", "google"
    }
    if root_pkg in third_parties:
        return "third_party"
        
    if full_module:
        return "third_party"
        
    return "unknown"


# --- COMPACT MANIFEST SERIALIZATION HELPERS ---

def serialize_node_compact(
    node: Dict[str, Any],
    node_alias: str,
    file_alias: str,
    max_docstring_tokens: int,
    use_docstrings: bool = True,
    use_tags: bool = True,
    current_mode: str = None
) -> str:
    """Serialize a single node in a space-efficient line-oriented format."""
    node_type = node["type"]
    if node_type == "function":
        node_type = "fn"
    elif node_type == "async_function":
        node_type = "async_fn"
        
    start = node["start_line"]
    end = node["end_line"]
    qualified_name = node["qualified_name"]
    score = node["score"]
    in_deg = node["in_degree"]
    out_deg = node["out_degree"]
    
    if current_mode is None:
        current_mode = node.get("mode", "sig")
        
    if current_mode in ("minimal", "min", "ultra_min"):
        mode_abbr = "min"
        return f"{node_alias} {file_alias}:{start}-{end} {node_type} {qualified_name} score={score:.2f} mode={mode_abbr}"
        
    mode_abbr = current_mode
    if current_mode == "full_body" or current_mode == "body":
        mode_abbr = "body"
    elif current_mode == "signature_only":
        mode_abbr = "sig"
        
    # Prepare clean signature
    sig_raw = node["signature"] or ""
    sig_clean = " ".join(sig_raw.split())
    sig_escaped = sig_clean.replace('"', '\\"')
    
    # Docstring handling
    doc_part = ""
    if use_docstrings and max_docstring_tokens > 0 and node.get("docstring"):
        doc_clean = " ".join(node["docstring"].split())
        doc_trunc = truncate_tokens(doc_clean, max_docstring_tokens)
        if doc_trunc:
            doc_escaped = doc_trunc.replace('"', '\\"')
            doc_part = f' doc="{doc_escaped}"'
            
    # Tags handling
    tags_part = ""
    if use_tags and node.get("tags"):
        tags_str = ",".join(node["tags"])
        tags_part = f' tags={tags_str}'
        
    if node_type == "module":
        line = f"{node_alias} {file_alias}:{start}-{end} {node_type} {qualified_name} score={score:.2f} in={in_deg} out={out_deg} mode={mode_abbr}"
    else:
        line = f"{node_alias} {file_alias}:{start}-{end} {node_type} {qualified_name} sig=\"{sig_escaped}\" score={score:.2f} in={in_deg} out={out_deg} mode={mode_abbr}"
        
    if doc_part:
        line += doc_part
    if tags_part:
        line += tags_part
        
    return line


def serialize_edge_compact(edge: Dict[str, Any], node_to_alias: Dict[str, str]) -> str:
    """Serialize a dependency edge using node aliases."""
    src_alias = node_to_alias.get(edge["source"])
    if not src_alias:
        return ""
        
    resolved = edge["resolved"]
    edge_type = edge["type"]
    if edge_type == "inheritance":
        edge_type = "inherit"
    elif edge_type == "reference":
        edge_type = "ref"
    raw_symbol = edge["raw_symbol"]
    
    if resolved:
        target_alias = node_to_alias.get(edge["target"])
        if target_alias:
            return f"{src_alias} -> {target_alias} {edge_type} {raw_symbol} resolved"
            
    # For unresolved edges:
    classification = edge.get("classification", "unknown")
    return f"{src_alias} -> EXT:{edge['target']} {edge_type} {classification}"


def get_exact_compact_manifest_string_with_modes(
    repo_name: str,
    target_ratio: float,
    original_tokens: int,
    nodes: List[Dict[str, Any]],
    file_to_alias: Dict[str, str],
    node_to_alias: Dict[str, str],
    emitted_edges: List[Dict[str, Any]],
    resolved_edges_count: int,
    unresolved_edges_count: int,
    max_docstring_tokens: int,
    use_docstrings: bool = True,
    use_tags: bool = True,
    node_modes: Dict[str, str] = None,
    parse_error_count: int = 0,
    debug_edges_total: int = 0,
    status_str: str = "HIT"
) -> Tuple[str, int]:
    """Assemble all manifest elements into the final line-oriented text artifact with precise modes."""
    if node_modes is None:
        node_modes = {n["id"]: n.get("mode", "sig") for n in nodes}
        
    def build_with_tokens(tok_val: int, rat_val: float) -> str:
        lines = []
        lines.append("# Context Compiler Manifest v3")
        
        full_body_count = sum(1 for n in nodes if node_modes.get(n["id"]) in ("full_body", "body"))
        excerpt_count = sum(1 for n in nodes if node_modes.get(n["id"]) == "excerpt")
        skeleton_count = sum(1 for n in nodes if node_modes.get(n["id"]) == "skel")
        sig_count = sum(1 for n in nodes if node_modes.get(n["id"]) in ("sig", "signature_only"))
        min_count = sum(1 for n in nodes if node_modes.get(n["id"]) in ("min", "minimal", "ultra_min"))
        
        meta_line = (
            f"META repo={repo_name} original_tokens={original_tokens} "
            f"compressed_tokens={tok_val} "
            f"ratio={rat_val:.3f} target={target_ratio:.3f} "
            f"files={len(file_to_alias)} nodes={len(nodes)} "
            f"debug_edges_total={debug_edges_total} "
            f"serialized_edges_total={len(emitted_edges)} "
            f"serialized_resolved_edges={resolved_edges_count} "
            f"serialized_unresolved_edges={unresolved_edges_count} "
            f"body={full_body_count} excerpt={excerpt_count} skel={skeleton_count} "
            f"sig={sig_count} min={min_count} status={status_str}"
        )
        lines.append(meta_line)
        lines.append("")
        
        # Files Section
        lines.append("FILES")
        for f_path in sorted(file_to_alias.keys()):
            lines.append(f"{file_to_alias[f_path]} {f_path}")
        lines.append("")
        
        # Nodes Section
        lines.append("NODES")
        for node in sorted(nodes, key=lambda x: x["id"]):
            node_id = node["id"]
            node_alias = node_to_alias[node_id]
            file_alias = file_to_alias[node["file"]]
            node_line = serialize_node_compact(
                node, node_alias, file_alias, max_docstring_tokens,
                use_docstrings=use_docstrings, use_tags=use_tags,
                current_mode=node_modes.get(node_id, "sig")
            )
            lines.append(node_line)
        lines.append("")
        
        # Skeletons Section
        lines.append("SKELS")
        for node in sorted(nodes, key=lambda x: x["id"]):
            node_id = node["id"]
            mode = node_modes.get(node_id, "sig")
            if mode in ("skel", "excerpt", "body", "full_body"):
                node_alias = node_to_alias[node_id]
                skeleton = node.get("behavior_skeleton", {})
                if skeleton:
                    calls_str = ",".join(skeleton.get("calls", []))
                    flow_str = skeleton.get("flow", "unknown")
                    effects_str = ",".join(skeleton.get("effects", []))
                    raises_str = ",".join(skeleton.get("raises", []))
                    returns_str = skeleton.get("returns", "unknown")
                    reads_str = ",".join(skeleton.get("reads", []))
                    lines.append(f"S {node_alias} calls=[{calls_str}] flow=\"{flow_str}\" effects=[{effects_str}] raises=[{raises_str}] returns={returns_str} reads=[{reads_str}]")
        lines.append("")
        
        # Edges Section
        lines.append("EDGES")
        for edge in emitted_edges:
            edge_line = serialize_edge_compact(edge, node_to_alias)
            if edge_line:
                lines.append(edge_line)
        lines.append("")
        
        # Bodies Section
        lines.append("BODIES")
        for node in sorted(nodes, key=lambda x: x["id"]):
            node_id = node["id"]
            mode = node_modes.get(node_id, "sig")
            if mode in ("full_body", "body"):
                lines.append(f"### {node_to_alias[node_id]} {node_id}")
                lines.append((node.get("full_body") or "").rstrip())
                lines.append("")
            elif mode == "excerpt":
                lines.append(f"### {node_to_alias[node_id]} {node_id}")
                lines.append((node.get("excerpt_body") or "").rstrip())
                lines.append("")
                
        # Notes Section
        lines.append("NOTES")
        unresolved_list = [e["target"] for e in emitted_edges if not e["resolved"]]
        unresolved_uniq = list(dict.fromkeys(unresolved_list))
        unresolved_str = ",".join(unresolved_uniq) if unresolved_uniq else "none"
        lines.append(f"unresolved_symbols={unresolved_str}")
        lines.append(f"parse_errors={parse_error_count}")
        
        return "\n".join(lines).strip() + "\n"

    # First pass with placeholders
    text = build_with_tokens(99999, 0.9999)
    tokens = approximate_token_count(text)
    
    # Second pass with actual token count
    ratio = tokens / max(1, original_tokens)
    final_text = build_with_tokens(tokens, ratio)
    tokens = approximate_token_count(final_text)
    
    # Final check
    final_tokens = approximate_token_count(final_text)
    if final_tokens != tokens:
        final_ratio = final_tokens / max(1, original_tokens)
        final_text = build_with_tokens(final_tokens, final_ratio)
        final_tokens = approximate_token_count(final_text)
        
    return final_text, final_tokens


def get_exact_compact_manifest_string(
    repo_name: str,
    target_ratio: float,
    original_tokens: int,
    nodes: List[Dict[str, Any]],
    file_to_alias: Dict[str, str],
    node_to_alias: Dict[str, str],
    emitted_edges: List[Dict[str, Any]],
    resolved_edges_count: int,
    unresolved_edges_count: int,
    max_docstring_tokens: int,
    use_docstrings: bool = True,
    use_tags: bool = True,
    minimal_nodes_set: Set[str] = None,
    parse_error_count: int = 0,
    debug_edges_total: int = 0,
    status_str: str = "HIT"
) -> Tuple[str, int]:
    node_modes = {}
    for n in nodes:
        node_id = n["id"]
        if minimal_nodes_set and node_id in minimal_nodes_set:
            node_modes[node_id] = "min"
        else:
            node_modes[node_id] = n.get("mode", "sig")
            
    return get_exact_compact_manifest_string_with_modes(
        repo_name=repo_name,
        target_ratio=target_ratio,
        original_tokens=original_tokens,
        nodes=nodes,
        file_to_alias=file_to_alias,
        node_to_alias=node_to_alias,
        emitted_edges=emitted_edges,
        resolved_edges_count=resolved_edges_count,
        unresolved_edges_count=unresolved_edges_count,
        max_docstring_tokens=max_docstring_tokens,
        use_docstrings=use_docstrings,
        use_tags=use_tags,
        node_modes=node_modes,
        parse_error_count=parse_error_count,
        debug_edges_total=debug_edges_total,
        status_str=status_str
    )


# --- DEBUG JSON SERIALIZATION HELPERS ---

def get_exact_debug_json_string_and_tokens(
    repo_basename: str,
    target_ratio: float,
    original_token_count: int,
    raw_nodes: List[Dict[str, Any]],
    edges: List[Dict[str, Any]],
    warnings: List[str],
    parse_error_count: int,
    skipped_file_count: int,
    use_compact_tokens: Optional[int] = None,
    budget_status: str = "UNKNOWN"
) -> Tuple[str, int, float]:
    """Generate the exact verbose debug JSON manifest and compute its token count if requested."""
    resolved_count = sum(1 for e in edges if e["resolved"])
    unresolved_count = len(edges) - resolved_count
    v_len = len(raw_nodes)
    possible_edges = v_len * (v_len - 1) if v_len > 1 else 1
    graph_density = round(len(edges) / possible_edges, 5)
    
    if use_compact_tokens is not None:
        comp_tokens = use_compact_tokens
        comp_ratio = comp_tokens / max(1, original_token_count)
        
        metadata = {
            "repo_path": repo_basename,
            "target_ratio": target_ratio,
            "original_tokens": original_token_count,
            "compressed_tokens": comp_tokens,
            "compression_ratio": round(comp_ratio, 4),
            "token_savings": round(1.0 - comp_ratio, 4),
            "budget_status": budget_status,
            "node_count": len(raw_nodes),
            "edge_count": len(edges),
            "resolved_edge_count": resolved_count,
            "unresolved_edge_count": unresolved_count,
            "graph_density": graph_density,
            "full_body_nodes": sum(1 for n in raw_nodes if n["mode"] in ("full_body", "body")),
            "excerpt_nodes": sum(1 for n in raw_nodes if n["mode"] == "excerpt"),
            "skeleton_nodes": sum(1 for n in raw_nodes if n["mode"] == "skel"),
            "signature_only_nodes": sum(1 for n in raw_nodes if n["mode"] in ("signature_only", "sig")),
            "minimal_nodes": sum(1 for n in raw_nodes if n["mode"] in ("minimal", "min", "ultra_min")),
            "parse_error_count": parse_error_count,
            "skipped_file_count": skipped_file_count
        }
        
        manifest_nodes = []
        for node in raw_nodes:
            node_out = {
                "id": node["id"],
                "type": node["type"],
                "name": node["name"],
                "qualified_name": node["qualified_name"],
                "file": node["file"],
                "start_line": node["start_line"],
                "end_line": node["end_line"],
                "signature": node["signature"],
                "docstring": node["docstring"],
                "token_count": node["token_count"],
                "signature_token_count": node["signature_token_count"],
                "in_degree": node["in_degree"],
                "out_degree": node["out_degree"],
                "score": node["score"],
                "value_density": node["value_density"],
                "is_public": node["is_public"],
                "has_docstring": node["has_docstring"],
                "has_type_annotations": node["has_type_annotations"],
                "calls": node["calls"],
                "imports": node["imports"],
                "base_classes": node["base_classes"],
                "mode": node["mode"],
                "tags": node.get("tags", []),
                "behavior_skeleton": node.get("behavior_skeleton", {}),
                "excerpt_body": node.get("excerpt_body", "")
            }
            if node["mode"] in ("full_body", "body"):
                node_out["body"] = node["full_body"]
            manifest_nodes.append(node_out)
            
        manifest_nodes.sort(key=lambda x: x["id"])
        sorted_edges = sorted(edges, key=lambda x: (x["source"], x["target"], x["type"]))
        
        manifest_json = {
            "metadata": metadata,
            "nodes": manifest_nodes,
            "edges": sorted_edges,
            "warnings": warnings
        }
        
        json_str = json.dumps(manifest_json, indent=2)
        return json_str, comp_tokens, comp_ratio
    else:
        # We need to find the exact token count of the serialized JSON
        placeholder_tokens = 99999
        for _ in range(3):
            metadata = {
                "repo_path": repo_basename,
                "target_ratio": target_ratio,
                "original_tokens": original_token_count,
                "compressed_tokens": placeholder_tokens,
                "compression_ratio": round(placeholder_tokens / max(1, original_token_count), 4),
                "token_savings": round(1.0 - (placeholder_tokens / max(1, original_token_count)), 4),
                "budget_status": budget_status,
                "node_count": len(raw_nodes),
                "edge_count": len(edges),
                "resolved_edge_count": resolved_count,
                "unresolved_edge_count": unresolved_count,
                "graph_density": graph_density,
                "full_body_nodes": sum(1 for n in raw_nodes if n["mode"] in ("full_body", "body")),
                "excerpt_nodes": sum(1 for n in raw_nodes if n["mode"] == "excerpt"),
                "skeleton_nodes": sum(1 for n in raw_nodes if n["mode"] == "skel"),
                "signature_only_nodes": sum(1 for n in raw_nodes if n["mode"] in ("signature_only", "sig")),
                "minimal_nodes": sum(1 for n in raw_nodes if n["mode"] in ("minimal", "min", "ultra_min")),
                "parse_error_count": parse_error_count,
                "skipped_file_count": skipped_file_count
            }
            
            manifest_nodes = []
            for node in raw_nodes:
                node_out = {
                    "id": node["id"],
                    "type": node["type"],
                    "name": node["name"],
                    "qualified_name": node["qualified_name"],
                    "file": node["file"],
                    "start_line": node["start_line"],
                    "end_line": node["end_line"],
                    "signature": node["signature"],
                    "docstring": node["docstring"],
                    "token_count": node["token_count"],
                    "signature_token_count": node["signature_token_count"],
                    "in_degree": node["in_degree"],
                    "out_degree": node["out_degree"],
                    "score": node["score"],
                    "value_density": node["value_density"],
                    "is_public": node["is_public"],
                    "has_docstring": node["has_docstring"],
                    "has_type_annotations": node["has_type_annotations"],
                    "calls": node["calls"],
                    "imports": node["imports"],
                    "base_classes": node["base_classes"],
                    "mode": node["mode"],
                    "tags": node.get("tags", []),
                    "behavior_skeleton": node.get("behavior_skeleton", {}),
                    "excerpt_body": node.get("excerpt_body", "")
                }
                if node["mode"] in ("full_body", "body"):
                    node_out["body"] = node["full_body"]
                manifest_nodes.append(node_out)
                
            manifest_nodes.sort(key=lambda x: x["id"])
            sorted_edges = sorted(edges, key=lambda x: (x["source"], x["target"], x["type"]))
            
            manifest_json = {
                "metadata": metadata,
                "nodes": manifest_nodes,
                "edges": sorted_edges,
                "warnings": warnings
            }
            
            json_str = json.dumps(manifest_json, indent=2)
            new_tokens = approximate_token_count(json_str)
            if new_tokens == placeholder_tokens:
                break
            placeholder_tokens = new_tokens
            
        comp_ratio = placeholder_tokens / max(1, original_token_count)
        return json_str, placeholder_tokens, comp_ratio


# --- CORE GRAPH COMPILER ---

def compile_codebase(args: argparse.Namespace) -> None:
    """Scan and analyze a repository, build a dependency graph, and optimize under budget."""
    repo_dir = os.path.abspath(args.repo)
    if not os.path.exists(repo_dir):
        print(f"Error: Repository directory '{repo_dir}' does not exist.", file=sys.stderr)
        sys.exit(1)

    exclude_dirs = {
        ".git", "__pycache__", ".venv", "venv", "env", "node_modules",
        "dist", "build", ".mypy_cache", ".pytest_cache", ".ruff_cache",
        ".next", "target"
    }

    raw_nodes: List[Dict[str, Any]] = []
    warnings: List[str] = []
    parse_error_count = 0
    skipped_file_count = 0

    # 1. Walk Repository and parse files
    for root, dirs, files in os.walk(repo_dir):
        dirs[:] = [d for d in dirs if d not in exclude_dirs]
        for file in files:
            if file.endswith(".py"):
                filepath = os.path.join(root, file)
                before_warn_len = len(warnings)
                file_nodes = parse_file(filepath, repo_dir, warnings)
                
                if len(warnings) > before_warn_len:
                    last_warn = warnings[-1]
                    if "Parse error" in last_warn:
                        parse_error_count += 1
                    else:
                        skipped_file_count += 1

                raw_nodes.extend(file_nodes)

    if not raw_nodes:
        print("Warning: No python files or nodes successfully extracted.", file=sys.stderr)

    # 2. Build Symbol Tables
    fqn_to_node_id: Dict[str, str] = {}
    name_to_node_ids: Dict[str, List[str]] = {}
    file_to_module: Dict[str, str] = {}
    nodes_by_id: Dict[str, Dict[str, Any]] = {}

    for node in raw_nodes:
        nodes_by_id[node["id"]] = node
        
        rel_path = node["file"]
        if rel_path.endswith("__init__.py"):
            if rel_path == "__init__.py":
                module_name = ""
            else:
                module_name = rel_path[:-12].replace('/', '.')
        else:
            module_name = rel_path[:-3].replace('/', '.')
            
        file_to_module[rel_path] = module_name

        node_type = node["type"]
        name = node["name"]
        
        if node_type == "module":
            fqn = module_name
        elif node_type == "class":
            fqn = f"{module_name}.{name}" if module_name else name
        elif node_type in ("method", "async_method"):
            fqn = f"{module_name}.{node['qualified_name']}" if module_name else node["qualified_name"]
        elif node_type in ("function", "async_function"):
            fqn = f"{module_name}.{name}" if module_name else name
        else:
            fqn = name

        node["fully_qualified_name"] = fqn
        fqn_to_node_id[fqn] = node["id"]
        
        if name not in name_to_node_ids:
            name_to_node_ids[name] = []
        name_to_node_ids[name].append(node["id"])

    # 3. Assign Tags & Metadata BEFORE Scoring
    for node in raw_nodes:
        node["tags"] = assign_tags_and_metadata(node)
        for dec in node.get("decorators", []):
            dec_name = dec["name"] or ""
            if "dataclass" in dec_name.lower():
                if "schema" not in node["tags"]:
                    node["tags"].append("schema")
                if "model" not in node["tags"]:
                    node["tags"].append("model")
        node["tags"] = sorted(list(set(node["tags"])))

    # 4. Resolve Dependency Edges
    edges: List[Dict[str, Any]] = []
    edges_seen: Set[Tuple[str, str, str]] = set()

    def add_edge(src: str, target_val: str, edge_type: str, raw_sym: str, resolved: bool) -> None:
        edge_key = (src, target_val, edge_type)
        if edge_key not in edges_seen:
            edges_seen.add(edge_key)
            classification = "resolved"
            if not resolved:
                src_node = nodes_by_id.get(src)
                imports = src_node.get("imports", []) if src_node else []
                classification = classify_unresolved_symbol(target_val, imports)
            edges.append({
                "source": src,
                "target": target_val,
                "type": edge_type,
                "raw_symbol": raw_sym,
                "resolved": resolved,
                "classification": classification
            })

    # Helper function to resolve a symbol inside a specific file scope
    def resolve_symbol(symbol: str, file_path: str, source_node: Optional[Dict[str, Any]] = None) -> Tuple[Optional[str], bool]:
        if not symbol:
            return None, False

        curr_module = file_to_module.get(file_path, "")

        # A. Local check (local package/module definitions)
        local_fqn = f"{curr_module}.{symbol}" if curr_module else symbol
        if local_fqn in fqn_to_node_id:
            return fqn_to_node_id[local_fqn], True

        # B. Class-level / Self/Cls prefix resolution helper
        if symbol.startswith("self.") or symbol.startswith("cls."):
            prefix_len = 5 if symbol.startswith("self.") else 4
            suffix = symbol[prefix_len:]
            if source_node and source_node["type"] in ("method", "async_method"):
                parts = source_node["qualified_name"].split(".")
                if len(parts) >= 1:
                    class_name = parts[0]
                    class_fqn = f"{curr_module}.{class_name}" if curr_module else class_name
                    method_fqn = f"{class_fqn}.{suffix}"
                    if method_fqn in fqn_to_node_id:
                        return fqn_to_node_id[method_fqn], True

        # C. Dot-separated resolution (methods on local variables, static class calls, module.function)
        if "." in symbol and not symbol.startswith("self."):
            parts = symbol.split(".")
            obj_name = parts[0]
            attr_name = ".".join(parts[1:])
            
            # Check if obj_name is a local variable with a type annotation
            if source_node and "local_types" in source_node and obj_name in source_node["local_types"]:
                class_type = source_node["local_types"][obj_name]
                resolved_class_id, resolved = resolve_symbol(class_type, file_path, source_node)
                if resolved and resolved_class_id:
                    class_base = resolved_class_id.split("::")[0]
                    class_short = resolved_class_id.split("::")[1] if "::" in resolved_class_id else ""
                    if class_short and class_short != "<module>":
                        target_id = f"{class_base}::{class_short}.{attr_name}"
                        if target_id in nodes_by_id:
                            return target_id, True
            
            # Check if obj_name is a class name defined or imported in this file
            resolved_obj_id, resolved = resolve_symbol(obj_name, file_path, source_node)
            if resolved and resolved_obj_id:
                obj_base = resolved_obj_id.split("::")[0]
                obj_short = resolved_obj_id.split("::")[1] if "::" in resolved_obj_id else ""
                
                if obj_short and obj_short != "<module>":
                    target_id = f"{obj_base}::{obj_short}.{attr_name}"
                    if target_id in nodes_by_id:
                        return target_id, True
                elif obj_short == "<module>":
                    target_id = f"{obj_base}::{attr_name}"
                    if target_id in nodes_by_id:
                        return target_id, True

        # D. Import checks (using the robust resolver)
        module_id = f"{file_path}::<module>"
        module_node = nodes_by_id.get(module_id)
        if module_node:
            for imp in module_node.get("imports", []):
                imp_name = imp["name"]
                imp_module = imp["module"]
                imp_alias = imp["alias"]
                imp_type = imp["type"]

                if imp_type == "from_import":
                    local_name = imp_alias if imp_alias else imp_name
                    if symbol == local_name:
                        target_fqn = f"{imp_module}.{imp_name}" if imp_module else imp_name
                        if target_fqn in fqn_to_node_id:
                            return fqn_to_node_id[target_fqn], True
                        if imp_module in fqn_to_node_id:
                            return fqn_to_node_id[imp_module], True
                    elif symbol.startswith(local_name + "."):
                        suffix = symbol[len(local_name)+1:]
                        target_fqn = f"{imp_module}.{imp_name}.{suffix}" if imp_module else f"{imp_name}.{suffix}"
                        if target_fqn in fqn_to_node_id:
                            return fqn_to_node_id[target_fqn], True
                        target_fqn = f"{imp_module}.{suffix}" if imp_module else suffix
                        if target_fqn in fqn_to_node_id:
                            return fqn_to_node_id[target_fqn], True

                elif imp_type == "import":
                    if imp_alias:
                        local_name = imp_alias
                        if symbol == local_name:
                            if imp_module in fqn_to_node_id:
                                return fqn_to_node_id[imp_module], True
                        elif symbol.startswith(local_name + "."):
                            suffix = symbol[len(local_name)+1:]
                            target_fqn = f"{imp_module}.{suffix}"
                            if target_fqn in fqn_to_node_id:
                                return fqn_to_node_id[target_fqn], True
                    else:
                        local_name = imp_name
                        if symbol == local_name:
                            if imp_module in fqn_to_node_id:
                                return fqn_to_node_id[imp_module], True
                        elif symbol.startswith(local_name + "."):
                            suffix = symbol[len(local_name)+1:]
                            target_fqn = f"{imp_name}.{suffix}"
                            if target_fqn in fqn_to_node_id:
                                return fqn_to_node_id[target_fqn], True
                            target_fqn = f"{imp_module}.{suffix}"
                            if target_fqn in fqn_to_node_id:
                                return fqn_to_node_id[target_fqn], True

        # E. Global Fallback search by Name / Attribute suffix
        name_to_search = symbol.split(".")[-1]
        if name_to_search in name_to_node_ids:
            return name_to_node_ids[name_to_search][0], True

        return symbol, False

    # Process each node to generate edges
    for node in raw_nodes:
        node_id = node["id"]
        file_path = node["file"]

        # A. Import edges
        for imp in node.get("imports", []):
            imp_module = imp["module"]
            imp_name = imp["name"]
            
            fqn_target = f"{imp_module}.{imp_name}" if imp_module else imp_name
            if fqn_target in fqn_to_node_id:
                add_edge(node_id, fqn_to_node_id[fqn_target], "import", fqn_target, True)
            elif imp_module in fqn_to_node_id:
                add_edge(node_id, fqn_to_node_id[imp_module], "import", imp_module, True)
            else:
                add_edge(node_id, fqn_target, "import", fqn_target, False)

        # B. Class Inheritance edges
        for base in node.get("base_classes", []):
            target_id, resolved = resolve_symbol(base, file_path, node)
            add_edge(node_id, target_id or base, "inheritance", base, resolved)

        # C. Call edges
        for call in node.get("calls", []):
            is_route_dec = False
            for dec in node.get("decorators", []):
                if dec["name"] == call:
                    is_route_dec = True
                    break
            edge_type = "route" if is_route_dec else "call"
            target_id, resolved = resolve_symbol(call, file_path, node)
            add_edge(node_id, target_id or call, edge_type, call, resolved)

    # 5. Compute Node Degrees
    for edge in edges:
        source_id = edge["source"]
        target_id = edge["target"]
        resolved = edge["resolved"]

        if source_id in nodes_by_id:
            nodes_by_id[source_id]["out_degree"] += 1

        if resolved and target_id in nodes_by_id:
            nodes_by_id[target_id]["in_degree"] += 1

    # 5.5 Extract Behavior Skeletons and Excerpts
    file_to_lines = {}
    for node in raw_nodes:
        if node["type"] == "module":
            file_to_lines[node["file"]] = node["full_body"].splitlines(keepends=True)

    for node in raw_nodes:
        if node["type"] in ("function", "async_function", "method", "async_method"):
            ast_node = node.get("ast_node")
            if ast_node:
                skeleton = extract_behavior_skeleton(
                    ast_node, node.get("local_types", {}), node["file"], resolve_symbol, node
                )
                node["behavior_skeleton"] = skeleton
                
                # Add skeleton effects to tags
                for eff in skeleton.get("effects", []):
                    if eff in ("db_read", "db_write"):
                        if "database" not in node["tags"]:
                            node["tags"].append("database")
                    else:
                        if eff not in node["tags"]:
                            node["tags"].append(eff)
                node["tags"] = sorted(list(set(node["tags"])))
                
                lines = file_to_lines.get(node["file"], [])
                if lines:
                    node["excerpt_body"] = generate_excerpt(ast_node, lines)
                else:
                    node["excerpt_body"] = ""

    # Clean up temporary ast_node
    for node in raw_nodes:
        if "ast_node" in node:
            node.pop("ast_node", None)

    # 6. Compute Structural Importance Scores with Practical Boosts
    for node in raw_nodes:
        in_deg = node["in_degree"]
        out_deg = node["out_degree"]
        is_pub = node["is_public"]
        has_doc = node["has_docstring"]
        has_annot = node["has_type_annotations"]
        t_full = node["token_count"]
        tags = node["tags"]

        denom = math.log(1 + max(1, t_full))
        base_score = 2 * in_deg + out_deg + 3 * is_pub + has_doc + has_annot
        
        # Boosts
        boost = 0.0
        if "route" in tags or "endpoint" in tags:
            boost += 5.0
        if is_pub:
            boost += 1.5
        if "model" in tags or "schema" in tags:
            boost += 2.0
            
        verbs = {"validate", "process", "create", "update", "delete", "checkout", "payment", "order", "user", "auth", "route", "handler"}
        name_lower = node["name"].lower()
        if any(v in name_lower for v in verbs):
            boost += 3.0
            
        # Count resolved edges connected to this node in the full graph
        resolved_count = 0
        for edge in edges:
            if edge["resolved"] and (edge["source"] == node["id"] or edge["target"] == node["id"]):
                resolved_count += 1
        boost += min(5.0, resolved_count * 1.0)
        
        score_val = (base_score + boost) / denom
        if "test" in tags:
            score_val -= 5.0
            
        node["score"] = round(score_val, 4)

        sig_tokens = approximate_token_count(node["signature"])
        doc_tokens = approximate_token_count(node["docstring"])
        node["signature_token_count"] = sig_tokens
        node["docstring_token_count"] = doc_tokens

        marginal_cost = max(1, t_full - sig_tokens + 1)
        node["value_density"] = round(node["score"] / marginal_cost, 6)

    # Convert binary flags to boolean
    for node in raw_nodes:
        node["is_public"] = bool(node["is_public"])
        node["has_docstring"] = bool(node["has_docstring"])
        node["has_type_annotations"] = bool(node["has_type_annotations"])

    # 7. Generate Alias Mapping
    unique_files = sorted(list(set(node["file"] for node in raw_nodes)))
    file_to_alias = {f_path: f"F{i}" for i, f_path in enumerate(unique_files)}
    
    sorted_raw_nodes = sorted(raw_nodes, key=lambda x: x["id"])
    node_to_alias = {node["id"]: f"N{i}" for i, node in enumerate(sorted_raw_nodes)}

    # 8. Apply Quantization Policy with Greedy Optimization & Strict Budgeting
    original_token_count = 0
    # Try to read raw file for token count of scanned files
    for root, dirs, files in os.walk(repo_dir):
        dirs[:] = [d for d in dirs if d not in exclude_dirs]
        for file in files:
            if file.endswith(".py"):
                filepath = os.path.join(root, file)
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        original_token_count += approximate_token_count(f.read())
                except Exception:
                    pass

    if original_token_count == 0:
        # Fallback to module tokens if raw scan failed
        original_token_count = sum(node["token_count"] for node in raw_nodes if node["type"] == "module") or 1

    budget_tokens = math.ceil(args.target_ratio * original_token_count)

    # Initialize all nodes to "sig" (signature_only) mode
    node_modes = {node["id"]: "sig" for node in raw_nodes}
    for node in raw_nodes:
        node["mode"] = "signature_only"

    minimal_nodes_set = set()
    use_docstrings = True
    use_tags = True
    aggressive_compaction_triggered = False

    # Filter out noisy unresolved edges
    resolved_edges_all = [e for e in edges if e["resolved"]]
    unresolved_edges_all = [e for e in edges if not e["resolved"]]
    unresolved_edges_filtered = [e for e in unresolved_edges_all if not is_noisy_symbol(e["raw_symbol"])]

    # Sort resolved and unresolved edges for selection
    node_id_to_score = {n["id"]: n["score"] for n in raw_nodes}
    resolved_edges_all.sort(key=lambda x: (-node_id_to_score.get(x["source"], 0.0), x["source"], x["target"]))
    unresolved_edges_filtered.sort(key=lambda x: (-node_id_to_score.get(x["source"], 0.0), x["source"], x["target"]))

    # Setup initial edge collection
    max_edges = args.max_edges
    max_unresolved = args.max_unresolved_edges
    
    emitted_resolved = resolved_edges_all[:max_edges]
    remaining_slots = max(0, max_edges - len(emitted_resolved))
    limit_unresolved = min(max_unresolved, remaining_slots)
    emitted_unresolved = unresolved_edges_filtered[:limit_unresolved]
    emitted_edges = emitted_resolved + emitted_unresolved
    emitted_edges.sort(key=lambda x: (x["source"], x["target"], x["type"]))

    # Pre-identify route/API nodes and their skeletons for protection
    route_nodes = [n for n in raw_nodes if "route" in n["tags"] or "endpoint" in n["tags"]]
    route_node_ids = {n["id"] for n in route_nodes}
    
    route_nodes_with_skel = [n for n in route_nodes if n.get("behavior_skeleton")]
    route_nodes_with_skel.sort(key=lambda x: -x["score"])
    top_route_ids_to_keep_skel = {n["id"] for n in route_nodes_with_skel[:5]} # Top 5 route nodes with skeletons

    route_adjacent_node_ids = set()
    for e in resolved_edges_all:
        if e["source"] in route_node_ids:
            route_adjacent_node_ids.add(e["target"])
        if e["target"] in route_node_ids:
            route_adjacent_node_ids.add(e["source"])

    # Function to get current exact manifest tokens
    def get_current_manifest_tokens(temp_modes, temp_edges, doc_flag, tag_flag, doc_max):
        _, tokens = get_exact_compact_manifest_string_with_modes(
            repo_name=os.path.basename(repo_dir),
            target_ratio=args.target_ratio,
            original_tokens=original_token_count,
            nodes=[n for n in raw_nodes if n["id"] in temp_modes],
            file_to_alias=file_to_alias,
            node_to_alias=node_to_alias,
            emitted_edges=temp_edges,
            resolved_edges_count=sum(1 for e in temp_edges if e["resolved"]),
            unresolved_edges_count=sum(1 for e in temp_edges if not e["resolved"]),
            max_docstring_tokens=doc_max,
            use_docstrings=doc_flag,
            use_tags=tag_flag,
            node_modes=temp_modes,
            parse_error_count=parse_error_count,
            debug_edges_total=len(edges),
            status_str="HIT"
        )
        return tokens

    current_tokens = get_current_manifest_tokens(
        node_modes, emitted_edges, use_docstrings, use_tags, args.max_docstring_tokens
    )

    if current_tokens <= budget_tokens:
        # ROOM AVAILABLE -> PROMOTE NODES!
        # Sort non-module nodes by score desc
        sorted_nodes_greedy = sorted(
            [n for n in raw_nodes if n["type"] != "module"],
            key=lambda x: (-x["score"], x["id"])
        )
        
        # Stage 1: Promote important functions/methods from "sig" to "skel"
        for node in sorted_nodes_greedy:
            if node["type"] in ("function", "async_function", "method", "async_method"):
                prev_mode = node_modes[node["id"]]
                node_modes[node["id"]] = "skel"
                test_tokens = get_current_manifest_tokens(
                    node_modes, emitted_edges, use_docstrings, use_tags, args.max_docstring_tokens
                )
                if test_tokens <= budget_tokens:
                    current_tokens = test_tokens
                else:
                    node_modes[node["id"]] = prev_mode
                    
        # Stage 2: Promote very important nodes to "excerpt" or "body" (under budget and max limit)
        full_body_nodes_retained_count = 0
        for node in sorted_nodes_greedy:
            if full_body_nodes_retained_count >= args.max_full_body_nodes:
                break
                
            node_id = node["id"]
            prev_mode = node_modes[node_id]
            
            # Determine candidate: "body" for short nodes, "excerpt" for longer nodes
            body_tokens = node["token_count"]
            candidate_mode = "body" if body_tokens <= 120 else "excerpt"
            
            node_modes[node_id] = candidate_mode
            test_tokens = get_current_manifest_tokens(
                node_modes, emitted_edges, use_docstrings, use_tags, args.max_docstring_tokens
            )
            
            if test_tokens <= budget_tokens:
                current_tokens = test_tokens
                full_body_nodes_retained_count += 1
            else:
                node_modes[node_id] = prev_mode
                
        # Handle min full body node retention constraints (if budget has a little tolerance)
        if full_body_nodes_retained_count < args.min_full_body_nodes:
            tolerance_budget = budget_tokens + math.ceil(0.05 * original_token_count)
            for node in sorted_nodes_greedy:
                if full_body_nodes_retained_count >= args.min_full_body_nodes:
                    break
                node_id = node["id"]
                if node_modes[node_id] in ("body", "excerpt"):
                    continue
                    
                prev_mode = node_modes[node_id]
                body_tokens = node["token_count"]
                candidate_mode = "body" if body_tokens <= 120 else "excerpt"
                
                node_modes[node_id] = candidate_mode
                test_tokens = get_current_manifest_tokens(
                    node_modes, emitted_edges, use_docstrings, use_tags, args.max_docstring_tokens
                )
                if test_tokens <= tolerance_budget:
                    current_tokens = test_tokens
                    full_body_nodes_retained_count += 1
                else:
                    node_modes[node_id] = prev_mode
    else:
        # BUDGET EXCEEDED -> AGGRESSIVE COMPACTION!
        aggressive_compaction_triggered = True
        warnings.append("signature baseline exceeded budget; aggressive compaction enabled")
        
        # Stage 1: Remove docstrings
        use_docstrings = False
        current_tokens = get_current_manifest_tokens(
            node_modes, emitted_edges, False, use_tags, 0
        )
        
        # Stage 2: Drop all unresolved edges EXCEPT framework route edges
        if current_tokens > budget_tokens:
            emitted_unresolved = [e for e in emitted_unresolved if e["type"] == "route" or e["target"].startswith("EXT:")]
            emitted_edges = emitted_resolved + emitted_unresolved
            emitted_edges.sort(key=lambda x: (x["source"], x["target"], x["type"]))
            current_tokens = get_current_manifest_tokens(
                node_modes, emitted_edges, False, use_tags, 0
            )
            
        # Stage 3: Cap resolved edges to at most 15, prioritizing route-adjacent resolved edges and maintaining a minimum of 10 if possible
        if current_tokens > budget_tokens:
            adjacent_resolved = [e for e in resolved_edges_all if e["source"] in route_node_ids or e["target"] in route_node_ids]
            protected_resolved = list(adjacent_resolved)
            for e in resolved_edges_all:
                if len(protected_resolved) >= 15:
                    break
                if e not in protected_resolved:
                    protected_resolved.append(e)
            
            target_cap = max(10, min(15, len(protected_resolved)))
            emitted_resolved = protected_resolved[:target_cap]
            emitted_edges = emitted_resolved + emitted_unresolved
            emitted_edges.sort(key=lambda x: (x["source"], x["target"], x["type"]))
            current_tokens = get_current_manifest_tokens(
                node_modes, emitted_edges, False, use_tags, 0
            )
            
        # Stage 4: Downgrade lowest-scoring non-module nodes to "min" (Protect route/API nodes)
        if current_tokens > budget_tokens:
            sorted_by_score_asc = sorted(
                [n for n in raw_nodes if n["type"] != "module"],
                key=lambda x: x["score"]
            )
            for node in sorted_by_score_asc:
                if current_tokens <= budget_tokens:
                    break
                node_id = node["id"]
                if node_id in route_node_ids:
                    # Never downgrade route/API nodes below "sig"
                    # Keep top route/API nodes in "skel" if they are in top_route_ids_to_keep_skel
                    if node_id in top_route_ids_to_keep_skel:
                        node_modes[node_id] = "skel"
                    else:
                        node_modes[node_id] = "sig"
                    continue
                    
                node_modes[node_id] = "min"
                minimal_nodes_set.add(node_id)
                current_tokens = get_current_manifest_tokens(
                    node_modes, emitted_edges, False, use_tags, 0
                )
                
        # Stage 5: Drop lowest-scoring unimportant (non-route/non-endpoint/non-adjacent) nodes entirely from manifest!
        if current_tokens > budget_tokens:
            protected_node_ids = route_node_ids.union(route_adjacent_node_ids)
            candidates_for_dropping = sorted(
                [n for n in raw_nodes if n["type"] != "module" and n["id"] not in protected_node_ids],
                key=lambda x: x["score"]
            )
            dropped_node_ids = set()
            for node in candidates_for_dropping:
                if current_tokens <= budget_tokens:
                    break
                
                temp_dropped = dropped_node_ids.union({node["id"]})
                temp_modes = {nid: m for nid, m in node_modes.items() if nid not in temp_dropped}
                temp_edges = [e for e in emitted_edges if e["source"] not in temp_dropped and e["target"] not in temp_dropped]
                
                # Enforce the utility edge floor for non-trivial repos
                if len(edges) >= 10 and len(temp_edges) < 8:
                    break
                
                dropped_node_ids.add(node["id"])
                node_modes = temp_modes
                emitted_edges = temp_edges
                current_tokens = get_current_manifest_tokens(
                    node_modes, emitted_edges, False, use_tags, 0
                )
                
            # Filter raw_nodes to exclude dropped ones
            raw_nodes = [n for n in raw_nodes if n["id"] in node_modes]
            for d_id in dropped_node_ids:
                if d_id in minimal_nodes_set:
                    minimal_nodes_set.remove(d_id)
                    
        # Stage 6: Turn off tags if still over budget
        if current_tokens > budget_tokens:
            use_tags = False
            current_tokens = get_current_manifest_tokens(
                node_modes, emitted_edges, False, False, 0
            )
            
        # Stage 7: Downgrade lowest-scoring module nodes to "min" if still over budget
        if current_tokens > budget_tokens:
            module_nodes = sorted(
                [n for n in raw_nodes if n["type"] == "module"],
                key=lambda x: x["score"]
            )
            for node in module_nodes:
                if current_tokens <= budget_tokens:
                    break
                node_modes[node["id"]] = "min"
                minimal_nodes_set.add(node["id"])
                current_tokens = get_current_manifest_tokens(
                    node_modes, emitted_edges, False, False, 0
                )

    # Sync node_modes back to each node's "mode" property
    for node in raw_nodes:
        mode_val = node_modes[node["id"]]
        if mode_val == "sig":
            node["mode"] = "signature_only"
        elif mode_val == "min":
            node["mode"] = "minimal"
        else:
            node["mode"] = mode_val

    # Determine budget status prior to final compilation
    budget_status = "HIT"
    final_compression_ratio = current_tokens / max(1, original_token_count)
    if aggressive_compaction_triggered:
        if final_compression_ratio <= args.target_ratio:
            budget_status = "AGGRESSIVE_BASELINE_EXCEEDED"
        else:
            budget_status = "MINIMUM_GRAPH_EXCEEDS_TARGET"
    elif final_compression_ratio > args.target_ratio:
        budget_status = "MISSED"

    # Compile Final outputs
    compact_text = ""
    compact_tokens_count = 0
    debug_json_text = ""
    debug_tokens_count = 0
    
    # Generate Compact Manifest Text
    compact_text, compact_tokens_count = get_exact_compact_manifest_string(
        repo_name=os.path.basename(repo_dir),
        target_ratio=args.target_ratio,
        original_tokens=original_token_count,
        nodes=raw_nodes,
        file_to_alias=file_to_alias,
        node_to_alias=node_to_alias,
        emitted_edges=emitted_edges,
        resolved_edges_count=sum(1 for e in emitted_edges if e["resolved"]),
        unresolved_edges_count=sum(1 for e in emitted_edges if not e["resolved"]),
        max_docstring_tokens=args.max_docstring_tokens if not aggressive_compaction_triggered else 0,
        use_docstrings=use_docstrings,
        use_tags=use_tags,
        minimal_nodes_set=minimal_nodes_set,
        parse_error_count=parse_error_count,
        debug_edges_total=len(edges),
        status_str=budget_status
    )

    # Generate JSON Text
    if args.format == "json":
        debug_json_text, debug_tokens_count, debug_ratio = get_exact_debug_json_string_and_tokens(
            repo_basename=os.path.basename(repo_dir),
            target_ratio=args.target_ratio,
            original_token_count=original_token_count,
            raw_nodes=raw_nodes,
            edges=edges,
            warnings=warnings,
            parse_error_count=parse_error_count,
            skipped_file_count=skipped_file_count,
            use_compact_tokens=None,
            budget_status=budget_status
        )
        final_compressed_tokens = debug_tokens_count
        final_compression_ratio = debug_ratio
    else:
        final_compressed_tokens = compact_tokens_count
        final_compression_ratio = compact_tokens_count / max(1, original_token_count)
        
        debug_json_text, _, _ = get_exact_debug_json_string_and_tokens(
            repo_basename=os.path.basename(repo_dir),
            target_ratio=args.target_ratio,
            original_token_count=original_token_count,
            raw_nodes=raw_nodes,
            edges=edges,
            warnings=warnings,
            parse_error_count=parse_error_count,
            skipped_file_count=skipped_file_count,
            use_compact_tokens=compact_tokens_count,
            budget_status=budget_status
        )

    # Write Output Files
    try:
        if args.format == "compact":
            with open(args.out, "w", encoding="utf-8") as f:
                f.write(compact_text)
        elif args.format == "json":
            with open(args.out, "w", encoding="utf-8") as f:
                f.write(debug_json_text)
        elif args.format == "both":
            with open(args.out, "w", encoding="utf-8") as f:
                f.write(compact_text)
            with open(args.debug_out, "w", encoding="utf-8") as f:
                f.write(debug_json_text)
    except Exception as e:
        print(f"Error: Failed to write output manifest: {e}", file=sys.stderr)
        sys.exit(1)

    # 10. Print Stdout Summary (TASK 6)
    print("Context Compiler Quantizer Summary")
    print("----------------------------------")
    print(f"Repository: {os.path.basename(repo_dir)}")
    print(f"Original tokens: {original_token_count}")
    print(f"Compressed tokens: {final_compressed_tokens}")
    print(f"Compression ratio: {final_compression_ratio:.3f}")
    print(f"Token savings: {round(1.0 - final_compression_ratio, 4) * 100:.1f}%")
    print(f"Target ratio: {args.target_ratio:.3f}")
    print(f"Budget status: {budget_status}")
    print()
    print("Graph Summary")
    print("-------------")
    print(f"Files: {len(file_to_alias)}")
    print(f"Nodes: {len(raw_nodes)}")
    print(f"Debug edges total: {len(edges)}")
    print(f"Serialized edges total: {len(emitted_edges)}")
    print(f"Serialized resolved edges: {sum(1 for e in emitted_edges if e['resolved'])}")
    print(f"Serialized unresolved edges: {sum(1 for e in emitted_edges if not e['resolved'])}")
    total_edges = len(edges)
    resolved_total_edges = sum(1 for e in edges if e["resolved"])
    resolved_rate_pct = (resolved_total_edges / max(1, total_edges)) * 100
    print(f"Resolved edge rate: {resolved_rate_pct:.1f}%")
    v_len = len(raw_nodes)
    possible_edges = v_len * (v_len - 1) if v_len > 1 else 1
    print(f"Graph density: {len(edges) / possible_edges:.5f}")
    print(f"Full-body nodes: {sum(1 for n in raw_nodes if n['mode'] in ('full_body', 'body'))}")
    print(f"Excerpt nodes: {sum(1 for n in raw_nodes if n['mode'] == 'excerpt')}")
    print(f"Skeleton nodes: {sum(1 for n in raw_nodes if n['mode'] == 'skel')}")
    print(f"Signature-only nodes: {sum(1 for n in raw_nodes if n['mode'] in ('signature_only', 'sig'))}")
    print(f"Ultra-minimal nodes: {sum(1 for n in raw_nodes if n['mode'] in ('minimal', 'min'))}")
    print()
    print("Top retained body/excerpt nodes")
    print("-------------------------------")
    top_retained = sorted(
        [n for n in raw_nodes if n["mode"] in ("full_body", "body", "excerpt")],
        key=lambda x: -x["score"]
    )[:5]
    if not top_retained:
        top_retained = sorted(
            [n for n in raw_nodes if n["type"] != "module"],
            key=lambda x: -x["score"]
        )[:5]
    for i, node in enumerate(top_retained, 1):
        alias = node_to_alias.get(node["id"], "N/A")
        print(f"{i}. {alias} {node['file']}:{node['start_line']}-{node['end_line']} {node['type']} {node['qualified_name']} (Score: {node['score']:.2f})")
    print()
    print("Top skeleton nodes")
    print("------------------")
    top_skel = sorted(
        [n for n in raw_nodes if n["mode"] == "skel"],
        key=lambda x: -x["score"]
    )[:5]
    for i, node in enumerate(top_skel, 1):
        alias = node_to_alias.get(node["id"], "N/A")
        print(f"{i}. {alias} {node['file']}:{node['start_line']}-{node['end_line']} {node['type']} {node['qualified_name']} (Score: {node['score']:.2f})")
    if not top_skel:
        print("None found")
    print()
    print("Top route/API nodes")
    print("-------------------")
    route_nodes_sorted = sorted(
        [n for n in raw_nodes if "route" in n["tags"] or "endpoint" in n["tags"]],
        key=lambda x: -x["score"]
    )[:5]
    for i, node in enumerate(route_nodes_sorted, 1):
        alias = node_to_alias.get(node["id"], "N/A")
        print(f"{i}. {alias} {node['file']}:{node['start_line']}-{node['end_line']} {node['type']} {node['qualified_name']} (Score: {node['score']:.2f})")
    if not route_nodes_sorted:
        print("None found")
    print()
    print("Top unresolved external symbols")
    print("-------------------------------")
    unresolved_counts = Counter(e["target"] for e in edges if not e["resolved"])
    top_unresolved = sorted(unresolved_counts.items(), key=lambda x: (-x[1], x[0]))[:5]
    for i, (symbol, count) in enumerate(top_unresolved, 1):
        print(f"{i}. {symbol} (referenced {count} times)")
    if not top_unresolved:
        print("None found")

    # Target warning guidance if low target causes severe minimization
    non_module_useful_modes = sum(1 for n in raw_nodes if n["type"] != "module" and n["mode"] not in ("minimal", "min", "ultra_min"))
    if args.target_ratio <= 0.20 and non_module_useful_modes == 0:
        print(f"\nTarget ratio {args.target_ratio:.2f} is below the minimum useful graph size for this repo; try 0.25 or 0.30 for demo-quality context.")

    if warnings:
        print()
        print("Warnings")
        print("--------")
        for warn in warnings:
            print(f"- {warn}")


if __name__ == "__main__":
    cli_args = parse_args()
    compile_codebase(cli_args)
