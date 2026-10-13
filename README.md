# Home Assistant apps

This repository contains Kasper's Home Assistant apps for amd64 Home Assistant OS and Supervised installations.

| App | Purpose | Documentation |
| --- | --- | --- |
| CLIProxyAPI | OpenAI-compatible proxy with CPA Manager Plus and optional request diagnostics. | [English documentation](cliproxyapi/DOCS.md), [Nederlandse snelstart](cliproxyapi/QUICKSTART.nl.md) |
| Obot MCP Gateway | Authenticated MCP gateway with skills attached to selected tool descriptions. | [App setup](obot/DOCS.md), [tool-skill guide](tool-skills/README.md) |

## Install an app

1. In Home Assistant, open **Settings → Apps → App store → ⋮ → Repositories**. Older versions call apps add-ons.
2. Add `https://github.com/Diabl0570/hassio-addons#stable`.
3. Install the app you need and follow its documentation.

The `stable` branch advances after CLIProxyAPI's image build, smoke test, retry check, anonymous image-pull check, and Obot's startup and persistence check pass. Obot builds its wrapper locally from the pinned official image. CLIProxyAPI uses its existing public GHCR package.

If you already installed CLIProxyAPI, keep `https://github.com/Diabl0570/home-assistant-app-cliproxyapi#stable` in your Home Assistant repositories. GitHub redirects that URL to this repository after the rename. Keeping the configured URL preserves Home Assistant's app identity, options, and private data, so you can update the existing installation in place. Back up the app before updating. Adding the new URL alongside the old one creates a separate app with separate private data.

See the [collection migration record](docs/collection-migration.md) for source revisions, verification, and recovery.

## Configure CLIProxyAPI

Set `api_keys` to one or more random client keys. Set `management_password` to a different random password of at least 24 characters. The defaults cannot start.

Open **Web UI** to manage provider accounts in CPA Manager Plus. Clients use `http://HOME_ASSISTANT_IP:8317/v1` with a client API key. See [CLIProxyAPI documentation](cliproxyapi/DOCS.md) for routing, retries, model exclusions, and diagnostics.

## Configure Obot and a Jira skill

Set `server_url` to the HTTP or HTTPS origin that your agents can reach. Disable **Protection mode** for Obot, start the app, and use the initial bootstrap token to configure normal authentication.

Obot has access to the Docker daemon that runs Home Assistant and its apps. Keep the gateway on your private network and give administration access only to people you trust with that host. Obot's documented baseline is two CPU cores, 4 GB available RAM, and 10 GB storage.

The [starter Jira skill](skills/jira-write-ticket/SKILL.md) binds to `createJiraIssue` and `editJiraIssue` through the [binding registry](tool-skills/bindings.json). Follow the [tool-skill guide](tool-skills/README.md) to render and apply the descriptions in Obot.

Tool descriptions provide instructions before a call. Use an Obot request filter for rules that must reject a write. Changing the skill requires rendering and applying the descriptions again. The app does not synchronize them automatically.

## Maintain app releases

The daily updater proposes CLIProxyAPI v8 and CPA Manager Plus v1 updates in separate pull requests. It explicitly dispatches `build.yaml` for each update branch. Review the build before merging. New major releases and incompatible CPA Manager Plus releases require a manual review.

CLIProxyAPI image tags are immutable. Bump the app version suffix when its app folder changes. Changes confined to Obot, shared skills, or collection documentation reuse the existing CLIProxyAPI image after its source tree and container checks pass. The image name remains `ghcr.io/diabl0570/home-assistant-app-cliproxyapi-amd64` so existing installations can keep using the same public package. Obot's upstream and wrapper versions remain pinned in its manifest and Dockerfile.

The separate diagnostics compatibility job reports whether the pinned CPA Manager Plus interface still works. It does not block image publication. Diagnostics stays separate from the proxy at runtime. See [the compatibility contract](cliproxyapi/DOCS.md#updates-and-diagnostics-compatibility).

## Run local checks

```sh
python3 -m pip install PyYAML==6.0.3
python3 -m unittest discover -s cliproxyapi/tests -v
python3 -m unittest discover -s obot/tests -v
python3 -m unittest discover -s tests -v
bash -n obot/run.sh
```

Container checks use disposable data and synthetic credentials. Run them on an amd64 Docker host:

```sh
docker build --build-arg BUILD_ARCH=amd64 -t ha-cliproxy-test cliproxyapi
python3 scripts/cliproxyapi-smoke.py
python3 scripts/retry_check.py
python3 scripts/diagnostics_compat.py
docker build --platform linux/amd64 --tag ha-obot:test obot
python3 scripts/obot-smoke.py --image ha-obot:test
```

These checks do not use your Home Assistant, Jira, or provider accounts. Test installation and account preservation on the target Home Assistant device after migration.

The wrapper code and starter skill use the MIT license. Upstream images and bundled releases retain their own licenses and notices.
