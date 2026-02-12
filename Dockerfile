FROM python:3.12-slim AS builder

WORKDIR /app

# Install Node.js (needed for npx-based stdio MCP servers)
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    curl -fsSL https://deb.nodesource.com/setup_22.x | bash - && \
    apt-get install -y --no-install-recommends nodejs && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Install Python dependencies first for layer caching
COPY pyproject.toml ./
RUN pip install --no-cache-dir .

# Copy source and install in editable mode
COPY src/ src/
RUN pip install --no-cache-dir -e .

# Copy policy files
COPY policies/ policies/

EXPOSE 8080

ENV MCP_HOST=0.0.0.0
ENV MCP_PORT=8080
ENV MCP_POLICY_FILE=policies/everything.yaml

CMD ["mcp-zero"]
