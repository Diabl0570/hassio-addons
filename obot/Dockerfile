FROM ghcr.io/obot-platform/obot:v0.26.3

USER 0
RUN apk add --no-cache jq openssl

COPY run.sh /usr/local/bin/ha-obot-entrypoint
RUN chmod 755 /usr/local/bin/ha-obot-entrypoint

LABEL io.hass.name="Obot MCP Gateway" \
      io.hass.description="Authenticated MCP gateway with skills" \
      io.hass.version="0.26.3-1" \
      io.hass.type="app" \
      io.hass.arch="amd64"

ENTRYPOINT ["/usr/local/bin/ha-obot-entrypoint"]
