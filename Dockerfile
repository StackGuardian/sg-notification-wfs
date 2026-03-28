FROM python:3.11-alpine

SHELL ["/bin/sh", "-o", "pipefail", "-c"]

RUN apk add --no-cache \
    bash \
    curl \
    git \
    jq \
    openssh \
    openssl \
    ca-certificates

RUN pip install --no-cache-dir apprise jinja2

RUN rm -rf /var/cache/apk/* && \
    rm -rf /tmp/* && \
    rm -rf /var/tmp/*

WORKDIR /app

COPY main.py ./
RUN chmod +x main.py

CMD ["python3", "main.py"]