# Bind skills to selected tools

Use the registry in [bindings.json](bindings.json) to select exact upstream tool
names and Markdown skill paths. Skill paths resolve from this directory.

```json
{
  "bindings": [
    {
      "tools": ["createJiraIssue", "editJiraIssue"],
      "skills": ["../skills/jira-write-ticket/SKILL.md"]
    }
  ]
}
```

## Connect the upstream server

1. Add a remote Atlassian MCP catalog entry in Obot with
   `https://mcp.atlassian.com/v2/mcp?tools=all`.
2. Complete Atlassian authentication and create a vMCP with that component.
3. Export the component's original upstream `tools/list` response. Collect all
   pages into a single `tools` array and remove `nextCursor`.
4. Check the tool names against your authenticated inventory. Use original
   upstream names rather than a prefix or rename applied by Obot.

Atlassian documents the flat tool endpoint for gateways in its
[setup guide](https://support.atlassian.com/atlassian-ai-gateway/docs/get-started-with-the-atlassian-remote-mcp-server/).

## Render descriptions

From the repository root, run:

```sh
python3 scripts/render-tool-skills.py \
  --tools-list /path/to/complete-tools.json \
  --out /tmp/obot-tool-overrides.json
```

If the component already has overrides, provide its existing `toolOverrides`
array:

```sh
python3 scripts/render-tool-skills.py \
  --tools-list /path/to/complete-tools.json \
  --existing-overrides /path/to/current-overrides.json \
  --out /tmp/obot-tool-overrides.json
```

The output is a complete component `toolOverrides` array. On a fresh component,
it retains every advertised tool. With existing overrides, it preserves their
selection, disabled states, names, and metadata. A binding to a missing or
disabled tool fails before the output file is written.

## Apply descriptions in Obot

In the vMCP component's tool editor, set each bound tool's description override
to the generated `overrideDescription`. Keep its original name and enabled
selection unless you intend to change them.

Obot treats a nonempty `toolOverrides` array as an allowlist. Replacing that array
with only the two Jira entries can hide all read tools. Use the full renderer
output when replacing the component field.

For an API update, preserve the complete vMCP manifest, components, and profiles.
The renderer output is one component field, not the complete request body. Do
not replay masked credentials from a GET response as secret values. Prefer the
component editor for initial setup.

Refresh the tool list in each MCP client. Confirm that create and update tools
contain the skill, read tools remain available, and disabled tools remain
disabled. No live Jira write is required for this check.

## Add or update a skill

Add the self-contained `SKILL.md` under `skills/`, add its binding, then render
and apply the descriptions again. Bindings do not automatically synchronize into
a running Obot gateway. Scripts and referenced files inside a skill package are
not installed by embedding its Markdown body.

The tool descriptions make the instructions available before `tools/call`.
Use [Obot filters](https://docs.obot.ai/functionality/filters/) to enforce rules
that must prevent a write. Obot's
[Skills catalog](https://docs.obot.ai/functionality/skills/) is a separate feature
for discovery and installation by Obot agents.
