# Obot MCP Gateway

This app runs Obot v0.26.3 on amd64 Home Assistant OS or Supervised. It uses
Obot's bundled PostgreSQL database and keeps its state under `/data`.

## First start

1. Set `server_url` to the address that your MCP clients can reach. Include
   `http://` or `https://` and the port if needed. For example:

   ```yaml
   server_url: "http://homeassistant.local:8180"
   bootstrap_token: ""
   ```

   Use your actual hostname. A private DNS name reachable over your VPN is
   useful when agents run on several machines. An HTTPS reverse proxy can also
   provide the origin. Configure its upstream to this app's port 8180.

2. On the app's information page, disable **Protection mode**. Obot needs the
   Docker socket even when you connect only to remote MCP servers.
3. Start the app and open its Web UI. Obot logs its initial bootstrap token.
   Keep that token private. With `bootstrap_token` empty, the wrapper generates
   a token once and reuses it after a restart.
4. Use the bootstrap login to configure a normal authentication provider in
   Obot. Follow [Obot's authentication guide](https://docs.obot.ai/installation/enabling-authentication/).
5. After setup, you can turn on **Start on boot** in Home Assistant.

There is no Home Assistant sidebar ingress for this app. Obot needs a stable
origin for its login and MCP OAuth flows.

## Options

| Option | Meaning |
| --- | --- |
| `server_url` | Required HTTP(S) origin that clients use to reach Obot. |
| `bootstrap_token` | Optional bootstrap login token. Leave empty to generate and retain a random token. |

`server_url` must have a hostname and optional port. It cannot contain a
username, password, path, query, fragment, or trailing slash. If you change the
mapped port, update this URL too. Obot advertises this address to its clients;
`localhost` would refer to each client's own machine.

If you supply `bootstrap_token`, that value takes precedence over the generated
token. A supplied token must have at least six printable characters and no
spaces. Returning the option to empty restores the saved generated token, or
creates it if none exists. Changing the bootstrap token does not change the
database encryption key.

Authentication and credential encryption are always enabled by the wrapper.
Obot Agent and hosted-agent features are disabled. No model-provider API key is
required for this MCP gateway configuration.

## Connect Jira and apply a skill

1. In Obot, create a remote MCP server for Atlassian and complete its OAuth
   connection. For explicit Jira tool names, use the flat-tool endpoint:

   ```text
   https://mcp.atlassian.com/v2/mcp?tools=all
   ```

2. Create a **Virtual MCP** containing that server. Give each agent access to
   the virtual MCP URL shown by Obot and authenticate the agent.
3. Follow [the tool-skill guide](../tool-skills/README.md) to attach the included
   [Jira skill](../skills/jira-write-ticket/SKILL.md) to `createJiraIssue` and
   `editJiraIssue` through Obot's tool description overrides.
4. Refresh the client's tool list and inspect those descriptions before using
   the Jira write tools.

The repository includes the skill and renderer as files for an administrator to
edit and apply. The app does not automatically synchronize them into Obot.
Descriptions supply instructions before the model chooses a tool call. For a
requirement that must block a write, configure an
[Obot request filter](https://docs.obot.ai/functionality/filters/) as well.

## Access and backups

The default mapping is host port 8180 to Obot port 8080. Keep this service on
your private network or behind a suitable authenticated private-access setup.
Docker access allows container operations on the Home Assistant host. Give
administration access only to people you trust with that host.

Include this app in Home Assistant backups. It requests a **cold backup**, which
stops the app while its data is copied. The database, bootstrap-token file, and
encryption configuration must be restored together. Losing the encryption key
can make saved credentials unreadable.

The wrapper stores its encryption configuration at `/data/encryption.yaml` and
its generated bootstrap token at `/data/bootstrap-token`. PostgreSQL uses
`/data/postgresql`. These paths are inside the app's persistent data volume.
Do not delete them to resolve an ordinary startup error.

## Troubleshooting

- **Docker permission or socket error:** check that Protection mode is off and
  restart the app. The manifest requests Docker access, which Home Assistant
  supplies only when the app is unprotected.
- **Invalid app options:** check the URL format above. The wrapper rejects
  malformed options before starting Obot.
- **Clients cannot connect or OAuth redirects fail:** check that `server_url`
  is reachable from those clients and matches your port or reverse proxy.
- **Out of memory or slow startup:** check free memory and storage on the host.
  Obot documents a baseline of two CPU cores, 4 GB RAM, and 10 GB storage.
- **Saved token or encryption configuration is empty:** restore the app's data
  from a backup. The wrapper refuses to replace an empty saved secret silently.
- **Database exists without an encryption configuration:** restore the original
  configuration from the same backup. A new key cannot decrypt its credentials.

For upstream configuration details, see
[Obot server configuration](https://docs.obot.ai/configuration/server-configuration/).
