#!/usr/bin/env python3
"""Synchronizuje buildy webowe narzędzi z GitHuba do katalogu witryny.

    python3 scripts/sync_tools.py --out site-out [--config tools.txt]
                                   [--site-url https://owner.github.io/OfficeCraft/]
                                   [--state state/manifest.json] [--dry-run] [--force]

Przebieg:
  1. czyta listę narzędzi z pliku konfiguracyjnego (jedna linia = jeden link),
  2. pyta API GitHuba o najnowsze wydanie (zawsze wersja stable),
  3. porównuje wersję z wdrożoną (manifest z żywej strony albo plik --state),
  4. pobiera i rozpakowuje TYLKO narzędzia, których wersja się zmieniła,
  5. zapisuje manifest.json do katalogu wyjściowego.

Pliki są wgrywane na GitHub Pages przez akcję GitHub (deploy-pages).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (  # noqa: E402
    REPO_ROOT,
    parse_config,
    read_manifest,
    versions_map,
)

API = "https://api.github.com"
RAW = "https://raw.githubusercontent.com"
USER_AGENT = "OfficeCraft-sync/1.0"
CHUNK = 1 << 16


# ---------------------------------------------------------------- HTTP


def http_get(url: str, token: Optional[str] = None, timeout: int = 60) -> bytes:
    """Pobiera zasób (bez śledzenia przekierowań jest obsłużone automatycznie)."""
    headers = {"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def http_json(url: str, token: Optional[str] = None, timeout: int = 60) -> Dict[str, Any]:
    raw = http_get(url, token=token, timeout=timeout)
    return json.loads(raw.decode("utf-8"))


def http_status(url: str, timeout: int = 20) -> Optional[int]:
    """Zwraca kod HTTP albo None, gdy zasób nie istnieje / jest błąd sieci."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status
    except urllib.error.HTTPError as error:
        return error.code
    except Exception:
        return None


# ---------------------------------------------------------------- GitHub


def latest_release(owner: str, repo: str, token: Optional[str]) -> Dict[str, Any]:
    """Najnowsze wydanie stabilne (prerelease nigdy nie jest zwracane)."""
    return http_json(f"{API}/repos/{owner}/{repo}/releases/latest", token=token)


def repo_info(owner: str, repo: str, token: Optional[str]) -> Dict[str, Any]:
    try:
        return http_json(f"{API}/repos/{owner}/{repo}", token=token)
    except Exception:
        return {}


def pick_asset(release: Dict[str, Any], tool: Dict[str, Any], version: str) -> Optional[Dict[str, Any]]:
    """Wybiera asset z buildem webowym: '<id>-web-<wersja>.zip' lub dowolny '*-web-*.zip'."""
    assets = release.get("assets") or []
    tool_id = tool["id"]
    overrides = tool["overrides"]

    if "asset" in overrides:
        pattern = overrides["asset"].replace("{v}", version).replace("{id}", tool_id)
        for asset in assets:
            if asset.get("name") == pattern:
                return asset

    exact = f"{tool_id}-web-{version}.zip"
    for asset in assets:
        if asset.get("name") == exact:
            return asset

    for asset in assets:
        name = (asset.get("name") or "").lower()
        if name.endswith(".zip") and "-web-" in name:
            return asset
    return None


def build_present(build_dir: Path) -> bool:
    """Czy build narzędzia faktycznie leży na dysku (cache mógł nie wrócić)."""
    return build_dir.is_dir() and any(build_dir.iterdir())


def find_icon(tool: Dict[str, Any], build_dir: Optional[Path], out_dir: Path) -> Optional[str]:
    """Szuka ikrki narzędzia. Zwraca URL albo ścieżkę lokalną."""
    if "icon" in tool["overrides"]:
        return tool["overrides"]["icon"]

    tool_id = tool["id"]
    owner, repo = tool["owner"], tool["repo"]

    # 1. Ikona wewnątrz rozpakowanego builda (np. SolidCraft: icons/256x256/*.png)
    if build_dir and build_dir.exists():
        candidates = sorted(build_dir.glob("icons/**/*.png"))
        if not candidates:
            candidates = sorted(build_dir.glob("**/app-icon/*.png"))
        if candidates:
            best = max(candidates, key=lambda p: p.stat().st_size)
            target_dir = out_dir / "assets" / "icons"
            target_dir.mkdir(parents=True, exist_ok=True)
            target = target_dir / f"{tool_id}.png"
            shutil.copyfile(best, target)
            return f"/assets/icons/{tool_id}.png"

    # 2. Ikona w repozytorium (rodzina ArtCraft)
    raw_candidates = [
        f"{RAW}/{owner}/{repo}/main/assets/app-icon/hicolor/64x64/apps/ai.storyteller.{tool_id}.png",
        f"{RAW}/{owner}/{repo}/main/assets/app-icon/{tool_id}-64.png",
        f"{RAW}/{owner}/{repo}/main/assets/app-icon/{tool_id}.png",
    ]
    for url in raw_candidates:
        if http_status(url) == 200:
            return url
    return None


