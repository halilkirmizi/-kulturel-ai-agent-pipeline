#!/usr/bin/env python3
"""Scan Obsidian vault, extract wikilinks + tags, build read-only graph JSON."""

import re
import json
from pathlib import Path
from collections import defaultdict

VAULT = Path(r"C:\Users\liter\SecondBrain-vault\SecondBrain")
OUT = Path(__file__).resolve().parent / "graph_store.json"
EXCLUDE = {".git", "node_modules", "__pycache__", ".obsidian", "_attachments", ".claude"}


def is_excluded(rel: Path) -> bool:
    parts = rel.parts
    return bool(set(parts) & EXCLUDE)


def gather_md_files() -> list:
    files = []
    for f in VAULT.rglob("*.md"):
        rel = f.relative_to(VAULT)
        if is_excluded(rel):
            continue
        if f.stat().st_size > 500_000:
            continue
        files.append(f)
    return sorted(files)


def extract_tags(content: str) -> set:
    tags = set()
    in_code = False

    # Parse YAML frontmatter tags
    if content.startswith("---"):
        fm_end = content.find("---", 3)
        if fm_end != -1:
            frontmatter = content[3:fm_end]
            # Inline format: tags: [t1, t2]
            for m in re.finditer(r"tags:\s*\[([^\]]+)\]", frontmatter):
                for t in m.group(1).split(","):
                    t_clean = t.strip().strip('"').strip("'")
                    if t_clean:
                        tags.add(t_clean)
            # Block format: tags:\n  - t1\n  - t2
            in_tags_block = False
            for line in frontmatter.split("\n"):
                stripped = line.strip()
                if stripped.startswith("tags:"):
                    in_tags_block = True
                    continue
                if in_tags_block:
                    if stripped.startswith("- "):
                        t = stripped[2:].strip().strip('"').strip("'")
                        if t:
                            tags.add(t)
                    elif ":" in stripped:
                        # Next key reached
                        in_tags_block = False

    for line in content.split("\n"):
        stripped = line.strip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_code = not in_code
            continue
        if in_code:
            continue
        for m in re.finditer(r"(?<!\w)(#[a-zA-Z][a-zA-Z0-9_/.-]*)", line):
            tag = m.group(1)[1:]
            if tag.lower() in ("no", "todo", "100"):
                continue
            tags.add(tag)
    return tags


def extract_wikilinks(content: str) -> set:
    links = set()
    for m in re.finditer(r"\[\[([^\]|#]+?)(?:#[^\]]*)?(?:\|[^\]]*)?\]\]", content):
        target = m.group(1).strip()
        if target and not target.startswith("http"):
            links.add(target)
    return links


def resolve_wikilink(target: str, all_files: list, vault: Path) -> str | None:
    t = target.lower().replace("\\", "/")
    for f in all_files:
        rel = str(f.relative_to(vault)).replace("\\", "/")
        stem = f.stem.lower()
        if stem == t or rel == t + ".md":
            return rel
        if rel.endswith("/" + t + ".md"):
            return rel
    return None


def main():
    md_files = gather_md_files()
    print(f"Found {len(md_files)} .md files")

    nodes: dict[str, dict] = {}
    edges: list[dict] = []
    tag_index: dict[str, list] = defaultdict(list)

    for f in md_files:
        rel = str(f.relative_to(VAULT)).replace("\\", "/")
        content = f.read_text(encoding="utf-8", errors="replace")
        folder = str(f.parent.relative_to(VAULT)).replace("\\", "/") if f.parent != VAULT else ""

        tags = extract_tags(content)
        wikilinks = extract_wikilinks(content)

        nodes[rel] = {
            "id": rel,
            "label": f.stem,
            "folder": folder,
            "tags": sorted(tags),
        }

        for tag in tags:
            tag_index[tag].append(rel)

        for target in wikilinks:
            resolved = resolve_wikilink(target, md_files, VAULT)
            edges.append({
                "source": rel,
                "target": resolved or target,
                "type": "wikilink",
                "resolved": resolved is not None,
            })

        parent = folder
        if parent:
            edges.append({
                "source": rel,
                "target": parent,
                "type": "container",
                "resolved": True,
            })

    # Add folder nodes
    for f in md_files:
        parent = f.parent.relative_to(VAULT)
        ps = str(parent).replace("\\", "/")
        if ps != "." and ps not in nodes:
            pp = str(parent.parent).replace("\\", "/") if str(parent.parent) != "." else ""
            nodes[ps] = {
                "id": ps,
                "label": parent.name,
                "folder": pp,
                "tags": [],
            }

    graph = {
        "meta": {
            "vault": "SecondBrain",
            "count_nodes": len(nodes),
            "count_edges": len(edges),
            "count_tags": len(tag_index),
        },
        "nodes": list(nodes.values()),
        "edges": edges,
        "tags": {tag: sorted(paths) for tag, paths in tag_index.items()},
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(graph, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Saved: {OUT}")
    print(f"  Nodes: {len(nodes)}, Edges: {len(edges)}, Tags: {len(tag_index)}")


if __name__ == "__main__":
    main()
