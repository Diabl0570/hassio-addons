#!/bin/bash
set -euo pipefail

unset SUPERVISOR_TOKEN HASSIO_TOKEN

configure_obot() {
    local data_dir="$1" server_url bootstrap_token temporary
    local options_file="$data_dir/options.json"

    if ! jq -e '
        type == "object" and
        ((keys - ["server_url", "bootstrap_token"]) | length == 0) and
        (.server_url | type == "string") and
        (if has("bootstrap_token") then
            (.bootstrap_token | type == "string" and
             (length == 0 or (length >= 6 and test("\\A[!-~]+\\z"))))
         else true end)
    ' "$options_file" >/dev/null 2>&1; then
        echo "Invalid app options. Set server_url and an optional bootstrap_token." >&2
        return 1
    fi

    if ! jq -e '
        def ipv6:
            .[1:-1] | split("::") as $parts |
            ($parts | map(if . == "" then [] else split(":") end) | add) as $groups |
            ($parts | length) <= 2 and
            all($groups[]; test("^[0-9a-fA-F]{1,4}$")) and
            (if ($parts | length) == 1 then ($groups | length) == 8
             else ($groups | length) < 8 end);
        .server_url | capture("\\Ahttps?://(?<host>[a-zA-Z0-9.-]+|\\[[0-9a-fA-F:]+\\])(?::(?<port>[0-9]+))?\\z") |
        (.host | if startswith("[") then ipv6 else
            length <= 253 and
            test("^[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(\\.[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*$")
         end) and
        (if .port == null then true else (.port | tonumber) >= 1 and (.port | tonumber) <= 65535 end)
    ' "$options_file" >/dev/null 2>&1; then
        echo "server_url must be an absolute HTTP(S) origin without credentials, path, query, or fragment." >&2
        return 1
    fi
    server_url=$(jq -r '.server_url' "$options_file")

    if [[ ! -e "$data_dir/encryption.yaml" && -e "$data_dir/postgresql/PG_VERSION" ]]; then
        echo "The existing database is missing its encryption configuration. Restore encryption.yaml from backup." >&2
        return 1
    fi

    umask 077
    bootstrap_token=$(jq -r '.bootstrap_token // ""' "$options_file")
    if [[ -z "$bootstrap_token" ]]; then
        if [[ ! -e "$data_dir/bootstrap-token" ]]; then
            temporary=$(mktemp "$data_dir/.bootstrap-token.XXXXXX")
            openssl rand -hex 32 >"$temporary"
            mv "$temporary" "$data_dir/bootstrap-token"
        fi
        if [[ ! -s "$data_dir/bootstrap-token" ]]; then
            echo "The saved bootstrap token is empty. Restore it from backup." >&2
            return 1
        fi
        bootstrap_token=$(cat "$data_dir/bootstrap-token")
    fi
    if ! jq -ne --arg token "$bootstrap_token" '$token | length >= 6 and test("\\A[!-~]+\\z")' >/dev/null; then
        echo "The bootstrap token must contain at least six visible ASCII characters." >&2
        return 1
    fi

    if [[ ! -e "$data_dir/encryption.yaml" ]]; then
        temporary=$(mktemp "$data_dir/.encryption.XXXXXX")
        openssl rand -base64 32 | jq -Rs '
            {
                apiVersion: "apiserver.config.k8s.io/v1",
                kind: "EncryptionConfiguration",
                resources: [{
                    resources: [
                        "credentials.obot.obot.ai", "users.obot.obot.ai", "identities.obot.obot.ai",
                        "mcpoauthtokens.obot.obot.ai", "mcpoauthpendingstates.obot.obot.ai",
                        "mcpauditlogs.obot.obot.ai", "llmauditlogs.obot.obot.ai",
                        "policyviolations.obot.obot.ai", "properties.obot.obot.ai"
                    ],
                    providers: [
                        {aesgcm: {keys: [{name: "key0", secret: rtrimstr("\n")}]}},
                        {identity: {}}
                    ]
                }]
            }
        ' >"$temporary"
        mv "$temporary" "$data_dir/encryption.yaml"
    fi
    if [[ ! -s "$data_dir/encryption.yaml" ]]; then
        echo "The saved encryption configuration is empty. Restore it from backup." >&2
        return 1
    fi
    chmod 600 "$data_dir/encryption.yaml"
    [[ ! -e "$data_dir/bootstrap-token" ]] || chmod 600 "$data_dir/bootstrap-token"

    export OBOT_SERVER_HOSTNAME="$server_url"
    export OBOT_BOOTSTRAP_TOKEN="$bootstrap_token"
    export OBOT_SERVER_ENABLE_AUTHENTICATION=true
    export OBOT_ENABLE_AGENTS=false
    export OBOT_SERVER_ENABLE_HOSTED_AGENTS=false
    export OBOT_HOSTED_AGENTS_BACKEND=disabled
    export OBOT_SERVER_ENCRYPTION_PROVIDER=custom
    export OBOT_SERVER_ENCRYPTION_CONFIG_FILE="$data_dir/encryption.yaml"
    export DOCKER_HOST=unix:///run/docker.sock
}

main() {
    configure_obot /data
    exec /bin/run.sh
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    main
fi
