# Configuration

Install the app from this repository, configure it, and start it. Enable **Show
in sidebar** for a book icon in Home Assistant. It is visible to signed-in
non-admin users too. Those users can use the same story features, including
editing and generation, that the story server permits.

| Option | Purpose |
| --- | --- |
| `target_url` | Public HTTPS origin of the existing story server, without a path. Default: `https://verhalen.xijezo.nl`. Only port 443 and public DNS addresses are accepted. |
| `username` | Story server's Basic Auth username. Default: `familie`. |
| `password` | Story server's Basic Auth password. Required. |

The password is kept in Home Assistant's app options and sent only to the
configured HTTPS server. It is never sent to the browser. No model API key is
needed by this app; generation and backup credentials stay on the story server.
Protect Home Assistant backups because they can include app options.

## Access and privacy

Only Supervisor ingress connections from `172.30.32.2` are accepted. There is no
published host port and no separate browser login. Home Assistant cookies,
authorization tokens, and user identity headers are not passed to the story
server. TLS certificate verification is always enabled. Redirects to another
server are blocked.

The story server must use relative URLs so pages and API calls work inside the
ingress path. HTTP streaming downloads and JSON POST requests up to 25 MiB are
supported; WebSockets and file-upload forms are not supported. A POST request
must come from the same Home Assistant origin and use the story app's JSON
request header.

## Troubleshooting

- **Configure a public HTTPS target...** in the log: check all three options.
- **Check the story server credentials...**: update the username/password and
  restart the app.
- **The story server is unavailable**: check DNS, connectivity and its TLS
  certificate. Private DNS addresses are intentionally rejected.
- **This request did not come from the story app**: confirm the frontend uses
  relative API URLs and sends `X-Requested-With: donna-story-app`.

The app stores no separate library. Restoring it requires its configuration;
story content is restored through the story server's own backup process.

Report issues in this repository without including passwords, private stories,
Home Assistant session cookies, or ingress URLs containing tokens.
