# Changelog

## 1.2.3-1

- Initial amd64 Home Assistant app using the official MCPHub 1.2.3 image, pinned by digest.
- Keep settings, users, bearer keys and the credential key in `/data/mcp_settings.json` and beside it.
- Keep a persistent dashboard session key, so a restart does not log users out.
- Restore bearer authentication for MCP endpoints and dashboard login at every start.
- Add the `tool_call_guard` option for MCPHub's tool-call argument guard.
- Add startup, authentication, stdio server, and restart persistence checks.
