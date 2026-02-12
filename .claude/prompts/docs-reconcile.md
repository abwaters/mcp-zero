# Claude Prompt: Full Documentation Reconciliation for mcp-zero

You are responsible for fully reconciling and updating the documentation of the `mcp-zero` repository so that it accurately reflects the current state of the codebase.

This is not a light edit. This is a structural, technical, and semantic alignment exercise.

---

## Objective

Bring **all documentation in the repository** into complete alignment with the current implementation.

This includes:

* Every markdown file in the repository (regardless of location)
* Root-level documentation files
* AI-assistant guidance files (e.g., CLAUDE.md or equivalent)
* Any design, PRD, architecture, threat model, comparison, or positioning documents

Do not assume the set of files is fixed. Files may have been added, renamed, or removed. Work from the current repository state.

The **codebase is the source of truth.**

---

# Phase 1 — Extract Truth From Code

Before editing any documentation, you must:

1. Inventory all implemented features.
2. Identify all configuration fields and defaults.
3. Identify all supported transports and execution modes.
4. Identify identity handling logic and validation behavior.
5. Identify policy evaluation semantics (ordering, deny/allow rules, fallback behavior).
6. Identify masking/redaction behavior and failure modes.
7. Identify audit logging behavior and logged fields.
8. Identify analytics or metrics behavior (if implemented).
9. Identify plugin or extension architecture (if implemented).
10. Identify strict vs legacy modes (if applicable).

Explicitly determine:

* What is implemented
* What is partially implemented
* What is planned but not implemented
* What was removed but may still be described in docs

---

# Phase 2 — Detect Documentation Drift

For every documentation file:

Check for:

* Claims that no longer match the code
* Missing documentation for newly added features
* Inconsistent terminology across files
* Overstated security claims
* Incorrect transport descriptions
* Identity flow inconsistencies
* Incorrect policy schema examples
* Architecture diagrams that no longer match flow
* Features described as enforced when they are observational
* “Planned” items that are already implemented
* “Implemented” items that are no longer present

---

# Phase 3 — Normalize Terminology

Standardize language across all documentation.

Ensure consistent definitions for:

* Self-hosted vs hosted
* Enforcement vs observability
* Hard enforcement vs advisory logging
* Streamable HTTP vs SSE vs stdio
* Token forwarding vs OBO token exchange
* Policy engine semantics
* Secure default posture
* Fail-open vs fail-closed behavior
* Identity validation vs identity propagation

If a term appears in multiple files, it must mean the same thing everywhere.

---

# Phase 4 — Update Documentation

Perform the following actions:

### 1. Rewrite where necessary

If a document is structurally outdated, rewrite it completely.

### 2. Update examples

Ensure:

* All configuration examples match actual schema
* YAML examples reflect current required fields
* Environment variable names match code
* Diagrams reflect actual flow

### 3. Clarify enforcement boundaries

Explicitly document:

* What the gateway enforces
* What it does not enforce
* What requires traffic to pass through it
* What cannot be controlled downstream

### 4. Correct security posture

Remove exaggerated claims.
Prefer precise, testable statements.

For example:

* Acceptable: "The gateway enforces policy evaluation for requests routed through it."
* Not acceptable: "Prevents all data exfiltration."

### 5. Update architectural descriptions

Ensure architecture diagrams (including mermaid diagrams) match actual request flow.

### 6. Update PRD-style documents

Clearly separate:

* Implemented scope
* In-progress scope
* Planned scope

### 7. Update comparison documents

Ensure comparisons reflect:

* Current feature set
* Current enforcement model
* Accurate positioning

If claims are speculative or require verification, mark them clearly.

### 8. Update AI assistant guidance files

Ensure they:

* Instruct future contributors not to overstate security
* Explain how to maintain consistency
* Include a checklist for changes affecting identity, policy, masking, audit, or transports

---

# Phase 5 — Consistency Audit

Before producing output, validate:

