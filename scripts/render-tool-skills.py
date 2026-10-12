#!/usr/bin/env python3
"""Render a complete Obot toolOverrides array from an upstream tool inventory."""

import argparse
import json
import sys
from pathlib import Path


START = "\n\n<!-- obot-tool-skills:start -->\n"
END = "\n<!-- obot-tool-skills:end -->"
DEFAULT_BINDINGS = Path(__file__).resolve().parents[1] / "tool-skills/bindings.json"


def unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def reject_constant(value):
    raise ValueError(f"invalid JSON constant: {value}")


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_keys, parse_constant=reject_constant)


def names(value, label):
    if not isinstance(value, list) or not value:
        raise ValueError(f"{label} must be a nonempty array")
    if any(not isinstance(name, str) or not name.strip() for name in value):
        raise ValueError(f"{label} must contain nonempty strings")
    if len(set(value)) != len(value):
        raise ValueError(f"{label} contains duplicates")
    return value


def tool_inventory(document):
    if not isinstance(document, dict) or "error" in document:
        raise ValueError("tools/list must be a successful JSON object")
    result = document.get("result", document)
    if not isinstance(result, dict) or not isinstance(result.get("tools"), list):
        raise ValueError("tools/list must contain a tools array or result.tools array")
    cursor = result.get("nextCursor")
    if cursor is not None and not isinstance(cursor, str):
        raise ValueError("tools/list nextCursor must be a string or null")
    if cursor:
        raise ValueError("tools/list is paginated; combine all pages and remove nextCursor first")
    tools = {}
    for tool in result["tools"]:
        if not isinstance(tool, dict) or not isinstance(tool.get("name"), str) or not tool["name"].strip():
            raise ValueError("each upstream tool must have a nonempty name")
        name = tool["name"]
        if name in tools:
            raise ValueError(f"duplicate upstream tool: {name}")
        if "description" in tool and not isinstance(tool["description"], str):
            raise ValueError(f"upstream description must be a string: {name}")
        tools[name] = tool
    return tools


def skill_body(path):
    markdown = path.read_text(encoding="utf-8-sig")
    lines = markdown.splitlines(keepends=True)
    if lines and lines[0].strip() == "---":
        closing = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
        if closing is None:
            raise ValueError(f"unclosed skill frontmatter: {path}")
        markdown = "".join(lines[closing + 1:])
    body = markdown.strip()
    if not body:
        raise ValueError(f"empty skill body: {path}")
    if "<!-- obot-tool-skills:" in body:
        raise ValueError(f"skill contains a reserved injection marker: {path}")
    return body


def skill_bindings(document, registry_path):
    if not isinstance(document, dict) or not isinstance(document.get("bindings"), list):
        raise ValueError("registry must contain a bindings array")
    bindings = {}
    for binding in document["bindings"]:
        if not isinstance(binding, dict):
            raise ValueError("each binding must be an object")
        tool_names = names(binding.get("tools"), "binding tools")
        skill_paths = names(binding.get("skills"), "binding skills")
        paths = []
        for relative in skill_paths:
            if Path(relative).is_absolute():
                raise ValueError(f"skill paths must be relative to the registry: {relative}")
            paths.append((registry_path.parent / relative).resolve())
        if len(set(paths)) != len(paths):
            raise ValueError("binding skills resolve to duplicate paths")
        bodies = [skill_body(path) for path in paths]
        for name in tool_names:
            if name in bindings:
                raise ValueError(f"duplicate binding for tool: {name}")
            bindings[name] = bodies
    return bindings


def override_entries(document):
    if not isinstance(document, list):
        raise ValueError("existing overrides must be a JSON array")
    entries = []
    seen = set()
    for entry in document:
        if not isinstance(entry, dict) or not isinstance(entry.get("name"), str) or not entry["name"].strip():
            raise ValueError("each override must have a nonempty name")
        name = entry["name"]
        if name in seen:
            raise ValueError(f"duplicate override for tool: {name}")
        seen.add(name)
        if not isinstance(entry.get("enabled"), bool):
            raise ValueError(f"override enabled must be a boolean: {name}")
        for field in ("overrideName", "description", "overrideDescription"):
            if field in entry and not isinstance(entry[field], str):
                raise ValueError(f"override {field} must be a string: {name}")
        entries.append(dict(entry))
    return entries


def original_description(description):
    if "<!-- obot-tool-skills:" not in description:
        return description
    if description.count(START) != 1 or description.count(END) != 1 or not description.endswith(END):
        raise ValueError("existing description has an invalid skill injection suffix")
    return description.split(START, 1)[0]


def render_overrides(tools, bindings, existing):
    entries = [dict(entry) for entry in existing] if existing else [{"name": name, "enabled": True} for name in tools]
    for entry in entries:
        if "overrideDescription" in entry:
            entry["overrideDescription"] = original_description(entry["overrideDescription"])
    selected = {entry["name"]: entry for entry in entries}
    for name, bodies in bindings.items():
        if name not in tools:
            raise ValueError(f"configured tool is missing from tools/list: {name}")
        if name not in selected or not selected[name]["enabled"]:
            raise ValueError(f"configured tool is disabled or absent from the existing allowlist: {name}")
        entry = selected[name]
        description = entry.get("overrideDescription") or tools[name].get("description", "")
        entry["overrideDescription"] = original_description(description) + START + "\n\n".join(bodies) + END
    return entries


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tools-list", type=Path, required=True, help="Complete upstream tools/list JSON response")
    parser.add_argument("--bindings", type=Path, default=DEFAULT_BINDINGS, help="Skill binding registry JSON")
    parser.add_argument("--existing-overrides", type=Path, help="Current Obot toolOverrides JSON array")
    parser.add_argument("--out", type=Path, help="Output path; defaults to stdout")
    args = parser.parse_args()
    try:
        tools = tool_inventory(read_json(args.tools_list))
        bindings = skill_bindings(read_json(args.bindings), args.bindings)
        existing = override_entries(read_json(args.existing_overrides)) if args.existing_overrides else []
        rendered = json.dumps(render_overrides(tools, bindings, existing), indent=2, ensure_ascii=False) + "\n"
        if args.out:
            args.out.write_text(rendered, encoding="utf-8")
        else:
            sys.stdout.write(rendered)
    except (ValueError, OSError, UnicodeError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
