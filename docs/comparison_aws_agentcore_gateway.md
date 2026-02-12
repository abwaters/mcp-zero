# comparison_aws_agentcore_gateway.md

## Gist (read this first)
**Choose AWS AgentCore Gateway over `mcp-zero`** when you want a fully managed AWS-native MCP gateway with zero-code tool creation from APIs and Lambda functions, Cedar-based policy enforcement, built-in identity credential management (AgentCore Identity), and deep integration with the broader AWS ecosystem (IAM, CloudWatch, Cognito, CloudTrail).

**Choose `mcp-zero` over AWS AgentCore Gateway** when you need a self-hosted, cloud-agnostic enterprise MCP gateway with built-in inline PII/secret masking, deterministic YAML/JSON policy files, and lightweight deployment without AWS lock-in or consumption-based pricing.

---

## Snapshot comparison

| Area | mcp-zero | AWS AgentCore Gateway |
|---|---|---|
| Primary focus | Self-hosted enterprise MCP governance gateway | Fully managed AWS MCP tool gateway and agent platform |
| Runtime/stack | Python service | AWS managed service (.NET/internal) |
| Policy model | Ordered allow/deny YAML/JSON rules tied to user/group/server/tool | Cedar-based policies with natural-language authoring option |
| Identity model | Okta OAuth2 with OBO token exchange | OAuth (Cognito/Okta/Auth0/custom), IAM, JWT; dedicated AgentCore Identity service |
| Data protection | Inline Presidio-based PII and secret masking on inputs/outputs | CloudWatch log-level PII masking; Bedrock Guardrails for content filtering |
| Hosting model | Self-hosted by enterprise (any cloud or on-prem) | AWS-managed service (consumption-based pricing) |
| License | Project license in this repo | Proprietary AWS service (sample code Apache-2.0; Cedar policy language open source) |

---

## Feature and use-case comparison

### 1) Architecture and operating model
- **mcp-zero:** compact, self-hosted gateway with a hook-based control path (identity, governance, masking, audit) deployed as a single Python service.
- **AWS AgentCore Gateway:** fully managed AWS service within the broader Bedrock AgentCore platform, encompassing Gateway, Identity, Policy, Runtime, Memory, and Observability as separately billable components.

**Where each excels**
- `mcp-zero`: teams wanting a self-contained, cloud-agnostic gateway they fully own and operate.
- `AWS AgentCore Gateway`: organizations already invested in AWS seeking managed infrastructure with zero-code tool creation from APIs, Lambda functions, and Smithy models.

### 2) Identity and authentication
- **mcp-zero:** Okta OAuth2 with on-behalf-of (OBO) token exchange for downstream MCP servers; identity claims mapped through the gateway.
- **AWS AgentCore Gateway:** dual-sided authentication model — inbound via OAuth (MCP spec-compliant), JWT, or IAM; outbound via IAM roles, API keys, or OAuth client credentials. Dedicated AgentCore Identity service provides agent-specific credential vaults with KMS encryption.

**Trade-off**
- AgentCore Gateway's identity model is broader and deeper within AWS, but couples you to AWS IAM and services.
- `mcp-zero`'s OBO model is simpler and provider-agnostic, fitting cleanly into existing enterprise IdP setups.

### 3) Authorization and policy
- **mcp-zero:** deterministic deny-by-default policy engine with ordered allow/deny rules in static YAML/JSON files scoped to user, group, server, and tool.
- **AWS AgentCore Gateway:** Cedar-based policy engine (AgentCore Policy) with fine-grained access control interceptors, natural-language policy authoring, and automated reasoning for safety validation.

**Trade-off**
- `mcp-zero` policies are simple, reviewable artifacts that compliance teams can audit directly.
- AgentCore Policy is more expressive (Cedar) and offers advanced features like NL-to-policy generation, but adds AWS service dependency and Cedar learning curve.

### 4) Data protection and masking
- **mcp-zero:** built-in inline Presidio masking for PII and secrets on both request inputs and response outputs, operating within the gateway data path.
- **AWS AgentCore Gateway:** PII masking is handled at the observability layer (CloudWatch data protection policies) rather than inline in the MCP data path. Content filtering is available separately via Bedrock Guardrails.

