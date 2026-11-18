FROM alpine:3.22

RUN apk add --no-cache openssh-client
RUN adduser -D -u 1000 ollama-tunnel

COPY entrypoint.sh /usr/local/bin/ollama-tunnel
RUN chmod 0555 /usr/local/bin/ollama-tunnel

USER 1000:1000
ENTRYPOINT ["/usr/local/bin/ollama-tunnel"]