def _save_pwa_icon(data: bytes, target: Path) -> bool:
    """Zapisuje ikonę jako PNG 512x512. Bez Pillow akceptuje gotowy PNG."""
    try:
        import io

        from PIL import Image, ImageOps  # type: ignore[import-not-found]
    except ImportError:
        if not data.startswith(b"\x89PNG\r\n\x1a\n"):
            return False
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return True
    try:
        with Image.open(io.BytesIO(data)) as image:
            icon = ImageOps.pad(image.convert("RGBA"), (512, 512), color=(0, 0, 0, 0))
            target.parent.mkdir(parents=True, exist_ok=True)
            icon.save(target, format="PNG", optimize=True)
        return True
    except Exception:  # noqa: BLE001
        return False


def pwa_icon(tool: Dict[str, Any], build_dir: Optional[Path], out_dir: Path) -> Optional[str]:
    """Ikona 512 px do manifestu PWA, trzymana lokalnie (bez hotlinku)."""
    tool_id = tool["id"]
    rel = f"/assets/icons/{tool_id}-512.png"
    target = out_dir / "assets" / "icons" / f"{tool_id}-512.png"
    if target.is_file() and target.stat().st_size > 0:
        return rel

    override = (tool["overrides"].get("icon") or "").strip()
    if override.startswith(("http://", "https://")):
        try:
            data = http_get(override, timeout=30)
        except Exception:  # noqa: BLE001
            data = b""
        if data and _save_pwa_icon(data, target):
            return rel

    if build_dir and build_dir.is_dir():
        for pattern in ("icons/512x512/*.png", "**/512x512/*.png"):
            found = sorted(build_dir.glob(pattern))
            if found:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(found[0], target)
                return rel

    owner, repo = tool["owner"], tool["repo"]
    for url in (
        f"{RAW}/{owner}/{repo}/main/assets/app-icon/hicolor/512x512/apps/ai.storyteller.{tool_id}.png",
        f"{RAW}/{owner}/{repo}/main/assets/icons/app/linux/exports/hicolor/512x512/apps/ai.storyteller.{tool_id}.png",
    ):
        try:
            data = http_get(url, timeout=30)
        except Exception:  # noqa: BLE001
            continue
        if len(data) > 1000:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            return rel
    return None


# ---------------------------------------------------------------- pobieranie


