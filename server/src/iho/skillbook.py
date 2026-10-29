"""The skills, served by the server itself: no plugin needed on the agent's side.

Each skill is package data under iho/skills: `<name>/SKILL.md` with a small frontmatter (name,
description, when, aliases, docs) and the step by step in Markdown. Support documents that several
skills share (the tracker protocol, the pitfalls) sit at the root of that folder and go out with the
skill that lists them in `docs`. Company values (name, domain, expected connectors) are `{{placeholders}}`
filled from the instance settings, never written in the text.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from importlib.resources import files as package_files
from typing import Any

from iho.config import Settings
from iho.errors import IhoError

_PLACEHOLDER = re.compile(r"\{\{\s*([a-z_]+)\s*\}\}")
_FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n", re.S)
_LIST_KEYS = ("aliases", "docs")


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    when: str
    aliases: tuple[str, ...]
    docs: tuple[str, ...]
    body: str


def _parse(text: str, where: str) -> Skill:
    m = _FRONTMATTER.match(text)
    if not m:
        raise ValueError(f"{where}: no frontmatter")
    meta: dict[str, str] = {}
    for line in m.group(1).splitlines():
        if line.strip():
            key, _, value = line.partition(":")
            meta[key.strip()] = value.strip()
    missing = {"name", "description", "when"} - meta.keys()
    if missing:
        raise ValueError(f"{where}: frontmatter without {', '.join(sorted(missing))}")
    lists = {k: tuple(x.strip() for x in meta.get(k, "").split(",") if x.strip()) for k in _LIST_KEYS}
    return Skill(name=meta["name"], description=meta["description"], when=meta["when"],
                 aliases=lists["aliases"], docs=lists["docs"], body=text[m.end():].lstrip("\n"))


def _key(name: str) -> str:
    return "-".join(name.strip().lstrip("/").lower().split())


class SkillBook:
    def __init__(self, settings: Settings):
        root = package_files("iho") / "skills"
        self.skills: dict[str, Skill] = {}
        self.docs: dict[str, str] = {}
        for node in sorted(root.iterdir(), key=lambda n: n.name):
            if node.is_dir() and (node / "SKILL.md").is_file():
                skill = _parse((node / "SKILL.md").read_text("utf-8"), f"skills/{node.name}/SKILL.md")
                self.skills[skill.name] = skill
            elif node.name.endswith(".md"):
                self.docs[node.name] = node.read_text("utf-8")
        self._names = {_key(s.name): s.name for s in self.skills.values()}
        for s in self.skills.values():
            for alias in s.aliases:
                self._names.setdefault(_key(alias), s.name)
            unknown = set(s.docs) - self.docs.keys()
            if unknown:
                raise ValueError(f"skill {s.name} lists missing docs: {', '.join(sorted(unknown))}")
        self.values = company_values(settings)

    def fill(self, text: str) -> str:
        return _PLACEHOLDER.sub(lambda m: self.values.get(m.group(1), m.group(0)), text)

    def list(self) -> dict[str, Any]:
        return {
            "skills": [{"name": s.name, "description": self.fill(s.description), "when": self.fill(s.when),
                        "aliases": list(s.aliases)} for s in self.skills.values()],
            "next": "os_get_skill(name) for the step by step, before acting.",
        }

    def get(self, name: str) -> dict[str, Any]:
        found = self._names.get(_key(name))
        if found is None:
            raise IhoError(404, "skill_not_found",
                           f"No skill {name!r}. Available: {', '.join(self.skills)}.")
        s = self.skills[found]
        return {
            "name": s.name,
            "description": self.fill(s.description),
            "when": self.fill(s.when),
            "text": self.fill(s.body),
            "docs": [{"name": d, "text": self.fill(self.docs[d])} for d in s.docs],
            "company": self.values,
        }

    def instructions(self) -> str:
        triggers = " ".join(f"{s.name}: {self.fill(s.when)}." for s in self.skills.values())
        return (
            "Skills: this company's rituals are served by this server. When the person says a trigger below "
            "or types the slash command, call os_get_skill with that name BEFORE anything else and follow it "
            "step by step, with the support docs it returns; do not run a ritual from memory. os_list_skills "
            f"lists them. Triggers: {triggers}"
        )


def company_values(settings: Settings) -> dict[str, str]:
    domain = settings.company_domain.strip().lower()
    if not domain and settings.allowed_domain_set:
        domain = sorted(settings.allowed_domain_set)[0]
    connectors = [c.strip() for c in settings.company_connectors.split(",") if c.strip()]
    return {
        "company": settings.company_name.strip() or "a empresa",
        "domain": domain or "(domínio não configurado)",
        "connectors": ", ".join(connectors) or "(nenhum configurado)",
        "meeting_notes": settings.company_meeting_notes.strip()
        or "as notas que a pessoa tiver (documento de notas no Drive, Granola)",
        "server": settings.normalized_public_url,
    }
