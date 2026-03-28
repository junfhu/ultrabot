"""Expert system -- domain-specialist personas with real agent capabilities.

Converts the 187 markdown persona definitions from `agency-agents-zh
<https://github.com/jnMetaCode/agency-agents-zh>`_ into real ultrabot agents
with tool access, memory, autonomous planning, and multi-channel support.
"""

from ultrabot.experts.parser import ExpertPersona, parse_persona_file, parse_persona_text
from ultrabot.experts.registry import ExpertRegistry
from ultrabot.experts.router import ExpertRouter, RouteResult

__all__ = [
    "ExpertPersona",
    "ExpertRegistry",
    "ExpertRouter",
    "RouteResult",
    "parse_persona_file",
    "parse_persona_text",
]
