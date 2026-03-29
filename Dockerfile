FROM python:3.11-alpine

SHELL ["/bin/sh", "-o", "pipefail", "-c"]

RUN apk add --no-cache \
    bash \
    curl \
    git \
    jq \
    openssh \
    openssl \
    ca-certificates \
    && rm -rf /var/cache/apk/*

# Install uv for dependency management
RUN pip install --no-cache-dir uv

# Copy dependency files
WORKDIR /app
COPY pyproject.toml ./

# Install dependencies using uv (from pyproject.toml, no lock file needed)
RUN uv pip install --system --no-cache -r pyproject.toml

# Copy application code
COPY main.py ./
RUN chmod +x main.py

# Cleanup
RUN rm -rf /tmp/* /var/tmp/*

CMD ["python3", "main.py"]