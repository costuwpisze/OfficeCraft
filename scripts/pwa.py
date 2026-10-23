"""Dodaje do buildów webowych manifest PWA z obsługą otwierania plików.

Każde narzędzie jest osobną aplikacją w ``apps/<id>/``. Po każdej aktualizacji
(zip rozpakowany od nowa) build_site woła :func:`prepare_apps`, więc manifest
i skrypt otwierania plików są dopisywane od nowa - nic nie ginie przy wydaniu.

``file_handlers`` sprawia, że zainstalowana w Edge/Chrome aplikacja rejestruje
się w systemie jako program do danych rozszerzeń. Z systemu plik trafia do
aplikacji przez ``launchQueue`` (File Handling API); skrypt poniżej podaje go
aplikacji jako zdarzenie przeciągnięcia pliku na kanwę.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any, Dict, List

MANIFEST_NAME = "manifest.webmanifest"
SCRIPT_NAME = "officecraft-pwa.js"

# MIME -> rozszerzenia. Windows rejestruje skojarzenia po rozszerzeniach,
# a przeglądarka dopasowuje typ pliku po kluczu MIME.
FILE_TYPES: Dict[str, Dict[str, List[str]]] = {
    "pdfcraft": {
        "application/pdf": [".pdf"],
        "image/png": [".png"],
        "image/jpeg": [".jpg", ".jpeg"],
        "image/tiff": [".tif", ".tiff"],
        "image/gif": [".gif"],
        "image/bmp": [".bmp"],
        "image/jp2": [".jp2", ".j2k", ".jpx"],
    },
    "wordcraft": {
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": [".docx"],
        "application/msword": [".doc"],
        "application/vnd.oasis.opendocument.text": [".odt"],
        "application/rtf": [".rtf"],
        "text/html": [".html", ".htm"],
        "text/markdown": [".md"],
        "application/x-tex": [".tex"],
        "text/plain": [".txt"],
    },
    "gridcraft": {
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": [".xlsx"],
        "application/vnd.ms-excel": [".xls"],
        "application/vnd.ms-excel.sheet.binary.macroEnabled.12": [".xlsb"],
        "application/vnd.oasis.opendocument.spreadsheet": [".ods"],
        "text/csv": [".csv"],
        "text/tab-separated-values": [".tsv"],
    },
    "cadcraft": {
        "image/vnd.dxf": [".dxf"],
        "image/vnd.dwg": [".dwg"],
    },
    "solidcraft": {
        "application/step": [".step", ".stp"],
        "model/iges": [".iges", ".igs"],
        "model/3mf": [".3mf"],
        "model/stl": [".stl"],
        "model/obj": [".obj"],
        "model/gltf+json": [".gltf"],
        "model/gltf-binary": [".glb"],
        "application/x-solidcraft": [".solidcraft"],
    },
    "deckcraft": {
        "application/vnd.openxmlformats-officedocument.presentationml.presentation": [".pptx"],
    },
    "vectorcraft": {
        "application/x-vectorcraft": [".vectorcraft"],
        "image/svg+xml": [".svg", ".svgz"],
        "application/pdf": [".pdf"],
        "application/postscript": [".ai", ".eps"],
        "image/vnd.dxf": [".dxf"],
        "image/emf": [".emf"],
        "image/wmf": [".wmf"],
        "image/vnd.adobe.photoshop": [".psd", ".psb"],
        "image/png": [".png"],
        "image/jpeg": [".jpg", ".jpeg"],
        "image/webp": [".webp"],
        "image/tiff": [".tif", ".tiff"],
        "image/bmp": [".bmp"],
        "image/gif": [".gif"],
        "application/x-affinity": [".af", ".afdesign", ".afpub", ".afphoto"],
    },
    "lightcraft": {
        "image/jpeg": [".jpg", ".jpeg"],
        "image/png": [".png"],
        "image/tiff": [".tif", ".tiff"],
        "image/webp": [".webp"],
        "image/vnd.adobe.photoshop": [".psd"],
        "image/jxl": [".jxl"],
        "image/gif": [".gif"],
        "image/bmp": [".bmp"],
        "image/heic": [".heic", ".heif"],
        "image/x-adobe-dng": [".dng"],
        "image/x-canon-cr2": [".cr2"],
        "image/x-canon-cr3": [".cr3"],
        "image/x-sony-arw": [".arw"],
        "image/x-nikon-nef": [".nef"],
        "image/x-fuji-raf": [".raf"],
        "image/x-panasonic-rw2": [".rw2", ".rwl"],
        "image/x-pentax-pef": [".pef"],
        "image/x-olympus-orf": [".orf"],
    },
}

SCRIPT = """\
/* OfficeCraft: otwieranie plikow z systemu (File Handling API).
   Podaje plik aplikacji jako przeciagniecie na kanwe - te same zdarzenia,
   ktore wysyla uzytkownik przeciagajacy plik do okna. */
