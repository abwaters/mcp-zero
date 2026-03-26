# Presidio Masking Plugin

PII detection and redaction plugin powered by [Microsoft Presidio](https://microsoft.github.io/presidio/). Scans both request inputs and tool response outputs, replacing detected PII entities with masked placeholders.

## Entry Point

```
presidio-masking = "mcp_zero.plugins.presidio_masking:PresidioMaskingPlugin"
```

## Configuration

```yaml
plugins:
  - name: presidio-masking
    config:
      entities:           # Required: list of PII entity types to detect
        - PERSON
        - EMAIL_ADDRESS
        - PHONE_NUMBER
        - CREDIT_CARD
        - API_KEY
        - PASSWORD
      priority: 75        # Optional: hook priority (default: 75)
```

### Config Reference

| Key | Type | Required | Default | Description |
|---|---|---|---|---|
| `entities` | `list[str]` | Yes | -- | PII entity types to detect. Must be non-empty. |
| `priority` | `int` | No | `75` | Hook execution priority. Lower runs earlier. |

### Supported Entity Types

Presidio supports a wide range of entity types. Common ones:

| Entity | Detects |
|---|---|
| `PERSON` | Person names |
| `EMAIL_ADDRESS` | Email addresses |
| `PHONE_NUMBER` | Phone numbers |
| `CREDIT_CARD` | Credit card numbers |
| `API_KEY` | API keys and tokens |
| `PASSWORD` | Passwords |
| `IBAN_CODE` | International bank account numbers |
| `IP_ADDRESS` | IP addresses |
| `US_SSN` | US Social Security numbers |

See the [Presidio supported entities documentation](https://microsoft.github.io/presidio/supported_entities/) for the full list.

## Behavior

### Input Masking (`pre_masking` hook)

Recursively walks all string values in `request_payload` and replaces detected PII with masked placeholders before the request reaches the upstream MCP server.

### Output Masking (`post_masking` hook)

Recursively walks all string values in `response_payload` and masks PII in tool responses before they reach the client.

### Fail-Closed

If the masking engine encounters an error:
- **Input stage**: The request is denied via `ShortCircuitError`
- **Output stage**: The response is blocked

This ensures PII is never leaked due to a masking failure.

## Example

Policy file that masks PII on all traffic to a filesystem server:

```yaml
version: 1
default: allow

servers:
  - name: filesystem
    transport: stdio
    command: npx
    args: ["-y", "@modelcontextprotocol/server-filesystem", ".data"]

policies:
  - id: allow-all
    effect: allow
    mcp_servers:
      - name: filesystem
        tools: ["*"]

plugins:
  - name: presidio-masking
    config:
      entities:
        - PERSON
        - EMAIL_ADDRESS
        - PHONE_NUMBER
        - CREDIT_CARD
        - API_KEY
        - PASSWORD
```

Before reaching the MCP server, a request containing `"Send to john@example.com"` becomes `"Send to <EMAIL_ADDRESS>"`.
