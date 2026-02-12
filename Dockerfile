FROM python:3.12-slim AS builder

WORKDIR /app

# Install Node.js (needed for npx-based stdio MCP servers)
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    curl -fsSL https://deb.nodesource.com/setup_22.x | bash - && \
    apt-get install -y --no-install-recommends nodejs && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Copy source and install
COPY pyproject.toml ./
COPY src/ src/
RUN pip install --no-cache-dir .

# Copy policy files
COPY policies/ policies/

EXPOSE 8080

ENV MCP_HOST=0.0.0.0
ENV MCP_PORT=8080
ENV MCP_POLICY_FILE=policies/everything.yaml

CMD ["mcp-zero"]