def download(url: str, dest: Path, expected_size: Optional[int] = None, token: Optional[str] = None) -> int:
    """Pobiera plik na dysk i sprawdza jego rozmiar."""
    headers = {"User-Agent": USER_AGENT, "Accept": "application/octet-stream"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    dest.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    with urllib.request.urlopen(request, timeout=300) as response, open(dest, "wb") as handle:
        while True:
            chunk = response.read(CHUNK)
            if not chunk:
                break
            handle.write(chunk)
            total += len(chunk)
    if expected_size and total != expected_size:
        raise IOError(f"rozmiar {total} B != oczekiwane {expected_size} B")
    return total


def extract_zip(zip_path: Path, dest: Path) -> int:
    """Rozpakowuje ZIP, pomijając górny folder (pdfcraft-web-0.11.0/...)."""
    dest.mkdir(parents=True, exist_ok=True)
    dest_resolved = dest.resolve()
    written = 0
    with zipfile.ZipFile(zip_path) as archive:
        names = [n for n in archive.namelist() if n and not n.startswith("/")]
        roots = {n.split("/", 1)[0] for n in names if "/" in n}
        strip = 1 if len(roots) == 1 else 0
        for info in archive.infolist():
            parts = info.filename.split("/")[strip:]
            parts = [p for p in parts if p not in ("", ".")]
            if not parts:
                continue
            target = (dest / Path(*parts)).resolve()
            if not str(target).startswith(str(dest_resolved)):
                raise IOError(f"ścieżka poza katalogiem docelowym: {info.filename}")
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, open(target, "wb") as handle:
                shutil.copyfileobj(source, handle)
            written += 1
    return written


# ---------------------------------------------------------------- manifest


def previous_manifest(site_url: str, state_file: Optional[Path], token: Optional[str]) -> Dict[str, Any]:
    """Stan wdrożony: manifest z żywej strony, w razie czego plik --state."""
    if site_url:
        url = site_url.rstrip("/") + "/manifest.json"
        try:
            data = http_json(url, token=token, timeout=30)
            if isinstance(data, dict) and data.get("tools") is not None:
                print(f"  · stan z {url}")
                return data
        except Exception:
            pass
    if state_file and Path(state_file).exists():
        print(f"  · stan z {state_file}")
        return read_manifest(Path(state_file))
    return read_manifest(Path("/nonexistent"))


def build_entry(
    tool: Dict[str, Any],
    release: Dict[str, Any],
    asset: Dict[str, Any],
    info: Dict[str, Any],
    icon: Optional[str],
    files: int,
    size: int,
) -> Dict[str, Any]:
    tag = release.get("tag_name", "")
    version = tag[1:] if tag.startswith("v") else tag
    label = tool["overrides"].get("label")
    if not label:
        name = (release.get("name") or "").strip()
        label = name
        for suffix in (version, tag):
            if suffix and label.endswith(suffix):
                label = label[: -len(suffix)].strip(" -–v")
        if not label:
            label = tool["repo"]

    blurb = tool["overrides"].get("blurb") or tool.get("blurb") or (info.get("description") or "").strip()
    if blurb and label and blurb.lower().startswith(label.lower() + ":"):
        blurb = blurb[len(label) + 1 :].strip()

    page = tool["overrides"].get("page")
    if not page:
        if tool["owner"].lower() == "storytold":
            page = f"https://getartcraft.com/apps/{tool['id']}"
        else:
            page = info.get("homepage") or f"https://github.com/{tool['owner']}/{tool['repo']}"
    page = page.strip()
    if page and not page.startswith(("http://", "https://")):
        page = "https://" + page.lstrip("/")

    return {
        "id": tool["id"],
        "label": label,
        "repo": f"{tool['owner']}/{tool['repo']}",
        "version": version,
        "tag": tag,
        "published_at": release.get("published_at"),
        "asset": asset.get("name"),
        "asset_size": asset.get("size"),
        "page": page,
        "icon": icon,
        "blurb": blurb,
        "app_path": f"/apps/{tool['id']}/",
        "files": files,
        "bytes": size,
        "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


# ---------------------------------------------------------------- main


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", default="site-out", help="katalog wyjściowy witryny")
    parser.add_argument("--config", default=str(REPO_ROOT / "tools.txt"), help="plik z listą narzędzi")
    parser.add_argument("--site-url", default=os.environ.get("SITE_URL", ""), help="adres wdrożonej witryny")
    parser.add_argument("--state", default=None, help="plik z poprzednim manifestem (gdy brak strony)")
    parser.add_argument("--only", default="", help="tylko te narzędzia (po przecinku)")
    parser.add_argument("--force", action="store_true", help="pobierz ponownie nawet bez zmian wersji")
    parser.add_argument("--dry-run", action="store_true", help="sprawdź wersje, nie pobieraj")
    args = parser.parse_args()

    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or None
    out_dir = Path(args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    tools = parse_config(Path(args.config))
    only = {part.strip() for part in args.only.split(",") if part.strip()}

    site_url = args.site_url.strip()
    if not site_url:
        repo_env = os.environ.get("GITHUB_REPOSITORY", "").strip()
        if "/" in repo_env:
            owner, name = repo_env.split("/", 1)
            site_url = f"https://{owner}.github.io/{name}/"

    print(f"OfficeCraft · synchronizacja {len(tools)} narzędzi")
    previous = previous_manifest(site_url, Path(args.state) if args.state else None, token)
    previous_versions = versions_map(previous)
    previous_tools: Dict[str, Any] = dict(previous.get("tools") or {})

    manifest_tools: Dict[str, Any] = {}
    manifest_skipped: Dict[str, str] = {}
    changed = False
    downloaded_bytes = 0

    for tool in tools:
        tool_id = tool["id"]
        if only and tool_id not in only:
            if tool_id in previous_tools:
                manifest_tools[tool_id] = previous_tools[tool_id]
            continue

        print(f"\n[{tool_id}] {tool['owner']}/{tool['repo']}")
        try:
            release = latest_release(tool["owner"], tool["repo"], token)
        except urllib.error.HTTPError as error:
            print(f"  ! API GitHuba: HTTP {error.code}")
            manifest_skipped[tool_id] = f"błąd API GitHuba (HTTP {error.code})"
            if tool_id in previous_tools:
                manifest_tools[tool_id] = previous_tools[tool_id]
            continue
        except Exception as error:  # noqa: BLE001
            print(f"  ! API GitHuba: {error}")
            manifest_skipped[tool_id] = f"błąd API: {error}"
            if tool_id in previous_tools:
                manifest_tools[tool_id] = previous_tools[tool_id]
            continue

        tag = release.get("tag_name", "")
        version = tag[1:] if tag.startswith("v") else tag
        asset = pick_asset(release, tool, version)
        if not asset:
            print(f"  · brak buildu webowego w wydaniu {tag} - pomijam")
            manifest_skipped[tool_id] = f"brak assetu *-web-*.zip w wydaniu {tag}"
            if tool_id in previous_tools:
                manifest_tools[tool_id] = previous_tools[tool_id]
            continue

        build_dir = out_dir / "apps" / tool_id
        icon_target = out_dir / "assets" / "icons" / f"{tool_id}.png"
        known = previous_versions.get(tool_id)
        previous_blurb = previous_tools.get(tool_id, {}).get("blurb", "")
        new_blurb = tool["overrides"].get("blurb") or tool.get("blurb") or ""
        if known == version and not args.force and not args.dry_run and build_present(build_dir) and previous_blurb == new_blurb:
            print(f"  · {version} już wdrożone - bez zmian")
            icon_before = icon_target.exists()
            icon = find_icon(tool, build_dir, out_dir) or previous_tools.get(tool_id, {}).get("icon")
            manifest_tools[tool_id] = {
                **previous_tools[tool_id],
                "icon": icon,
                "pwa_icon": pwa_icon(tool, build_dir, out_dir),
            }
            if not icon_before and icon_target.exists():
                changed = True
            continue
        if known == version and not args.dry_run and not build_present(build_dir):
            print(f"  · {version} wdrożone, ale brak plików lokalnie - pobieram ponownie")

        print(f"  · wydanie {tag} ({asset.get('name')}, {round((asset.get('size') or 0) / 1e6, 1)} MB)")
        if args.dry_run:
            print("  · tryb --dry-run: pomijam pobieranie")
            continue

        if build_dir.exists():
            shutil.rmtree(build_dir)
        build_dir.mkdir(parents=True, exist_ok=True)

        try:
            with tempfile.TemporaryDirectory() as tmp:
                zip_path = Path(tmp) / asset["name"]
                size = download(
                    asset["browser_download_url"],
                    zip_path,
                    expected_size=asset.get("size"),
                    token=token,
                )
                downloaded_bytes += size
                files = extract_zip(zip_path, build_dir)
        except Exception as error:  # noqa: BLE001
            print(f"  ! pobieranie nieudane: {error}")
            manifest_skipped[tool_id] = f"błąd pobierania: {error}"
            if tool_id in previous_tools:
                manifest_tools[tool_id] = previous_tools[tool_id]
            continue

        total_size = sum(p.stat().st_size for p in build_dir.rglob("*") if p.is_file())
        info = repo_info(tool["owner"], tool["repo"], token)
        icon = find_icon(tool, build_dir, out_dir) or previous_tools.get(tool_id, {}).get("icon")
        manifest_tools[tool_id] = build_entry(
            tool, release, asset, info, icon, files, total_size
        )
        manifest_tools[tool_id]["pwa_icon"] = pwa_icon(tool, build_dir, out_dir)
        changed = True
        print(f"  ✓ zaktualizowano: {files} plików, {round(total_size / 1e6, 1)} MB")

    manifest = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "site_url": site_url,
        "tools": manifest_tools,
        "skipped": manifest_skipped,
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    new_versions = versions_map(manifest)
    deploy_needed = changed or new_versions != versions_map(previous)
    marker = REPO_ROOT / ".deploy-needed"
    if deploy_needed:
        marker.write_text("1\n", encoding="utf-8")
    elif marker.exists():
        marker.unlink()

    print("\n" + "-" * 60)
    print(f"narzędzia w manifeście: {len(manifest_tools)}   pominięte: {len(manifest_skipped)}")
    for tool_id, entry in sorted(manifest_tools.items()):
        print(f"  · {tool_id:12s} {entry.get('version', '?'):16s} {entry.get('label', '')}")
    for tool_id, reason in sorted(manifest_skipped.items()):
        print(f"  ! {tool_id:12s} {reason}")
    if changed:
        print(f"pobrano: {round(downloaded_bytes / 1e6, 1)} MB")
    print("DEPLOY: " + ("potrzebny" if deploy_needed else "niepotrzebny - bez zmian"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
