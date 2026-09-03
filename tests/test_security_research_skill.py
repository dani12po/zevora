"""Tests for the bundled defensive security-research skill."""
from agent.skills.registry import SkillRegistry
from agent.skills.security_research import (
    SKILL_ID,
    SECURITY_RESEARCH_CAPABILITIES,
    build_security_research_skill,
)


def test_security_research_skill_is_trusted_and_bounded():
    skill = build_security_research_skill()
    assert skill.skill_id == SKILL_ID
    assert skill.trust_state == 'trusted'
    assert skill.source == 'local'
    # Bounded by the registry's instruction cap.
    assert len(skill.instructions) <= 8_000
    # Defensive-only: must not instruct the agent to bypass safety boundaries
    # or generate offensive malware/evasion tooling. The skill may mention
    # those terms only inside explicit "do not" prohibitions.
    lowered = skill.instructions.lower()
    assert 'approval' in lowered
    assert 'authoriz' in lowered
    assert 'do not produce offensive malware' in lowered
    assert 'do not' in lowered
    # It must not instruct evasion of defensive controls.
    assert 'evade' not in lowered
    assert 'bypass av' not in lowered


def test_security_research_skill_matches_security_prompts():
    registry = SkillRegistry()
    registry.register(build_security_research_skill(), replace=True)
    context, used = registry.context_for(
        'Help me run an authorized vulnerability scan and harden my server',
        capabilities={'security'},
    )
    assert SKILL_ID in used
    assert 'security' in context.lower()


def test_security_research_skill_exposes_expected_capabilities():
    skill = build_security_research_skill()
    assert 'security' in skill.capabilities
    assert 'hardening' in skill.capabilities
    assert set(skill.capabilities) == set(SECURITY_RESEARCH_CAPABILITIES)