(function () {
  if (!("launchQueue" in window)) return;

  var files = [];
  var delivered = false;

  launchQueue.setConsumer(function (params) {
    (params.files || []).forEach(function (handle) {
      handle.getFile().then(function (file) { files.push(file); send(); });
    });
  });

  function booted() {
    return !!(window.wasmBindings || window.lightcraft);
  }

  function send() {
    if (delivered || !files.length) return;
    var started = Date.now();
    (function wait() {
      var canvas = document.querySelector("canvas");
      if (!canvas || !booted()) {
        if (Date.now() - started < 30000) return setTimeout(wait, 250);
        canvas = canvas || document.body;
      }
      // daj aplikacji chwile na podpiecie nasluchiwaczy po starcie
      setTimeout(function () { dropAll(canvas); }, 800);
    })();
  }

  function dropAll(canvas) {
    delivered = true;
    var dt = new DataTransfer();
    files.forEach(function (file) { dt.items.add(file); });
    var rect = canvas.getBoundingClientRect();
    var opts = {
      bubbles: true,
      cancelable: true,
      dataTransfer: dt,
      clientX: rect.left + rect.width / 2,
      clientY: rect.top + rect.height / 2
    };
    ["dragenter", "dragover", "drop"].forEach(function (type) {
      canvas.dispatchEvent(new DragEvent(type, opts));
    });
  }
})();

/* OfficeCraft: instalacja jako aplikacja. Strona otwarta z przyciskiem
   "Zainstaluj jako aplikacje" (?install=1) pokazuje panel z przyciskiem,
   ktory wywoluje systemowy dialog instalacji PWA. */
