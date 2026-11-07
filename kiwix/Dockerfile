FROM ghcr.io/kiwix/kiwix-serve:3.8.2

# The upstream image drops to an unprivileged user; the app needs root to
# write ZIM files into the shared /share volume.
USER root
RUN apk add --no-cache python3

WORKDIR /app
COPY manager.py ./
COPY web ./web

EXPOSE 8080 8099
ENTRYPOINT ["/usr/bin/dumb-init", "--", "python3", "-u", "/app/manager.py"]
