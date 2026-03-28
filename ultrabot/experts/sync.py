"""Sync expert personas from the agency-agents-zh GitHub repository."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen
from urllib.error import URLError

from loguru import logger

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REPO_OWNER = "jnMetaCode"
REPO_NAME = "agency-agents-zh"
BRANCH = "main"
RAW_BASE = f"https://raw.githubusercontent.com/{REPO_OWNER}/{REPO_NAME}/{BRANCH}"
API_TREE = (
    f"https://api.github.com/repos/{REPO_OWNER}/{REPO_NAME}"
    f"/git/trees/{BRANCH}?recursive=1"
)

# Directories that contain persona .md files.
PERSONA_DIRS = frozenset({
    "academic", "design", "engineering", "finance", "game-development",
    "hr", "integrations", "legal", "marketing", "paid-media", "product",
    "project-management", "sales", "spatial-computing", "specialized",
    "supply-chain", "support", "testing",
})


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def sync_personas(
    dest_dir: Path,
    *,
    departments: set[str] | None = None,
    force: bool = False,
    progress_callback: Any = None,
) -> int:
    """Download persona ``.md`` files from GitHub to *dest_dir*.

    Parameters
    ----------
    dest_dir:
        Local directory where ``.md`` files will be saved.
    departments:
        Optional filter -- only download experts from these departments.
        ``None`` means all.
    force:
        Re-download even if a file already exists locally.
    progress_callback:
        Optional ``callable(current, total, filename)`` for UI progress.

    Returns
    -------
    int
        Number of files downloaded.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)

    # 1. Fetch the repository tree.
    logger.info("Fetching repository tree from GitHub ...")
    try:
        tree = _fetch_tree()
    except Exception as exc:
        logger.error("Failed to fetch repo tree: {}", exc)
        raise RuntimeError(f"Cannot reach GitHub API: {exc}") from exc

    # 2. Filter to persona .md files.
    files = _filter_persona_files(tree, departments)
    total = len(files)
    logger.info("Found {} persona files to sync", total)

    if total == 0:
        return 0

    # 3. Download each file.
    downloaded = 0
    for idx, file_path in enumerate(files, 1):
        filename = Path(file_path).name
        local_path = dest_dir / filename

        if local_path.exists() and not force:
            logger.debug("Skipping {} (already exists)", filename)
            if progress_callback:
                progress_callback(idx, total, filename)
            continue

        try:
            content = _fetch_raw_file(file_path)
            local_path.write_text(content, encoding="utf-8")
            downloaded += 1
            logger.debug("Downloaded {}", filename)
        except Exception:
            logger.exception("Failed to download {}", file_path)

        if progress_callback:
            progress_callback(idx, total, filename)

    logger.info("Synced {}/{} persona files to {}", downloaded, total, dest_dir)
    return downloaded


async def async_sync_personas(
    dest_dir: Path,
    **kwargs: Any,
) -> int:
    """Async wrapper around :func:`sync_personas` (runs in executor)."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None, lambda: sync_personas(dest_dir, **kwargs)
    )


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _fetch_tree() -> list[dict[str, Any]]:
    """Fetch the full recursive file tree from the GitHub API."""
    req = Request(API_TREE, headers={"Accept": "application/json"})
    with urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data.get("tree", [])


def _filter_persona_files(
    tree: list[dict[str, Any]],
    departments: set[str] | None,
) -> list[str]:
    """Return paths of persona .md files from the tree listing."""
    files: list[str] = []
    for item in tree:
        if item.get("type") != "blob":
            continue
        path = item.get("path", "")
        if not path.endswith(".md"):
            continue

        parts = path.split("/")
        if len(parts) != 2:
            continue

        dept = parts[0]
        filename = parts[1]

        if dept not in PERSONA_DIRS:
            continue
        if departments and dept not in departments:
            continue
        if filename.startswith("_") or filename.upper() == "README.MD":
            continue

        files.append(path)

    return sorted(files)


def _fetch_raw_file(path: str) -> str:
    """Download a single raw file from the repo."""
    url = f"{RAW_BASE}/{path}"
    req = Request(url)
    with urlopen(req, timeout=15) as resp:
        return resp.read().decode("utf-8")