(function () {
  var params;
  try { params = new URLSearchParams(location.search); } catch (err) { return; }
  if (!params.has("install")) return;

  var deferred = null;
  var panel = null;
  var button = null;
  var note = null;

  function close() {
    if (!panel) return;
    panel.parentNode.removeChild(panel);
    panel = null;
  }

  function open() {
    if (panel) return;
    panel = document.createElement("div");
    panel.id = "officecraft-install";
    panel.style.cssText = "position:fixed;right:20px;bottom:20px;z-index:2147483647;"
      + "display:flex;gap:12px;align-items:center;max-width:calc(100vw - 40px);"
      + "padding:12px 14px;border:1px solid rgba(255,255,255,.18);border-radius:14px;"
      + "background:#24262b;color:#eef1f6;font:14px/1.35 system-ui,sans-serif;"
      + "box-shadow:0 12px 32px rgba(0,0,0,.45)";
    note = document.createElement("span");
    note.textContent = "Zainstaluj " + document.title.split(" - ")[0] + " na komputerze.";
    button = document.createElement("button");
    button.type = "button";
    button.textContent = "Zainstaluj";
    button.style.cssText = "flex:none;padding:9px 14px;border:0;border-radius:9px;"
      + "background:#3b82f6;color:#fff;font:600 14px system-ui,sans-serif;cursor:pointer";
    button.addEventListener("click", function () {
      if (!deferred) return;
      var prompt = deferred;
      deferred = null;
      prompt.prompt();
      prompt.userChoice.then(close);
    });
    button.disabled = !deferred;
    panel.appendChild(note);
    panel.appendChild(button);
    document.body.appendChild(panel);
    if (!deferred) {
      setTimeout(function () {
        if (deferred) return;
        button.disabled = true;
        note.textContent = "Uzyj menu przegladarki: Zainstaluj...";
      }, 4000);
    }
  }

  window.addEventListener("beforeinstallprompt", function (event) {
    event.preventDefault();
    deferred = event;
    close();
    open();
  });
  window.addEventListener("appinstalled", close);

  if (document.body) open();
  else window.addEventListener("DOMContentLoaded", open);

  try { history.replaceState(null, "", location.pathname + location.hash); } catch (err) {}
})();
"""


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


ICON_LARGE = "officecraft-icon-512.png"
ICON_SMALL = "officecraft-icon-192.png"


def _resize_icon(source: Path, target: Path, size: int) -> bool:
    """Tworzy kwadratową ikonę ``size`` px (Pillow). False, gdy brak Pillow."""
    try:
        from PIL import Image  # type: ignore[import-not-found]
    except ImportError:
        return False
    try:
        with Image.open(source) as image:
            icon = image.convert("RGBA").resize((size, size), Image.LANCZOS)
            icon.save(target, format="PNG", optimize=True)
        return True
    except Exception:  # noqa: BLE001
        return False


def _icon_list(info: Dict[str, Any], site_dir: Path, app_dir: Path) -> List[Dict[str, Any]]:
    """Ikony 192 i 512. Duża ikona (512 px) jest kopiowana do katalogu aplikacji,
    a mniejsza powstaje z niej przez przeskalowanie (gdy jest Pillow)."""
    large = (info.get("pwa_icon") or "").strip()
    source = site_dir / large.lstrip("/") if large else None
    if not source or not source.is_file():
        return []
    shutil.copyfile(source, app_dir / ICON_LARGE)
    icons = [
        {"src": ICON_LARGE, "sizes": "512x512", "type": "image/png", "purpose": "any"},
    ]
    if _resize_icon(source, app_dir / ICON_SMALL, 192):
        icons.insert(0, {"src": ICON_SMALL, "sizes": "192x192", "type": "image/png", "purpose": "any"})
    else:
        # Bez Pillow nie deklarujemy rozmiaru, ktorego plik nie ma.
        icons.insert(0, {"src": ICON_LARGE, "sizes": "192x192", "type": "image/png", "purpose": "any"})
    return icons


def build_manifest(tool_id: str, info: Dict[str, Any], site_dir: Path, app_dir: Path) -> Dict[str, Any]:
    label = info.get("label") or tool_id
    blurb = " ".join((info.get("blurb") or "").split())
    manifest: Dict[str, Any] = {
        "name": label,
        "short_name": label,
        "description": blurb,
        "start_url": "./",
        "scope": "./",
        "display": "standalone",
        "background_color": "#1c1c1c",
        "theme_color": "#1c1c1c",
        "categories": ["productivity", "utilities"],
        "launch_handler": {"client_mode": "navigate-new"},
    }
    icons = _icon_list(info, site_dir, app_dir)
    if icons:
        manifest["icons"] = icons
    types = FILE_TYPES.get(tool_id)
    if types:
        manifest["file_handlers"] = [{"action": "./", "accept": types}]
    return manifest


def prepare_app(app_dir: Path, tool_id: str, info: Dict[str, Any]) -> bool:
    """Pisze manifest i skrypt, dopisuje je do index.html. Idempotentne."""
    index = app_dir / "index.html"
    if not index.is_file():
        return False

    manifest_path = app_dir / MANIFEST_NAME
    manifest = _read_json(manifest_path)
    generated = build_manifest(tool_id, info, app_dir.parent.parent, app_dir)
    # Zachowaj to, co aplikacja sama zadeklarowala (np. wlasne ikony SolidCraft);
    # nasze wpisy (file_handlers, launch_handler) zawsze wygrywaja.
    for key, value in generated.items():
        if key in ("file_handlers", "launch_handler") or (key == "icons" and value) or key not in manifest:
            manifest[key] = value

    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (app_dir / SCRIPT_NAME).write_text(SCRIPT, encoding="utf-8")

    html = index.read_text(encoding="utf-8")
    changed = False
    if not re.search(r'<link[^>]+rel=["\']manifest["\']', html, re.IGNORECASE):
        html = html.replace(
            "</head>", f'  <link rel="manifest" href="{MANIFEST_NAME}">\n  </head>', 1
        )
        changed = True
    if SCRIPT_NAME not in html:
        html = html.replace(
            "</body>", f'  <script src="{SCRIPT_NAME}" defer></script>\n  </body>', 1
        )
        changed = True
    if changed:
        index.write_text(html, encoding="utf-8")
    return True


def prepare_apps(apps_dir: Path, tools: Dict[str, Dict[str, Any]]) -> int:
    """Przygotowuje wszystkie rozpakowane buildy; zwraca liczbę aplikacji."""
    done = 0
    for tool_id, info in tools.items():
        app_dir = apps_dir / tool_id
        if app_dir.is_dir() and prepare_app(app_dir, tool_id, info):
            done += 1
    return done
