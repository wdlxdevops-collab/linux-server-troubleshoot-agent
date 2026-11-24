# Disposable "server" the agent investigates. Never point the agent at your real host.
FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
    && apt-get install -y --no-install-recommends apache2 procps iproute2 net-tools curl wget netcat-openbsd ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Avoid the "Could not reliably determine the server's FQDN" warning.
RUN echo "ServerName localhost" > /etc/apache2/conf-available/servername.conf \
    && a2enconf servername >/dev/null

# Keep the container alive even when apache2 is stopped, so the agent can inspect it.
CMD ["sleep", "infinity"]
