"""Governance lifecycle hook — bridges PolicyEngine to the request pipeline."""

from __future__ import annotations

import logging

from mcp_zero.context import HookContext, PolicyDecision
from mcp_zero.governance.config import PolicyEffect
from mcp_zero.governance.engine import EvaluationResult, PolicyEngine, PolicyInput
from mcp_zero.pipeline.errors import ShortCircuitError
from mcp_zero.pipeline.hooks import LifecycleHook

logger = logging.getLogger(__name__)


class GovernanceHook(LifecycleHook):
    """Evaluates governance policies at POST_VALIDATION.

    Runs after IdentityHook has resolved user identity.  Builds a
    :class:`PolicyInput` from the hook context and delegates to the
    :class:`PolicyEngine` for an allow/deny decision.

    Fail-closed: if no identity is present the request is denied without
    consulting the engine.
    """

    def __init__(self, engine: PolicyEngine, *, identity_required: bool = True) -> None:
        self._engine = engine
        self._identity_required = identity_required

    async def on_post_validation(self, ctx: HookContext) -> HookContext:
        identity = ctx.request.identity
        correlation_id = ctx.request.correlation_id

        # When no identity provider is configured, evaluate policy with an
        # anonymous identity so that subject-free rules (e.g. default-allow
        # policies for local/demo usage) still work.  If an identity provider
        # *is* configured but the identity is missing, that means authentication
        # failed — deny (fail-closed).
        if identity is None and self._identity_required:
            logger.warning(
                "No authenticated identity — denying request "
                "(correlation_id=%s, server=%s, tool=%s)",
                correlation_id,
                ctx.server_name,
                ctx.tool_name,
            )
            raise ShortCircuitError("No authenticated identity", deny=True)

        user_id = identity.user_id if identity else "anonymous"
        groups = list(identity.groups) if identity else []

        policy_input = PolicyInput(
            user_id=user_id,
            groups=groups,
            mcp_server=ctx.server_name,
            tool=ctx.tool_name,
        )

        result: EvaluationResult = self._engine.evaluate(policy_input)

        if result.effect == PolicyEffect.ALLOW:
            logger.info(
                "Policy ALLOW: user=%s server=%s tool=%s policy_id=%s correlation_id=%s",
                user_id,
                ctx.server_name,
                ctx.tool_name,
                result.policy_id or "",
                correlation_id,
            )
            return ctx.evolve(
                policy_decision=PolicyDecision.ALLOW,
                policy_rule_id=result.policy_id or "",
            )

        # DENY
        reason = result.reason or "Denied by policy"
        logger.warning(
            "Policy DENY: user=%s server=%s tool=%s policy_id=%s correlation_id=%s reason=%s",
            user_id,
            ctx.server_name,
            ctx.tool_name,
            result.policy_id or "",
            correlation_id,
            reason,
        )
        raise ShortCircuitError(reason, deny=True)
