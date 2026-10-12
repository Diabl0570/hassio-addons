# Collection migration

On 12 October 2026, `Diabl0570/home-assistant-app-cliproxyapi` was renamed to `Diabl0570/hassio-addons`. Obot and the Jira tool-skill package were added to the collection. The rename retained the repository's history, open update pull requests, and existing public CLIProxyAPI image package.

## Source revisions

| Imported source | Commit |
| --- | --- |
| CLIProxyAPI app | `6bfae9283bcf74117369cdbb417997900a1db6c8` |
| Obot app and tool-skill package | `088b0096a4ccb396d288c355bcea716bb2378de8` |
| Combined collection release | `beb143424746125f3ffd35b9e2b41928925c72d4` |

Both app runtimes and upstream pins were preserved. The CLIProxyAPI wrapper version became `8.0.10-4`. Obot remained `0.26.3-1`.

## Existing Home Assistant installation

The existing installation retained its configured repository URL, `https://github.com/Diabl0570/home-assistant-app-cliproxyapi#stable`. GitHub redirects Git fetches to the renamed collection. Home Assistant keeps its repository prefix from the configured URL, preserving the installed app identity and private data directory.

Home Assistant discovered both apps through that source. CLIProxyAPI was updated in place after an app-only backup. The backup archive was inspected, copied off the device, and verified by checksum.

Verification after the update confirmed:

- The same installed app identity, hostname, settings, and published ports.
- Six saved provider accounts and the same 31 advertised model entries.
- Ten historical request records matching the pre-update sample.
- Authenticated proxy and manager access through the published LAN ports.
- A successful real model response and rejection of unauthenticated API requests.
- The original boot, auto-update, watchdog, and protection settings.

Obot was available in the app store but had not been installed. Its authenticated startup and database, encryption key, and bootstrap token persistence passed container checks.

## Release verification

[The collection branch build](https://github.com/Diabl0570/hassio-addons/actions/runs/38253157695) and [the published main build](https://github.com/Diabl0570/hassio-addons/actions/runs/38253707454) passed all jobs. The main build published the immutable CLIProxyAPI image and verified anonymous access before advancing `stable`.

CLIProxyAPI's image revision records the commit that built it. Collection changes outside its app folder can reuse that version only when the recorded commit's complete app source tree matches the current tree. The workflow then runs the smoke and retry checks against the pulled image before advancing `stable`.

## Installation and recovery

New installations use `https://github.com/Diabl0570/hassio-addons#stable`.

Existing installations using the old CLIProxyAPI source should retain that exact URL. Adding the new source creates separate app identities with separate private data. Keep the old GitHub repository name unused so its redirect continues to work.

For rollback of the verified in-place update, stop the app and restore its app-only backup to the same installed identity. The pre-migration image version `8.0.10-3` remains published. Restoring a backup does not remap an app to a different repository prefix.
