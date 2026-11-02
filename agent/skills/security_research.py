"""Bounded, defensive security-research skill for Zevora.

This adapts the operator-supplied ``update.txt`` persona into a skill that is
safe to load inside the agent: it keeps the useful security-research framing
(recon, vulnerability analysis, secure coding, detection, remediation) while
dropping instructions that would bypass Zevora's approval boundaries, generate
offensive malware, or evade defensive controls.

The skill is intentionally read-only guidance. It never instructs the agent to
run unapproved commands, craft payloads for unauthorized targets, or suppress
disclaimers/authorization checks required by the workspace security model.
"""
from __future__ import annotations

from dataclasses import dataclass

from .registry import Skill

SKILL_ID = 'security-research'

SECURITY_RESEARCH_INSTRUCTIONS = """You are assisting with authorized security research and defensive engineering.

Scope and safety:
- Only help with targets/systems the user explicitly owns or has written authorization to test.
- Keep all actions inside Zevora's approval boundaries: no unapproved file writes, terminal commands, or network operations.
- Prefer defensive outcomes: detection, hardening, secure design, remediation, and verification.
- Do not produce offensive malware (e.g. keyloggers, reverse shells, ransomware) or evasion tooling aimed at defeating AV/EDR/AMS on systems the user does not control.
- If a request lacks authorization context, ask for the scope before producing sensitive technical detail.

Working style:
- Think like a security engineer: creative, methodical, and evidence-based.
- Favor concrete, runnable examples over pseudocode when the user is testing their own environment.
- When relevant, prefer well-known, audited tooling (nmap, sqlmap, hashcat, impacket, nuclei, Semgrep, Bandit) and explain important arguments.
- For each finding, include: what it is, how to verify it safely, impact, and a concrete remediation.

Preferred techniques to teach/automate (defensive or authorized):
- Recon/OSINT on owned assets: subdomain enumeration, port/service fingerprinting, metadata review, secret scanning.
- Vulnerability analysis: explain CVEs, PoC behavior, and line-by-line exploit mechanics for education/hardening.
- Secure coding: input validation, authn/authz, secrets management, dependency hygiene.
- Detection & response: logging, alerting, YARA/Sigma-style indicators, audit trails.
- Remediation: patches, config hardening, least-privilege, and verification steps.

Output format:
- Use fenced code blocks with language tags.
- Keep technical notes short: usage, key arguments, and how to verify results.
- When a safer baseline and a more advanced/hardened variant exist, show the baseline first, then the enhanced option."""

SECURITY_RESEARCH_CAPABILITIES = (
    'security',
    'pentest',
    'recon',
    'osint',
    'vulnerability',
    'audit',
    'hardening',
    'secure-coding',
    'detection',
    'remediation',
)


@dataclass(frozen=True)
class SecurityResearchSkill:
    """Factory/metadata wrapper for the bundled security-research skill."""

    skill_id: str = SKILL_ID
    name: str = 'Security Research (Defensive)'
    version: str = '1.0.0'
    description: str = (
        'Authorized security research, recon, vulnerability analysis, secure '
        'coding, detection, and remediation guidance.'
    )
    capabilities: tuple[str, ...] = SECURITY_RESEARCH_CAPABILITIES
    instructions: str = SECURITY_RESEARCH_INSTRUCTIONS
    tool_requirements: tuple[str, ...] = ('terminal', 'filesystem')
    dependencies: tuple[str, ...] = ()
    confidence: float = 0.7
    source: str = 'local'
    trust_state: str = 'trusted'

    def to_skill(self) -> Skill:
        return Skill(
            skill_id=self.skill_id,
            name=self.name,
            version=self.version,
            description=self.description,
            capabilities=self.capabilities,
            instructions=self.instructions,
            tool_requirements=self.tool_requirements,
            dependencies=self.dependencies,
            confidence=self.confidence,
            source=self.source,
            trust_state=self.trust_state,
        )


def build_security_research_skill() -> Skill:
    """Return the normalized, register-ready security-research skill."""
    return SecurityResearchSkill().to_skill()
