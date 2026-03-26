"""General-purpose utility helpers for the ultrabot framework."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from loguru import logger


# ---------------------------------------------------------------------------
# Workspace template sync
# ---------------------------------------------------------------------------


def sync_workspace_templates(workspace_path: Path) -> None:
    """Copy bundled template files into *workspace_path* if they are missing.

    Templates are located in ``ultrabot/templates/`` relative to this package.
    Only files that do not yet exist in the target workspace are copied.
    """
    templates_dir = Path(__file__).resolve().parent.parent / "templates"
    if not templates_dir.is_dir():
        logger.debug("No templates directory found at {}", templates_dir)
        return

    workspace_path.mkdir(parents=True, exist_ok=True)
    for src in templates_dir.rglob("*"):
        if not src.is_file():
            continue
        rel = src.relative_to(templates_dir)
        dest = workspace_path / rel
        if dest.exists():
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        logger.debug("Synced template {} -> {}", rel, dest)


# ---------------------------------------------------------------------------
# Token estimation
# ---------------------------------------------------------------------------


def estimate_tokens(text: str) -> int:
    """Return a rough token count for *text*.

    Uses the simple heuristic of ``len(text) / 4`` which is a reasonable
    approximation for English text across most tokenisers.
    """
    return max(1, len(text) // 4)


# ---------------------------------------------------------------------------
# Text truncation
# ---------------------------------------------------------------------------


def truncate_content(content: str, max_chars: int = 50000) -> str:
    """Truncate *content* to at most *max_chars*, appending ``...`` if cut."""
    if len(content) <= max_chars:
        return content
    return content[: max_chars - 3] + "..."


# ---------------------------------------------------------------------------
# Safe JSON parsing
# ---------------------------------------------------------------------------


def safe_json_loads(text: str) -> Any:
    """Parse *text* as JSON, falling back to ``json_repair`` if possible.

    If the standard ``json.loads`` fails, we try the ``json_repair`` library.
    If that is not available either, we re-raise the original error.
    """
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    try:
        from json_repair import repair_json

        repaired = repair_json(text, return_objects=True)
        return repaired
    except ImportError:
        logger.debug("json_repair not installed -- cannot attempt repair")
    except Exception:
        logger.debug("json_repair failed on input")

    # Last resort -- try stripping common wrapper artifacts.
    stripped = text.strip()
    if stripped.startswith("```"):
        # Remove markdown code fences.
        lines = stripped.splitlines()
        lines = [l for l in lines if not l.strip().startswith("```")]
        stripped = "\n".join(lines)
    return json.loads(stripped)


# ---------------------------------------------------------------------------
# Tool result formatting
# ---------------------------------------------------------------------------


def format_tool_result(result: Any, max_length: int = 50000) -> str:
    """Convert an arbitrary tool result to a string suitable for the LLM.

    Parameters
    ----------
    result:
        The raw result from a tool execution.  May be a string, dict, list,
        or any JSON-serialisable object.
    max_length:
        Maximum character length of the returned string.
    """
    if isinstance(result, str):
        text = result
    elif isinstance(result, (dict, list)):
        try:
            text = json.dumps(result, indent=2, default=str, ensure_ascii=False)
        except (TypeError, ValueError):
            text = str(result)
    else:
        text = str(result)

    return truncate_content(text, max_length)
