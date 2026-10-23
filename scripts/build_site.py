#!/usr/bin/env python3
"""Składa gotową witrynę OfficeCraft z szablonów i pobranych buildów.

    python3 scripts/build_site.py --out site-out [--config tools.txt]

Szablony leżą w katalogu site/:
    hub.template.html   -> strona główna
    tool.template.html  -> podstrona narzędzia (pasek + iframe)
    admin.template.html -> ukryta strona zarządzania
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import REPO_ROOT, esc, format_blurb, parse_config, read_manifest, render  # noqa: E402
from pwa import prepare_apps  # noqa: E402

SITE_TITLE = "OfficeCraft"
SITE_TAGLINE = "Narzędzia biurowe oraz CAD - wszystko działa w Twojej przeglądarce."

ROBOTS = """User-agent: *
Allow: /

User-agent: *
Disallow: {prefix}admin/
"""


def local_path(base: str, value: str) -> str:
    """Zamienia ścieżkę absolutną (``/apps/x/``) na relatywną do podkatalogu strony."""
    value = (value or "").strip()
    if not value:
        return ""
    if re.match(r"^(?:[a-z][a-z0-9+.-]*:)?//", value, re.IGNORECASE) or value.startswith("data:"):
        return value
    return base + value.lstrip("/")


def icon_html(info: Dict[str, Any], base: str, cls: str, fallback_cls: str) -> str:
    icon = local_path(base, info.get("icon") or "")
    if icon:
        return f'<img class="{cls}" src="{esc(icon)}" alt="" loading="lazy">'
    initial = esc(((info.get("label") or info.get("id") or "?")[:1]).upper())
    return f'<span class="{fallback_cls}">{initial}</span>'


FAVICON_SVG = (
    "%3Csvg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 32 32%22%3E"
    "%3Crect width=%2232%22 height=%2232%22 rx=%228%22 fill=%22%232f6df6%22/%3E"
    "%3Ctext x=%2216%22 y=%2222%22 font-family=%22sans-serif%22 font-weight=%22700%22"
    " font-size=%2220%22 fill=%22%23ffffff%22 text-anchor=%22middle%22%3EOC"
    "%3C/text%3E%3C/svg%3E"
)


def favicon_html(src: str) -> str:
    if src:
        return f'<link rel="icon" href="{esc(src)}" sizes="any">'
    return f'<link rel="icon" href="data:image/svg+xml,{FAVICON_SVG}">' 


def human_size(size: int) -> str:
    value = float(size or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1000 or unit == "GB":
            text = f"{value:.0f}" if unit == "B" else f"{value:.1f}"
            return f"{text.replace('.', ',')} {unit}"
        value /= 1000
    return f"{value:.1f} GB"


def plural_tools(count: int) -> str:
    """Polska odmiana: 1 narzędzie, 2 narzędzia, 5 narzędzi."""
    if count == 1:
        return "1 narzędzie"
    if count % 10 in (2, 3, 4) and count % 100 not in (12, 13, 14):
        return f"{count} narzędzia"
    return f"{count} narzędzi"


def format_time(value: str) -> str:
    if not value:
        return "—"
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value
    return stamp.astimezone().strftime("%d.%m.%Y %H:%M")


def tool_card(tool_id: str, info: Dict[str, Any], base: str = "") -> str:
    fallback = esc(((info.get("label") or tool_id)[:1]).upper())
    icon = local_path(base, info.get("icon") or "")
    if icon:
        plate = f'<img class="card-icon" src="{esc(icon)}" alt="" loading="lazy">'
    else:
        plate = f'<span class="card-icon card-icon--fallback">{fallback}</span>'

    blurb = info.get("blurb") or ""
    size = human_size(info.get("bytes") or 0)
    repo = (info.get("repo") or "").strip().removeprefix("https://").removeprefix("http://")
    repo = repo.removeprefix("github.com/")
    repo_text = f"github.com/{repo}" if repo else ""
    return f"""
      <a class="card" href="{esc(base)}tool/{esc(tool_id)}/">
        <div class="plate">{plate}</div>
        <div class="card-body">
          <h2>{esc(info.get('label') or tool_id)}</h2>
          <p class="card-blurb">{format_blurb(blurb)}</p>
          <div class="card-foot">
            <p class="card-meta">
              <span class="badge">v{esc(info.get('version') or '?')}</span>
              <span> {esc(repo_text)}</span>
            </p>
          </div>
        </div>
      </a>"""


def skipped_card(tool_id: str, reason: str) -> str:
    return f"""
      <div class="card card--disabled">
        <div class="plate"><span class="card-icon card-icon--fallback">?</span></div>
        <div class="card-body">
          <h2>{esc(tool_id)}</h2>
          <p class="card-blurb">{esc(reason or 'Ta wersja nie ma jeszcze kompilacji webowej.')}</p>
          <p class="card-meta"><span class="badge badge--muted">pominięte</span></p>
        </div>
      </div>"""


def build_tool_pages(site_dir: Path, out_dir: Path, manifest: Dict[str, Any]) -> None:
    template = (site_dir / "tool.template.html").read_text(encoding="utf-8")
    base = "../../"
    for tool_id, info in (manifest.get("tools") or {}).items():
        app_path = local_path(base, info.get("app_path") or f"/apps/{tool_id}/")
        if app_path and not app_path.endswith("/"):
            app_path += "/"
        context = {
            "BASE": base,
            "TOOL_ICON_HTML": icon_html(info, base, "bar-icon", "bar-icon--fallback"),
            "TOOL_FAVICON": favicon_html(local_path(base, info.get("icon") or "")),
            "SITE_TITLE": SITE_TITLE,
            "TOOL_ID": esc(tool_id),
            "TOOL_LABEL": esc(info.get("label") or tool_id),
            "TOOL_VERSION": esc(info.get("version") or "?"),
            "TOOL_BLURB": esc(info.get("blurb") or ""),
            "TOOL_PAGE_URL": esc(f"https://github.com/{info.get('repo')}"),
            "TOOL_PAGE_LABEL": esc((info.get("repo") or "").replace("/", "/")),
            "TOOL_APP_PATH": esc(app_path),
            "TOOL_TAG": esc(info.get("tag") or ""),
        }
        target = out_dir / "tool" / tool_id / "index.html"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(render(template, context), encoding="utf-8")


def detect_repository() -> str:
    """Wykrywa repozytorium 'owner/repo' (env albo zdal git)."""
    from_env = os.environ.get("GITHUB_REPOSITORY", "").strip()
    if from_env:
        return from_env
    try:
        result = subprocess.run(
            ["git", "config", "--get", "remote.origin.url"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=15,
        )
        match = re.search(r"github\.com[/:]([^/]+)/([^/]+?)(?:\.git)?$", result.stdout.strip())
        if match:
            return f"{match.group(1)}/{match.group(2)}"
    except Exception:  # noqa: BLE001
        pass
    return ""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", default="site-out", help="katalog wyjściowy witryny")
    parser.add_argument("--config", default=str(REPO_ROOT / "tools.txt"), help="plik z listą narzędzi")
    parser.add_argument("--site", default=str(REPO_ROOT / "site"), help="katalog z szablonami")
    args = parser.parse_args()

    out_dir = Path(args.out).resolve()
    site_dir = Path(args.site).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    manifest = read_manifest(out_dir / "manifest.json")
    tools: Dict[str, Any] = manifest.get("tools") or {}
    skipped: Dict[str, str] = manifest.get("skipped") or {}
    config = parse_config(Path(args.config))
    known_ids = [tool["id"] for tool in config]

    # --- strona główna
    cards: List[str] = []
    for tool_id in known_ids:
        if tool_id in tools:
            cards.append(tool_card(tool_id, tools[tool_id]))
        else:
            cards.append(skipped_card(tool_id, skipped.get(tool_id, "brak danych")))
    for tool_id, info in tools.items():
        if tool_id not in known_ids:
            cards.append(tool_card(tool_id, info))

    hub_context = {
        "BASE": "",
        "HUB_FAVICON": favicon_html(""),
        "SITE_TITLE": SITE_TITLE,
        "SITE_TAGLINE": esc(SITE_TAGLINE),
        "LAST_SYNC": esc(format_time(manifest.get("generated_at") or "")),
        "TOOL_COUNT": plural_tools(len(tools)),
    }
    hub_template = (site_dir / "hub.template.html").read_text(encoding="utf-8")
    (out_dir / "index.html").write_text(
        render(hub_template, hub_context, {"TOOL_CARDS": "\n".join(cards)}), encoding="utf-8"
    )

    # --- podstrony narzędzi
    build_tool_pages(site_dir, out_dir, manifest)
    prepare_apps(out_dir / "apps", tools)

    # --- strona admina
    admin_config = {
        "repository": detect_repository(),
        "workflow": os.environ.get("SYNC_WORKFLOW", "sync-tools.yml"),
        "ref": os.environ.get("GITHUB_REF_NAME", "main"),
        "tools": {
            tool_id: {
                "label": info.get("label"),
                "version": info.get("version"),
                "repo": info.get("repo"),
                "page": info.get("page"),
                "bytes": info.get("bytes") or 0,
            }
            for tool_id, info in tools.items()
        },
        "skipped": skipped,
        "manifest": {
            "generated_at": manifest.get("generated_at"),
            "site_url": manifest.get("site_url"),
        },
    }
    admin_template = (site_dir / "admin.template.html").read_text(encoding="utf-8")
    admin_context = {
        "BASE": "../",
        "SITE_TITLE": SITE_TITLE,
        "CONFIG_JSON": json.dumps(admin_config, ensure_ascii=False).replace("</", "<\\/"),
        "LAST_SYNC": esc(format_time(manifest.get("generated_at") or "")),
    }
    admin_dir = out_dir / "admin"
    admin_dir.mkdir(parents=True, exist_ok=True)
    (admin_dir / "index.html").write_text(render(admin_template, admin_context), encoding="utf-8")

    # --- assety, robots, .nojekyll
    assets_src = site_dir / "assets"
    if assets_src.exists():
        shutil.copytree(assets_src, out_dir / "assets", dirs_exist_ok=True)
    repo = detect_repository()
    prefix = f"/{repo.split('/')[1]}/" if "/" in repo else "/"
    (out_dir / "robots.txt").write_text(ROBOTS.format(prefix=prefix), encoding="utf-8")
    (out_dir / ".nojekyll").write_text("", encoding="utf-8")

    print(f"zbudowano witrynę: {len(tools)} narzędzi, {len(skipped)} pominiętych -> {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