* No contradictions remain across documents
* Transport descriptions are identical everywhere
* Policy evaluation behavior is described consistently
* Security claims match implementation
* All examples compile logically against code
* Quickstart instructions would actually work

---

# Output Requirements

Return the following in this order:

1. High-level documentation changelog
2. File-by-file summary of changes with rationale
3. Patch-style diffs for all changed files

   * If diff is impractical, provide full rewritten files with clear file headers

Do not omit files that required changes.

---

# Non-Negotiable Rules

* The codebase is the source of truth.
* Do not introduce marketing claims unsupported by implementation.
* Prefer clarity over persuasion.
* Prefer explicit configuration over implied behavior.
* If behavior differs by mode, document both.
* If something is not implemented, say so clearly.

---

# Success Criteria

The documentation must:

* Accurately reflect the current repository state
* Be internally consistent
* Avoid overclaiming
* Be technically precise
* Be safe to publish in regulated environments
* Require no follow-up clarification for correctness

---

# Pull Request Requirement (Mandatory)

After completing all documentation updates:

1. Create a new branch for the documentation reconciliation work.
2. Commit all changes with clear, structured commit messages.
3. Open a Pull Request against the main branch.
4. In the PR description, include:

   * A high-level summary of documentation drift discovered
   * A categorized list of changes (security, transports, policy, identity, masking, audit, analytics, plugins, etc.)
   * Any removed claims and why they were removed
   * Any newly documented features and where they are implemented in code
   * Any remaining gaps between implementation and documentation
5. Ensure the PR description explicitly confirms:

   * All documentation has been reconciled against the current codebase
   * No unsupported security or compliance claims remain
   * All examples match the current configuration schema

The task is not complete until the Pull Request is created and ready for review.

---

# Pull Request Review Checklist (Required in PR Description)

The PR description must include the following checklist and explicitly confirm each item:

## Documentation Accuracy

* [ ] All documentation has been reconciled against the current codebase.
* [ ] No claims exceed what is implemented.
* [ ] No outdated features remain described.
* [ ] All configuration examples match actual schema and defaults.
* [ ] All environment variable names match code.
* [ ] All quickstart instructions were validated against the current implementation.

## Security & Enforcement Integrity

* [ ] Enforcement boundaries are clearly and precisely stated.
* [ ] Observability is not described as enforcement.
* [ ] Fail-open / fail-closed behavior is accurately documented.
* [ ] Identity validation and token flow descriptions match actual logic.
* [ ] Masking/redaction behavior matches real execution paths.
* [ ] Audit logging descriptions reflect actual logged fields.
* [ ] No unsupported compliance or security guarantees are claimed.

## Transport & Execution Modes

* [ ] All supported transports are documented consistently.
* [ ] Differences between execution modes are clearly described.
* [ ] Architecture diagrams reflect real runtime request flow.

## Consistency & Terminology

* [ ] Terminology is consistent across all documents.
* [ ] No internal contradictions remain.
* [ ] Diagrams, examples, and text descriptions are aligned.

---

# CI Validation Requirement (Mandatory Before Merge)

The Pull Request must satisfy the following before approval:

* Markdown linting passes (if configured).
* Documentation builds successfully (if applicable).
* No broken internal links.
* No references to removed files.
* No references to deprecated configuration fields.
* Policy schema examples (if provided) validate against the current loader or schema validation logic.
* CLI examples match current command syntax.

If automated validation exists for configuration schema, examples must pass it.

The PR must not be merged until these checks pass.

---

# Scope Guardrail — Documentation-Only Reconciliation

This task is documentation reconciliation only.

* The PR must not modify runtime code.
* The PR must not introduce new features.
* The PR must not change behavior.
* The PR must not refactor implementation logic.

If implementation inconsistencies are discovered:

* Document them clearly in the PR description.
* Open a separate issue for code changes.
* Do not resolve them in this PR unless explicitly authorized.

The diff must be limited strictly to documentation files unless explicit authorization is provided.

This guardrail is required to preserve review clarity, compliance auditability, and separation of concerns.

Begin the reconciliation process now.
