"""Wspólne narzędzia dla skryptów OfficeCraft (tylko biblioteka standardowa)."""

from __future__ import annotations

import html
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent

# Dzielniki dopuszczalne w identyfikatorze narzędzia (używany w ścieżkach URL).
ID_RE = re.compile(r"[^a-z0-9._-]+")


def slugify(value: str) -> str:
    """Zamienia dowolny tekst na bezpieczny identyfikator (np. do URL)."""
    value = ID_RE.sub("-", value.strip().lower()).strip("-._")
    return value or "narzedzie"


def esc(value: Any) -> str:
    """Escapuje tekst do wstawienia w HTML."""
    return html.escape(str(value), quote=True)


_ITALIC_RE = re.compile(r"\*([^\*\n]+)\*")


def format_blurb(value: str) -> str:
    """Eskapuje opis, zamienia *kursywę* na <em>kursywę</em> i nowe linie na <br>."""
    text = esc(value)
    text = _ITALIC_RE.sub(r"<em>\1</em>", text)
    return text.replace("\n", "<br>")


def parse_config(path: Path) -> List[Dict[str, Any]]:
    """Czyta plik konfiguracyjny narzędzi.

    Plik jest podzielony na akapity (bloki rozdzielone pustą linią). Każdy blok
    opisuje jedno narzędzie:

        https://github.com/storytold/pdfcraft
        Czytaj, porządkuj i zabezpieczaj pliki PDF - w przeglądarce.

    Pierwsza linia bloku to link do repozytorium (z opcjonalnymi ustawieniami
    po "|"), pozostałe linie to opis - mogą być zapisane w wielu wierszach,
    wtedy są sklejane spacją.

    Zwraca listę słowników z kluczami: id, owner, repo, source, blurb, overrides.
    """
    tools: List[Dict[str, Any]] = []
    seen: Dict[str, int] = {}

    text = Path(path).read_text(encoding="utf-8")
    text = "\n".join(line for line in text.splitlines() if not line.strip().startswith("#"))

    for block in re.split(r"\n\s*\n", text):
        block_lines = [line.strip() for line in block.splitlines() if line.strip()]
        if not block_lines:
            continue

        parts = [part.strip() for part in block_lines[0].split("|")]
        source = parts[0]
        overrides: Dict[str, str] = {}
        for part in parts[1:]:
            if "=" not in part:
                continue
            key, value = part.split("=", 1)
            key = key.strip().lower()
            if key:
                overrides[key] = value.strip()

        blurb = "\n".join(block_lines[1:]).strip()  # This joins with newlines!

        owner, repo = _split_repo(source, overrides)
        tool_id = slugify(overrides.get("id") or repo)

        # Dwa narzędzia o tym samym identyfikatorze? Dodajemy sufiks.
        if tool_id in seen:
            seen[tool_id] += 1
            tool_id = f"{tool_id}-{seen[tool_id]}"
        else:
            seen[tool_id] = 1

        tools.append(
            {
                "id": tool_id,
                "owner": owner,
                "repo": repo,
                "source": source,
                "blurb": blurb,
                "overrides": overrides,
            }
        )

    return tools


def _split_repo(source: str, overrides: Dict[str, str]) -> tuple:
    """Wyciąga owner/repo z linku, ścieżki "owner/repo" lub pola repo=."""
    if "repo" in overrides and "/" in overrides["repo"]:
        owner, repo = overrides["repo"].split("/", 1)
        return owner.strip(), repo.strip().removesuffix(".git")

    cleaned = source.strip()
    cleaned = re.sub(r"^git\+", "", cleaned)
    cleaned = re.sub(r"\.git$", "", cleaned)

    match = re.search(r"github\.com[/:]([^/]+)/([^/?#]+)", cleaned, re.IGNORECASE)
    if match:
        return match.group(1), match.group(2)

    if cleaned.count("/") == 1 and not cleaned.startswith(("http://", "https://")):
        owner, repo = cleaned.split("/", 1)
        return owner.strip(), repo.strip()

    raise ValueError(f"Nie umiem odczytać repozytorium z: {source!r}")


def render(template: str, context: Dict[str, str], blocks: Optional[Dict[str, str]] = None) -> str:
    """Podstawia {{KLUCZ}} oraz bloki <!--BLOCK:klucz--> w szablonie."""
    out = template
    for key, value in context.items():
        out = out.replace("{{" + key + "}}", str(value))
    for name, content in (blocks or {}).items():
        out = out.replace("<!--BLOCK:" + name + "-->", content)
    return out


def read_manifest(path: Path) -> Dict[str, Any]:
    """Wczytuje manifest z pliku (pusty manifest, gdy pliku nie ma)."""
    empty = {"generated_at": None, "site_url": "", "tools": {}, "skipped": {}}
    if not Path(path).exists():
        return empty
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return empty
    if not isinstance(data, dict):
        return empty
    data.setdefault("tools", {})
    data.setdefault("skipped", {})
    return data


def versions_map(manifest: Dict[str, Any]) -> Dict[str, str]:
    """Zwraca mapę {id: wersja} - to ją porównujemy, by wykryć zmiany."""
    return {
        tool_id: str(info.get("version", ""))
        for tool_id, info in (manifest.get("tools") or {}).items()
    }
