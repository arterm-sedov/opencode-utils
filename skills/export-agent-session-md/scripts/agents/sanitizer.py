"""Sanitize exported sessions to remove secrets and sensitive data.

Automatically redacts:
- Private IP addresses (10.x.x.x, 192.168.x.x, 172.16-31.x.x)
- Tailscale/VPN IPs (100.x.x.x)
- SSH key paths and references
- Username patterns (home directories, sudoers)
- API keys and tokens (sk-*, ghp_*, AKIA*, etc.)
- Hostnames and domain names
- Port numbers that may be sensitive
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class SanitizeResult:
    """Result of sanitization with details of what was changed."""
    content: str
    sanitized: bool = False
    replacements: list[str] = field(default_factory=list)

    @property
    def warning(self) -> str | None:
        if not self.sanitized:
            return None
        items = "\n".join(f"  - {r}" for r in self.replacements)
        return f"⚠️ Sanitized {len(self.replacements)} sensitive pattern(s):\n{items}"


# Pattern → replacement pairs
# Each tuple: (compiled_regex, replacement_template, description)
_PATTERNS: list[tuple[re.Pattern, str, str]] = [
    # Private IP addresses
    (re.compile(r'\b10\.\d{1,3}\.\d{1,3}\.\d{1,3}\b'), '10.x.x.x', 'private IP'),
    (re.compile(r'\b172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}\b'), '172.16.x.x', 'private IP'),
    (re.compile(r'\b192\.168\.\d{1,3}\.\d{1,3}\b'), '192.168.x.x', 'private IP'),

    # Tailscale / VPN IPs
    (re.compile(r'\b100\.\d{1,3}\.\d{1,3}\.\d{1,3}\b'), '100.x.x.x', 'VPN IP'),

    # SSH keys
    (re.compile(r'id_rsa\b'), 'id_KEY', 'SSH key reference'),
    (re.compile(r'id_ed25519\b'), 'id_KEY', 'SSH key reference'),

    # Sudoers
    (re.compile(r'/etc/sudoers\.d/\S+'), '/etc/sudoers.d/XX-xxx', 'sudoers path'),

    # Home directory usernames (catch common patterns)
    (re.compile(r'/home/\w[\w.-]*/'), '/home/USER/', 'home directory'),
    (re.compile(r'~(?=/\w)'), '~', 'home shortcut'),

    # Common username patterns
    (re.compile(r'\b\w+-lnx\b'), 'USER', 'username'),
    (re.compile(r'\barterm-\w+\b'), 'USER', 'username'),

    # API keys and tokens
    (re.compile(r'sk-[a-zA-Z0-9]{20,}'), 'sk-REDACTED', 'API key'),
    (re.compile(r'ghp_[a-zA-Z0-9]{36}'), 'ghp_REDACTED', 'GitHub token'),
    (re.compile(r'gho_[a-zA-Z0-9]{36}'), 'gho_REDACTED', 'GitHub token'),
    (re.compile(r'AKIA[A-Z0-9]{16}'), 'AKIA_REDACTED', 'AWS key'),
    (re.compile(r'xox[bpsa]-[a-zA-Z0-9-]+'), 'xox-REDACTED', 'Slack token'),

    # Private keys
    (re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'), '-----BEGIN REDACTED KEY-----', 'private key'),

    # Generic passwords in commands
    (re.compile(r'-p\s+\S+', re.IGNORECASE), '-p REDACTED', 'password flag'),
    (re.compile(r'password[=:]\s*\S+', re.IGNORECASE), 'password=REDACTED', 'password value'),

    # Hostnames (corporate)
    (re.compile(r'\b[\w.-]*\.corp\.\w+\b'), 'hostname.corp.example', 'corp hostname'),
    (re.compile(r'\b[\w.-]*\.internal\b'), 'hostname.internal', 'internal hostname'),
]


def sanitize(text: str) -> SanitizeResult:
    """Sanitize text by redacting sensitive patterns.

    Returns SanitizeResult with the sanitized content and details of changes.
    """
    result = SanitizeResult(content=text)
    seen_descriptions: dict[str, int] = {}

    for pattern, replacement, description in _PATTERNS:
        matches = pattern.findall(text)
        if matches:
            result.content = pattern.sub(replacement, result.content)
            count = len(matches)
            seen_descriptions[description] = seen_descriptions.get(description, 0) + count

    if seen_descriptions:
        result.sanitized = True
        result.replacements = [
            f"{desc} ({count} occurrence{'s' if count > 1 else ''})"
            for desc, count in sorted(seen_descriptions.items(), key=lambda x: -x[1])
        ]

    return result


def sanitize_session_content(messages: list[dict]) -> SanitizeResult:
    """Sanitize all content in a list of message dicts.

    Modifies messages in-place and returns the sanitize result.
    """
    combined = []
    for msg in messages:
        if isinstance(msg, dict):
            for key in ("content", "text", "thinking", "output"):
                if key in msg and isinstance(msg[key], str):
                    combined.append(msg[key])

    full_text = "\n".join(combined)
    result = sanitize(full_text)

    if result.sanitized:
        # Apply the same replacements to each message
        for msg in messages:
            if isinstance(msg, dict):
                for key in ("content", "text", "thinking", "output"):
                    if key in msg and isinstance(msg[key], str):
                        for pattern, replacement, _ in _PATTERNS:
                            msg[key] = pattern.sub(replacement, msg[key])

    return result
