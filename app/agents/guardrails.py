import logging
import re

logger = logging.getLogger(__name__)

# Simple blocklist for demo; replace with real moderation API in prod
_BLOCKED_PATTERNS = [
    r"\b(credit\s*card\s*number|ssn|social\s*security)\b",
    r"\b(how\s+to\s+make\s+bomb|instructions\s+for\s+illegal)\b",
]

_INJECTION_PATTERNS = [
    r"ignore\s+previous\s+instructions",
    r"system\s*:\s*you\s+are",
    r"jailbreak",
]


def check_moderation(text: str) -> tuple[bool, str]:
    """Returns (is_blocked, reason)."""
    lower = text.lower()
    for pat in _BLOCKED_PATTERNS:
        if re.search(pat, lower, re.IGNORECASE):
            return True, f"Blocked content pattern: {pat}"
    return False, ""


def check_injection(text: str) -> tuple[bool, str]:
    lower = text.lower()
    for pat in _INJECTION_PATTERNS:
        if re.search(pat, lower, re.IGNORECASE):
            return True, f"Potential prompt injection: {pat}"
    return False, ""


def apply_guardrails(agent_name: str, prompt: str) -> tuple[bool, str]:
    blocked, reason = check_moderation(prompt)
    if blocked:
        logger.warning(f"Guardrail blocked ({agent_name}): {reason}")
        return False, f"[Guardrail] Request blocked for {agent_name}: {reason}"
    injected, reason2 = check_injection(prompt)
    if injected:
        logger.warning(f"Guardrail injection detected ({agent_name}): {reason2}")
        # For injection we don't block but warn and sanitize
        # Sanitize by removing suspicious lines
        sanitized = re.sub(r"ignore previous.*", "", prompt, flags=re.IGNORECASE)
        return True, sanitized
    return True, prompt


def validate_agent_output(agent_name: str, output: str) -> tuple[bool, str]:
    # Check output moderation as well
    blocked, reason = check_moderation(output)
    if blocked:
        logger.warning(f"Guardrail blocked output ({agent_name}): {reason}")
        return False, f"[Guardrail] Output from {agent_name} blocked: policy violation"
    return True, output
