import re
import os
import json
from typing import Dict, List, Any, Optional

class ManifestParser:
    def __init__(self, txt_path: str, json_path: Optional[str] = None):
        self.txt_path = txt_path
        self.json_path = json_path
        self.data = self.parse_txt(txt_path)
        self.metadata = self.data.get("metadata", {})
        self.files = self.data.get("files", {})
        self.file_to_alias = self.data.get("file_to_alias", {})
        self.nodes_map = self.data.get("nodes_map", {})
        self.edges_raw = self.data.get("edges", [])
        self.unresolved_symbols = self.data.get("unresolved_symbols", [])
        self.parse_errors = self.data.get("parse_errors", 0)
        
        # Enrich and unify with debug JSON if it exists
        if json_path and os.path.exists(json_path):
            self.debug_data = self.load_debug_json(json_path)
            self._merge_debug_data()
        else:
            self.debug_data = {}
            
        self.nodes = list(self.nodes_map.values())
        self.edges = self._enrich_edges(self.edges_raw)

    def _merge_debug_data(self):
        """
        Merges rich metadata from codebase_manifest.debug.json into parsed compact-manifest nodes.
        """
        debug_nodes = self.debug_data.get("nodes", [])
        # Build mapping from file + start_line + name -> node alias
        # and from ID -> node alias
        lookup = {}
        for alias, node in self.nodes_map.items():
            key = (node["file"], node["start_line"], node["name"])
            lookup[key] = alias
            lookup[node["id"]] = alias

        for d_node in debug_nodes:
            alias = None
            if d_node.get("id") in lookup:
                alias = lookup[d_node["id"]]
            else:
                key = (d_node.get("file"), d_node.get("start_line"), d_node.get("name"))
                alias = lookup.get(key)
                
            if alias and alias in self.nodes_map:
                node = self.nodes_map[alias]
                node["token_count"] = d_node.get("token_count", node.get("token_count", 0))
                node["signature_token_count"] = d_node.get("signature_token_count", 0)
                node["value_density"] = d_node.get("value_density", 0.0)
                node["is_public"] = d_node.get("is_public", True)
                node["calls"] = d_node.get("calls", node.get("calls", []))
                node["imports"] = d_node.get("imports", node.get("imports", []))
                node["base_classes"] = d_node.get("base_classes", [])
                
                # If skeleton is more descriptive
                if d_node.get("behavior_skeleton") and not node.get("behavior_skeleton"):
                    node["behavior_skeleton"] = d_node["behavior_skeleton"]
                # If body is not in text but present in json (some times full body is in debug json)
                if d_node.get("full_body") and not node.get("body"):
                    node["body"] = d_node["full_body"]

    def _enrich_edges(self, edges_list: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Enriches raw edge records with resolved source/target names, symbols, and resolved flags.
        """
        enriched = []
        for edge in edges_list:
            src_alias = edge["source"]
            dst_alias = edge["target"]
            edge_type = edge["type"]
            relation = edge["relation"]
            status = edge["status"]
            
            resolved = (status == "resolved")
            symbol = "unknown"
            if dst_alias.startswith("EXT:"):
                symbol = dst_alias[4:]
                resolved = False
            else:
                tgt_node = self.nodes_map.get(dst_alias)
                if tgt_node:
                    symbol = tgt_node.get("name", dst_alias)
                    resolved = True
                    
            src_node = self.nodes_map.get(src_alias)
            src_name = src_node.get("name", src_alias) if src_node else src_alias
            tgt_node = self.nodes_map.get(dst_alias)
            tgt_name = tgt_node.get("name", dst_alias) if tgt_node else dst_alias
            
            enriched.append({
                "source": src_alias,
                "target": dst_alias,
                "type": edge_type,
                "relation": relation,
                "status": status,
                "resolved": resolved,
                "symbol": symbol,
                "source_name": src_name,
                "target_name": tgt_name
            })
        return enriched

    @staticmethod
    def parse_txt(path: str) -> Dict[str, Any]:
        """
        Parses a compact codebase_manifest.txt and returns its structured components.
        """
        metadata = {}
        files = {}
        file_to_alias = {}
        nodes_map = {} # node_alias -> node dict
        edges = []
        unresolved_symbols = []
        parse_errors = 0
        
        current_section = None
        
        # Temp storage for skeletons and bodies
        skeletons = {} # node_alias -> skel_dict
        bodies = {} # node_alias -> body_string
        
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()
            
        i = 0
        while i < len(lines):
            line = lines[i]
            line_strip = line.strip()
            
            if not line_strip:
                i += 1
                continue
                
            if line_strip.startswith("#"):
                i += 1
                continue
                
            if line_strip.startswith("META "):
                # Parse metadata
                meta_parts = re.findall(r'(\w+)=(?:"([^"]*)"|(\S+))', line_strip[5:])
                for k, v1, v2 in meta_parts:
                    val = v1 if v1 else v2
                    # try convert to number
                    try:
                        if "." in val:
                            val = float(val)
                        else:
                            val = int(val)
                    except ValueError:
                        pass
                    metadata[k] = val
                i += 1
                continue
                
            if line_strip in ("FILES", "NODES", "SKELS", "EDGES", "BODIES", "NOTES"):
                current_section = line_strip
                i += 1
                continue
                
            if current_section == "FILES":
                # Format: F0 path/to/file
                match = re.match(r"^(F\d+)\s+(.+)$", line_strip)
                if match:
                    alias, f_path = match.groups()
                    files[alias] = f_path
                    file_to_alias[f_path] = alias
                i += 1
                continue
                
            elif current_section == "NODES":
                # Format: N0 F0:1-5 type name attrs
                parts = line_strip.split(" ", 4)
                if len(parts) >= 4:
                    node_alias = parts[0]
                    file_range = parts[1] # e.g. F0:1-5
                    node_type = parts[2]
                    node_name = parts[3]
                    attrs_str = parts[4] if len(parts) > 4 else ""
                    
                    # Parse file alias and line ranges
                    file_alias = file_range.split(":")[0]
                    lines_range = file_range.split(":")[1] if ":" in file_range else "0-0"
                    start_line, end_line = 0, 0
                    if "-" in lines_range:
                        try:
                            start_line, end_line = map(int, lines_range.split("-"))
                        except ValueError:
                            pass
                            
                    # Parse attributes
                    attrs = {}
                    attr_parts = re.findall(r'(\w+)=(?:"([^"]*)"|(\S+))', attrs_str)
                    for k, v1, v2 in attr_parts:
                        attrs[k] = v1 if v1 else v2
                        
                    sig = attrs.get("sig", f"{node_type} {node_name}")
                    doc = attrs.get("doc", "")
                    tags_list = attrs.get("tags", "").split(",") if attrs.get("tags") else []
                    
                    try:
                        score = float(attrs.get("score", 0.0))
                        in_deg = int(attrs.get("in", 0))
                        out_deg = int(attrs.get("out", 0))
                    except ValueError:
                        score, in_deg, out_deg = 0.0, 0, 0
                        
                    mode = attrs.get("mode", "sig")
                    
                    f_path = files.get(file_alias, "")
                    node_id = f"{f_path}::{node_name}" if f_path else f"{node_alias}::{node_name}"
                    
                    nodes_map[node_alias] = {
                        "id": node_id,
                        "alias": node_alias,
                        "file_alias": file_alias,
                        "file": f_path,
                        "start_line": start_line,
                        "end_line": end_line,
                        "type": node_type,
                        "name": node_name,
                        "simple_name": node_name,
                        "qualified_name": f_path.replace("/", ".").replace(".py", "") + "::" + node_name,
                        "signature": sig,
                        "docstring": doc,
                        "score": score,
                        "in_degree": in_deg,
                        "out_degree": out_deg,
                        "mode": mode,
                        "tags": tags_list,
                        "behavior_skeleton": {},
                        "body": ""
                    }
                i += 1
                continue
                
            elif current_section == "SKELS":
                # Format: S N8 calls=[...] flow="..." effects=[...] raises=[...] returns=... reads=[...]
                if line_strip.startswith("S "):
                    parts = line_strip[2:].split(" ", 1)
                    if len(parts) == 2:
                        node_alias = parts[0]
                        skel_attrs_str = parts[1]
                        
                        skel_attrs = {}
                        # Extract attributes like calls=[...] or flow="..."
                        skel_parts = re.findall(r'(\w+)=(?:\[([^\]]*)\]|"([^"]*)"|(\S+))', skel_attrs_str)
                        for k, v1, v2, v3 in skel_parts:
                            if v1 is not None: # matched list inside brackets
                                skel_attrs[k] = [x.strip() for x in v1.split(",") if x.strip()]
                            elif v2 is not None: # matched double-quoted string
                                skel_attrs[k] = v2
                            else: # matched plain word/val
                                skel_attrs[k] = v3
                                
                        skeletons[node_alias] = skel_attrs
                i += 1
                continue
                
            elif current_section == "EDGES":
                # Format: N1 -> N2 import src.config resolved
                # Or: N1 -> EXT:json.load call stdlib
                match = re.match(r"^(\w+)\s+->\s+(\S+)\s+(.+)$", line_strip)
                if match:
                    src, dst, rest = match.groups()
                    rest_parts = rest.split(" ")
                    edge_type = rest_parts[0] if len(rest_parts) > 0 else "unknown"
                    relation = rest_parts[1] if len(rest_parts) > 1 else "unknown"
                    status = rest_parts[2] if len(rest_parts) > 2 else "unresolved"
                    
                    edges.append({
                        "source": src,
                        "target": dst,
                        "type": edge_type,
                        "relation": relation,
                        "status": status
                    })
                i += 1
                continue
                
            elif current_section == "BODIES":
                # Format:
                # ### N8 src/helpers/utils.py::get_local_products
                # def get_local_products():
                # ...
                if line_strip.startswith("### "):
                    parts = line_strip[4:].split(" ", 1)
                    node_alias = parts[0]
                    node_id = parts[1] if len(parts) > 1 else ""
                    
                    # Accumulate code lines
                    code_lines = []
                    i += 1
                    while i < len(lines):
                        next_line = lines[i]
                        # Check if we hit next section or next body header
                        if next_line.strip().startswith("### ") or next_line.strip() in ("NOTES", "FILES", "NODES", "SKELS", "EDGES", "BODIES"):
                            break
                        code_lines.append(next_line)
                        i += 1
                    
                    bodies[node_alias] = "".join(code_lines).strip()
                    continue
                i += 1
                continue
                
            elif current_section == "NOTES":
                if "=" in line_strip:
                    k, v = line_strip.split("=", 1)
                    if k == "unresolved_symbols":
                        unresolved_symbols = [x.strip() for x in v.split(",") if x.strip()]
                    elif k == "parse_errors":
                        try:
                            parse_errors = int(v)
                        except ValueError:
                            pass
                i += 1
                continue
                
            i += 1
            
        # Enrich nodes with skeletons and bodies
        for alias, node in nodes_map.items():
            if alias in skeletons:
                node["behavior_skeleton"] = skeletons[alias]
            if alias in bodies:
                node["body"] = bodies[alias]
                
        return {
            "metadata": metadata,
            "files": files,
            "file_to_alias": file_to_alias,
            "nodes": list(nodes_map.values()),
            "nodes_map": nodes_map,
            "edges": edges,
            "unresolved_symbols": unresolved_symbols,
            "parse_errors": parse_errors
        }

    @staticmethod
    def load_debug_json(path: str) -> Dict[str, Any]:
        """
        Loads the codebase_manifest.debug.json.
        """
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"Warning: Failed to load debug JSON manifest at {path}: {e}")
            return {}
            
    @classmethod
    def get_unified_nodes(cls, txt_path: str, json_path: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Parses compact text manifest and optional debug json, returning a fully enriched node list.
        """
        parser = cls(txt_path, json_path)
        return parser.nodes

    # Convenience Helpers
    def get_node(self, node_id: str) -> Optional[Dict[str, Any]]:
        """
        Returns a node dict from its node_id (the alias N0, or the full id path::name).
        """
        if node_id in self.nodes_map:
            return self.nodes_map[node_id]
        for node in self.nodes_map.values():
            if node["id"] == node_id:
                return node
        return None

    def get_file_path(self, file_alias: str) -> Optional[str]:
        """
        Returns the file path for a file alias (e.g. F0 -> app/api/catalog.py).
        """
        return self.files.get(file_alias)

    def get_node_display_name(self, node_id: str) -> str:
        """
        Returns a user-friendly display name of the node.
        """
        node = self.get_node(node_id)
        if not node:
            return node_id
        name = node.get("name", "")
        if name == "<module>":
            return f"{node.get('file', 'unknown')} (module)"
        return name

    def get_concrete_nodes(self) -> List[Dict[str, Any]]:
        """
        Returns all nodes that are not <module>.
        """
        return [n for n in self.nodes if n.get("name") != "<module>"]

    def _get_alias(self, node_id: str) -> Optional[str]:
        if node_id in self.nodes_map:
            return node_id
        node = self.get_node(node_id)
        return node["alias"] if node else None

    def get_outbound_neighbors(self, node_id: str) -> List[Dict[str, Any]]:
        """
        Returns nodes that this node points to.
        """
        alias = self._get_alias(node_id)
        if not alias:
            return []
        neighbors = []
        for edge in self.edges:
            if edge["source"] == alias:
                tgt_alias = edge["target"]
                tgt_node = self.get_node(tgt_alias)
                if tgt_node:
                    neighbors.append(tgt_node)
        return neighbors

    def get_inbound_neighbors(self, node_id: str) -> List[Dict[str, Any]]:
        """
        Returns nodes that point to this node.
        """
        alias = self._get_alias(node_id)
        if not alias:
            return []
        neighbors = []
        for edge in self.edges:
            if edge["target"] == alias:
                src_alias = edge["source"]
                src_node = self.get_node(src_alias)
                if src_node:
                    neighbors.append(src_node)
        return neighbors

    def get_neighbors(self, node_id: str) -> List[Dict[str, Any]]:
        """
        Returns all inbound and outbound neighbors.
        """
        outbound = self.get_outbound_neighbors(node_id)
        inbound = self.get_inbound_neighbors(node_id)
        seen = set()
        neighbors = []
        for n in outbound + inbound:
            if n["alias"] not in seen:
                seen.add(n["alias"])
                neighbors.append(n)
        return neighbors

    def get_edges_for_node(self, node_id: str) -> List[Dict[str, Any]]:
        """
        Returns all enriched edges where the node is source or target.
        """
        alias = self._get_alias(node_id)
        if not alias:
            return []
        res = []
        for edge in self.edges:
            if edge["source"] == alias or edge["target"] == alias:
                res.append(edge)
        return res
