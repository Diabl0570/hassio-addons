import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RENDERER = ROOT / "scripts/render-tool-skills.py"


class ToolSkillsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.tools = {
            "tools": [
                {"name": "getJiraIssue", "description": "Read a ticket."},
                {"name": "searchJiraIssues", "description": "Search tickets."},
                {"name": "createJiraIssue", "description": "Create a ticket."},
                {"name": "editJiraIssue", "description": "Update a ticket."},
            ]
        }
        self.skill = self.directory / "SKILL.md"
        self.skill.write_text("---\nname: ticket\ndescription: Write tickets.\n---\n# Ticket guidance\n\nPreserve unrelated fields.\n", encoding="utf-8")
        self.bindings = {"bindings": [{"tools": ["createJiraIssue", "editJiraIssue"], "skills": ["SKILL.md"]}]}

    def run_cli(self, tools=None, bindings=None, overrides=None, out=None, defaults=False):
        tools_path = self.directory / "tools.json"
        tools_path.write_text(json.dumps(self.tools if tools is None else tools), encoding="utf-8")
        command = [sys.executable, str(RENDERER), "--tools-list", str(tools_path)]
        if not defaults:
            bindings_path = self.directory / "bindings.json"
            bindings_path.write_text(json.dumps(self.bindings if bindings is None else bindings), encoding="utf-8")
            command += ["--bindings", str(bindings_path)]
        if overrides is not None:
            overrides_path = self.directory / "overrides.json"
            overrides_path.write_text(json.dumps(overrides), encoding="utf-8")
            command += ["--existing-overrides", str(overrides_path)]
        if out:
            command += ["--out", str(out)]
        return subprocess.run(command, capture_output=True, text=True, check=False)

    def rendered(self, **kwargs):
        result = self.run_cli(**kwargs)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_fresh_configuration_keeps_every_tool(self):
        entries = self.rendered(defaults=True)
        self.assertEqual([entry["name"] for entry in entries], [tool["name"] for tool in self.tools["tools"]])
        self.assertTrue(all(entry["enabled"] for entry in entries))
        self.assertNotIn("overrideDescription", entries[0])
        self.assertNotIn("overrideDescription", entries[1])
        self.assertTrue(entries[2]["overrideDescription"].startswith("Create a ticket."))
        self.assertIn("Use the language requested by the user.", entries[2]["overrideDescription"])
        self.assertNotIn("description: Create or update", entries[2]["overrideDescription"])

    def test_existing_selection_and_metadata_are_preserved(self):
        original = [
            {"name": "getJiraIssue", "enabled": False, "overrideName": "read_ticket", "metadata": {"owner": "test"}},
            {"name": "createJiraIssue", "enabled": True, "overrideName": "new_ticket", "description": "Cached description.", "overrideDescription": "Our create instructions."},
        ]
        binding = {"bindings": [{"tools": ["createJiraIssue"], "skills": ["SKILL.md"]}]}
        entries = self.rendered(overrides=original, bindings=binding)
        self.assertEqual(entries[0], original[0])
        self.assertEqual(entries[1]["overrideName"], "new_ticket")
        self.assertEqual(entries[1]["description"], original[1]["description"])
        self.assertTrue(entries[1]["overrideDescription"].startswith("Our create instructions."))
        self.assertEqual(len(entries), 2)
        self.assertNotIn("editJiraIssue", [entry["name"] for entry in entries])

    def test_display_description_cannot_replace_upstream_instructions(self):
        binding = {"bindings": [{"tools": ["createJiraIssue"], "skills": ["SKILL.md"]}]}
        for runtime_override in ({}, {"overrideDescription": ""}):
            with self.subTest(runtime_override=runtime_override):
                original = {
                    "name": "createJiraIssue",
                    "enabled": True,
                    "description": "Display label without runtime instructions.",
                    "metadata": {"owner": "test"},
                    **runtime_override,
                }
                entry = self.rendered(overrides=[original], bindings=binding)[0]
                self.assertTrue(entry["overrideDescription"].startswith("Create a ticket."))
                self.assertNotIn(original["description"], entry["overrideDescription"])
                self.assertEqual(entry["description"], original["description"])
                self.assertEqual(entry["metadata"], original["metadata"])

    def test_disabled_or_unlisted_bound_tool_is_rejected(self):
        binding = {"bindings": [{"tools": ["createJiraIssue"], "skills": ["SKILL.md"]}]}
        for overrides in ([{"name": "createJiraIssue", "enabled": False}], [{"name": "getJiraIssue", "enabled": True}]):
            with self.subTest(overrides=overrides):
                result = self.run_cli(overrides=overrides, bindings=binding)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("disabled or absent", result.stderr)

    def test_missing_configured_tool_does_not_overwrite_output(self):
        output = self.directory / "output.json"
        output.write_text("keep this", encoding="utf-8")
        result = self.run_cli(tools={"tools": self.tools["tools"][:2]}, out=output)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("missing from tools/list", result.stderr)
        self.assertEqual(output.read_text(encoding="utf-8"), "keep this")

    def test_pagination_is_rejected_for_both_input_shapes(self):
        paginated = {**self.tools, "nextCursor": "another-page"}
        for tools in (paginated, {"jsonrpc": "2.0", "id": 1, "result": paginated}):
            with self.subTest(tools=tools):
                result = self.run_cli(tools=tools)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("paginated", result.stderr)

    def test_rerender_replaces_skill_body_without_duplicating(self):
        first = self.rendered()
        self.assertEqual(first, self.rendered(overrides=first))
        self.skill.write_text("# New guidance\n\nCheck existing state.\n", encoding="utf-8")
        changed = self.rendered(overrides=first)
        description = changed[2]["overrideDescription"]
        self.assertIn("Check existing state.", description)
        self.assertNotIn("Preserve unrelated fields.", description)
        self.assertEqual(description.count("<!-- obot-tool-skills:start -->"), 1)

    def test_removing_binding_removes_previous_skill_suffix(self):
        first = self.rendered()
        removed = self.rendered(overrides=first, bindings={"bindings": []})
        self.assertEqual(removed[2]["overrideDescription"], "Create a ticket.")
        self.assertEqual(removed[3]["overrideDescription"], "Update a ticket.")
        self.assertTrue(all(entry["enabled"] for entry in removed))

    def test_duplicate_bindings_and_empty_skills_are_rejected(self):
        duplicate = {"bindings": self.bindings["bindings"] * 2}
        result = self.run_cli(bindings=duplicate)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("duplicate binding", result.stderr)
        self.skill.write_text("---\nname: empty\n---\n", encoding="utf-8")
        result = self.run_cli()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("empty skill body", result.stderr)

    def test_malformed_override_is_rejected(self):
        result = self.run_cli(overrides=[{"name": "createJiraIssue", "enabled": "true"}])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must be a boolean", result.stderr)

    def test_non_json_numeric_constant_is_rejected(self):
        result = self.run_cli(tools={**self.tools, "metadata": float("nan")})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("invalid JSON constant", result.stderr)

    def test_complete_json_rpc_response_and_output_file(self):
        output = self.directory / "output.json"
        result = self.run_cli(tools={"jsonrpc": "2.0", "id": 1, "result": self.tools}, out=output)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertEqual(json.loads(output.read_text(encoding="utf-8")), self.rendered())


if __name__ == "__main__":
    unittest.main()
