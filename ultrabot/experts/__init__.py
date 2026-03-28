"""Expert system -- domain-specialist personas with real agent capabilities.

Converts the 187 markdown persona definitions from `agency-agents-zh
<https://github.com/jnMetaCode/agency-agents-zh>`_ into real ultrabot agents
with tool access, memory, autonomous planning, and multi-channel support.

The package ships with bundled persona files under ``personas/`` so that
experts work out of the box without requiring a ``sync`` step.
"""

from pathlib import Path

from ultrabot.experts.parser import ExpertPersona, parse_persona_file, parse_persona_text
from ultrabot.experts.registry import ExpertRegistry
from ultrabot.experts.router import ExpertRouter, RouteResult

#: Path to the bundled persona markdown files shipped with the package.
BUNDLED_PERSONAS_DIR: Path = Path(__file__).parent / "personas"

__all__ = [
    "BUNDLED_PERSONAS_DIR",
    "ExpertPersona",
    "ExpertRegistry",
    "ExpertRouter",
    "RouteResult",
    "parse_persona_file",
    "parse_persona_text",
]
