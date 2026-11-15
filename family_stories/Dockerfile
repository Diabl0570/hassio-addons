FROM python:3.13-alpine
WORKDIR /app
COPY proxy.py ./
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
LABEL io.hass.name="Donna, Ollie & Ava" \
      io.hass.description="Family stories through Home Assistant ingress" \
      io.hass.version="1.0.0" \
      io.hass.type="app"
EXPOSE 8099
ENTRYPOINT ["python3", "/app/proxy.py"]
