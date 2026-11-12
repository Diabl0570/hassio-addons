# MCPHub

This app runs MCPHub 1.2.3 on amd64 Home Assistant OS or Supervised. MCPHub
gives your agents one MCP endpoint for all of your MCP servers. In its
dashboard you turn single tools on or off, rewrite tool descriptions, bundle
tools into groups with their own endpoint, and give each agent a key that only
reaches the groups or servers you choose.

The app needs no database and no Docker access. It keeps its state in one
settings file under `/data`.

## First start

1. Install and start the app. Home Assistant builds the image on the device
   from the pinned official MCPHub image, about 2 GB on disk.
2. Open the app's **Log** tab. On the first start, MCPHub logs a line
   `Generated admin password: ...`. It never logs it again.
3. Open **Web UI**, log in as `admin` with that password, and choose a new
   password under **Change Password**.

## Add MCP servers

Under **Servers**, add each MCP server:

- **Remote servers:** use the server's streamable HTTP or SSE URL and any
  headers it needs. A server in another Home Assistant app is reachable at the
  Home Assistant host's address and that app's mapped port.
- **Local servers:** use a command such as `npx` or `uvx` with the package and
  its arguments. The image includes Node.js 22, Python 3.13 and uv. The
  command downloads its package when the server starts, so the app needs
  internet access when it starts.

MCPHub prefixes each tool with its server name, such as `fetch-fetch` for the
`fetch` tool of a server named `fetch`.

## Choose what each agent sees

- **One tool:** open a server and turn the tool off, or rewrite its
  description.
- **A bundle:** under **Groups**, create a group, add servers to it, and pick
  the tools of each server. Agents reach the group at `/mcp/<group name>`.
- **One key per agent:** under **Settings → Keys**, add a key per agent or
  machine. **Access scope** limits the key to all servers, chosen groups,
  chosen servers, a combination, or everything except some groups or servers.
  MCPHub shows the token once.
- **Rules:** **Settings → Tool access policies** allows or denies tools by
  key, group, server, user and original tool name. A matching deny always
  wins.

Keys and policies decide which tools an agent can see and call. MCPHub does
not check the arguments of a call, apart from the optional guard below.

## Connect an agent

Agents use `http://HOME_ASSISTANT_HOST:8190/mcp` for every server the key
allows, or `http://HOME_ASSISTANT_HOST:8190/mcp/<group name>` for one group.
They send the key as a bearer token. For Claude Code:

```sh
claude mcp add --transport http mcphub http://HOME_ASSISTANT_HOST:8190/mcp \
  --header "Authorization: Bearer YOUR_KEY"
```

## Options

| Option | Meaning |
| --- | --- |
| `tool_call_guard` | Reject tool calls whose arguments contain command injection, reverse shell or cloud credential theft patterns before they reach a server. Off by default. |

## Authentication

MCPHub can switch off key checks for its MCP endpoints, and it can skip the
dashboard login. Either would let anyone on your network use every server. At
each start, the app sets **Enable Bearer Authentication** on and dashboard
login on in `/data/mcp_settings.json`. A change in the dashboard lasts until
the next restart. Other settings are kept as they are.

The app removes Home Assistant's Supervisor token from MCPHub's environment,
so MCP servers that MCPHub starts cannot use it.

## Access and backups

The default mapping is host port 8190 to MCPHub port 3000. There is no Home
Assistant sidebar ingress: MCPHub serves its dashboard from a fixed path. Keys
travel in plain HTTP, so keep the port on your private network or VPN, or put
an HTTPS reverse proxy in front of it.

Include this app in Home Assistant backups. These files in its data volume
belong together:

- `mcp_settings.json`: servers with their URLs, headers and environment,
  users, groups, keys and policies. Keys are stored as hashes. Server
  credentials that you type into a server's configuration are stored as
  written.
- `mcp_settings.json.credentials.key`: encrypts personal credentials that
  users bind to a shared server. MCPHub creates it the first time someone
  saves one. Without it, those credentials cannot be read.
- `jwt-secret`: signs dashboard logins, so a restart does not log users out.

The files are readable only by the app.

## Troubleshooting

- **Lost the generated admin password:** MCPHub generates it only while no
  user exists, and a backup holds the same password. Uninstall and reinstall
  the app, which deletes its data, to get a new one.
- **Invalid app options:** set `tool_call_guard` to `true` or `false`.
- **`/data/mcp_settings.json` is not a JSON object:** restore the app from a
  backup. The app does not replace a damaged settings file.
- **A local server does not connect:** check the app log for the command's
  error. Starting an `npx` or `uvx` server needs internet access.
- **An agent gets 401:** check that the key is enabled and its access scope
  includes the endpoint the agent uses.

For upstream configuration details, see the
[MCPHub documentation](https://docs.mcphub.app/).
