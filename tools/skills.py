"""Skills tool — browse and run step-by-step skill scripts stored in skills/*.md.

Each skill is a plain Markdown file: a # heading, a description, and numbered
steps that the model should execute in sequence using its other tools.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from tools.registry import register

_IAGENT_HOME = Path(os.environ.get("IAGENT_HOME", Path.home() / ".iagent"))

# Skills can live in the code dir OR in IAGENT_HOME/skills (user-created)
def _skill_dirs() -> list[Path]:
    dirs = []
    # Installed code directory: same dir as this file's parent
    code_skills = Path(__file__).parent.parent / "skills"
    if code_skills.exists():
        dirs.append(code_skills)
    # User skill directory (persists across updates)
    user_skills = _IAGENT_HOME / "skills"
    if user_skills.exists():
        dirs.append(user_skills)
    return dirs


def _all_skills() -> dict[str, Path]:
    """Return {slug: path} for every skill. User skills shadow code skills."""
    found: dict[str, Path] = {}
    for d in _skill_dirs():
        for p in sorted(d.glob("*.md")):
            slug = p.stem.lower()
            found[slug] = p
    return found


def _slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9_-]", "_", name.strip().lower())


# ── Tools ────────────────────────────────────────────────────────────────

@register({
    "name": "list_skills",
    "description": (
        "List all available skills. Each skill is a named procedure the agent "
        "can follow to accomplish a task (e.g. battery, disk_usage, wifi_info). "
        "Returns a bullet list of skill names and their one-line descriptions."
    ),
    "parameters": {"type": "object", "properties": {}, "required": []},
})
async def list_skills() -> str:
    skills = _all_skills()
    if not skills:
        return "No skills found. Create one with write_skill."
    lines = []
    for slug, path in sorted(skills.items()):
        text = path.read_text()
        # First non-empty line after the # heading is the description
        desc = ""
        for line in text.splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                desc = line
                break
        lines.append(f"• **{slug}** — {desc}")
    return "\n".join(lines)


@register({
    "name": "view_skill",
    "description": (
        "Read the full content of a skill so the agent knows what steps to execute. "
        "Call list_skills first to discover available names."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Skill name (e.g. 'battery')"},
        },
        "required": ["name"],
    },
})
async def view_skill(name: str) -> str:
    slug = _slugify(name)
    skills = _all_skills()
    if slug not in skills:
        available = ", ".join(sorted(skills)) or "none"
        return f"Skill '{name}' not found. Available: {available}"
    return skills[slug].read_text()


@register({
    "name": "write_skill",
    "description": (
        "Create or update a skill. Skills are Markdown files stored in "
        "$IAGENT_HOME/skills/<name>.md. Use this to teach yourself new procedures "
        "that persist across conversations."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Skill name slug (letters, digits, underscores, hyphens)",
            },
            "content": {
                "type": "string",
                "description": (
                    "Full Markdown content. Start with '# <name>', then a one-line "
                    "description, then '## Steps' with numbered steps."
                ),
            },
        },
        "required": ["name", "content"],
    },
})
async def write_skill(name: str, content: str) -> str:
    slug = _slugify(name)
    if not slug:
        return "Invalid skill name."
    user_dir = _IAGENT_HOME / "skills"
    user_dir.mkdir(parents=True, exist_ok=True)
    path = user_dir / f"{slug}.md"
    path.write_text(content)
    return f"Skill '{slug}' saved to {path}"