**Implication**
- `mcp-zero` masks data in-flight before it reaches downstream MCP servers, which is often required in regulated environments.
- AgentCore Gateway's masking operates on logs after the fact; inline content filtering requires configuring Bedrock Guardrails as a separate service.

### 5) Auditing and observability
- **mcp-zero:** structured audit logs with user attribution, correlation IDs, and policy decision records.
- **AWS AgentCore Gateway:** CloudWatch metrics and logs for all policy decisions, CloudTrail for identity events, and per-operation audit trails across Gateway, Identity, and Policy services.

**Where each excels**
- `mcp-zero`: self-contained audit trail without external service dependencies.
- `AWS AgentCore Gateway`: deep observability integration with the AWS monitoring ecosystem (CloudWatch, CloudTrail, X-Ray).

### 6) Tool creation and developer experience
- **mcp-zero:** proxy/gateway framework you configure with policy files; tools are existing MCP servers routed through the gateway.
- **AWS AgentCore Gateway:** zero-code MCP tool creation from OpenAPI specs, Lambda functions, and Smithy models; semantic tool search and discovery; SDK annotations for credential injection.

**Practical outcome**
- AgentCore Gateway significantly reduces boilerplate for creating and discovering MCP tools at scale.
- `mcp-zero` focuses on governing existing tools rather than creating them.

---

## Hosting model comparison

### mcp-zero
- Self-hosted in any environment (VM, container, Kubernetes, on-prem).
- No cloud vendor dependency; enterprise owns and operates the full stack.
- Predictable cost profile (no per-request billing).

### AWS AgentCore Gateway
- Fully managed AWS service with consumption-based pricing (per MCP operation).
- Serverless infrastructure with built-in scaling and availability.
- Requires AWS account and couples operational model to AWS service boundaries.
- Free tier available ($200 credits for new customers); Policy service free during preview.

---

## License comparison

- **mcp-zero:** see repository license.
- **AWS AgentCore Gateway:** proprietary AWS managed service. Cedar policy language is open source; sample code and MCP server are Apache-2.0. The Gateway service itself is not open source.

**Practical implication:** AgentCore Gateway is a commercial AWS service with pay-per-use pricing. Organizations cannot self-host, fork, or modify the gateway itself. Cedar's open-source nature provides some portability for policy logic.

---

## Recommended use-cases

### Prefer mcp-zero when
1. You need a cloud-agnostic, self-hosted MCP gateway without vendor lock-in.
2. You require inline PII/secret masking in the MCP data path (not just in logs).
3. You want simple, file-based policy artifacts that compliance teams can directly review.
4. You need lightweight deployment without consumption-based pricing.

### Prefer AWS AgentCore Gateway when
1. You are standardized on AWS and want managed MCP infrastructure with zero operational overhead.
2. You need zero-code tool creation from existing APIs, Lambda functions, or Smithy models.
3. You want Cedar-based policy expressiveness with natural-language authoring and automated reasoning.
4. You need deep integration with AWS identity (IAM, Cognito) and observability (CloudWatch, CloudTrail).

---

## Known limitations and caveats
- AgentCore Gateway is a rapidly evolving AWS service; features like AgentCore Policy are still in preview as of early 2026.
- Cost comparisons depend heavily on request volume and the number of AgentCore sub-services consumed.
- Re-verify current AWS documentation and pricing before implementation planning.

---

## Sources
- mcp-zero README: `README.md`
- AWS AgentCore Gateway overview: https://aws.amazon.com/bedrock/agentcore/
- AgentCore Gateway docs: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway.html
- AgentCore Policy docs: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy.html
- AgentCore Identity features: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/key-features-and-benefits.html
- AgentCore Gateway blog: https://aws.amazon.com/blogs/machine-learning/introducing-amazon-bedrock-agentcore-gateway-transforming-enterprise-ai-agent-tool-development/
- AgentCore Gateway interceptors: https://aws.amazon.com/blogs/machine-learning/apply-fine-grained-access-control-with-bedrock-agentcore-gateway-interceptors/
- AgentCore pricing: https://aws.amazon.com/bedrock/agentcore/pricing/
