FROM samanhappy/mcphub:1.2.3@sha256:c7fa512abc83b6ba99054c8a2bad555889dfb8b6c708d6e2e45ba44d04c35639

COPY run.py /usr/local/lib/ha-mcphub/run.py

LABEL io.hass.name="MCPHub" \
      io.hass.description="One authenticated MCP endpoint with tool groups and per-key access" \
      io.hass.version="1.2.3-1" \
      io.hass.type="app" \
      io.hass.arch="amd64"

# The wrapper starts the image's original entrypoint and command itself.
ENTRYPOINT ["python3", "/usr/local/lib/ha-mcphub/run.py"]
CMD []
