/* Panel administracyjny OfficeCraft - działa bez backendu (czysty statyk). */
(function () {
  "use strict";

  var cfg = JSON.parse(document.getElementById("officecraft-config").textContent);
  var API = "https://api.github.com";
  var repo = cfg.repository || "";
  var workflow = cfg.workflow || "sync-tools.yml";
  var ref = cfg.ref || "main";
  var patInput = document.getElementById("pat");
  var logBox = document.getElementById("log");
  var PAT_KEY = "officecraft.pat";

  function log(message) {
    if (!logBox) return;
    logBox.hidden = false;
    var stamp = new Date().toLocaleTimeString("pl-PL");
    logBox.textContent += "[" + stamp + "] " + message + "\n";
    logBox.scrollTop = logBox.scrollHeight;
  }

  function token() {
    return (patInput && patInput.value.trim()) || sessionStorage.getItem(PAT_KEY) || "";
  }

  function headers(extra) {
    var head = { Accept: "application/vnd.github+json" };
    var t = token();
    if (t) head.Authorization = "Bearer " + t;
    if (extra) Object.keys(extra).forEach(function (k) { head[k] = extra[k]; });
    return head;
  }

  function pill(kind, text) {
    return '<span class="pill pill--' + kind + '">' + text + "</span>";
  }

  function escapeHtml(value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  // ---------------------------------------------------------------- status

  function renderStatus(tools) {
    var host = document.getElementById("status");
    var ids = Object.keys(tools || {});
    if (!ids.length) {
      host.innerHTML = '<p class="muted">Brak wdrożonych narzędzi - uruchom pierwszą synchronizację.</p>';
      return;
    }
    var rows = ids.map(function (id) {
      var t = tools[id];
      return (
        "<tr><td>" +
        escapeHtml(t.label || id) +
        "</td><td class=\"num\">" +
        escapeHtml(t.version || "?") +
        '</td><td><span class="status-cell" data-repo="' +
        escapeHtml(t.repo) +
        '">sprawdzam…</span></td><td><a href="' +
        escapeHtml(t.page || "#") +
        '" target="_blank" rel="noopener">projekt ↗</a></td></tr>'
      );
    });
    host.innerHTML =
      "<table><thead><tr><th>Narzędzie</th><th>Wdrożone</th><th>Na GitHubie</th><th></th></tr></thead><tbody>" +
      rows.join("") +
      "</tbody></table>";
  }

  // Wersje wdrożone czytamy na żywo z manifest.json (zawsze aktualne),
  // a gdy pliku nie ma - z konfiguracji osadzonej w stronie.
  function loadDeployed() {
    return fetch("../manifest.json", { cache: "no-cache" })
      .then(function (response) {
        return response.ok ? response.json() : null;
      })
      .then(function (manifest) {
        if (manifest && manifest.tools && Object.keys(manifest.tools).length) {
          var tools = {};
          Object.keys(manifest.tools).forEach(function (id) {
            var entry = manifest.tools[id];
            tools[id] = {
              label: entry.label,
              version: entry.version,
              repo: entry.repo,
              page: entry.page
            };
          });
          return tools;
        }
        return cfg.tools || {};
      })
      .catch(function () {
        return cfg.tools || {};
      });
  }

  function renderTools() {
    var host = document.getElementById("tools");
    var skipped = cfg.skipped || {};
    var tools = cfg.tools || {};
    var parts = [];
    Object.keys(tools).forEach(function (id) {
      parts.push(
        "<li><code>" +
          escapeHtml(id) +
          "</code> - " +
          escapeHtml(tools[id].repo) +
          " (v" +
          escapeHtml(tools[id].version) +
          ")</li>"
      );
    });
    Object.keys(skipped).forEach(function (id) {
      parts.push("<li><code>" + escapeHtml(id) + "</code> - pominięte: " + escapeHtml(skipped[id]) + "</li>");
    });
    host.innerHTML = parts.length ? "<ul>" + parts.join("") + "</ul>" : '<p class="muted">Brak danych.</p>';
  }

  // ------------------------------------------------------- sprawdzanie wersji

  function checkLatest() {
    var cells = document.querySelectorAll(".status-cell");
    Array.prototype.forEach.call(cells, function (cell) {
      var repoName = cell.getAttribute("data-repo");
      if (!repoName) return;
      fetch(API + "/repos/" + repoName + "/releases/latest", { headers: headers() })
        .then(function (response) {
          if (response.status === 403 || response.status === 429) {
            cell.innerHTML = pill("err", "limit API");
            return null;
          }
          if (!response.ok) {
            cell.innerHTML = pill("err", "błąd " + response.status);
            return null;
          }
          return response.json();
        })
        .then(function (data) {
          if (!data) return;
          var latest = String(data.tag_name || "").replace(/^v/, "");
          var current = cell.closest("tr").querySelector("td.num").textContent.trim();
          if (!latest) {
            cell.innerHTML = pill("skip", "brak");
          } else if (latest === current) {
            cell.innerHTML = pill("ok", latest + " - aktualne");
          } else {
            cell.innerHTML = pill("new", latest + " - nowa wersja");
          }
        })
        .catch(function () {
          cell.innerHTML = pill("err", "brak połączenia");
        });
    });
  }

  // ------------------------------------------------------------ uruchamianie

  function runUrl() {
    return "https://github.com/" + repo + "/actions/workflows/" + workflow;
  }

  function dispatch() {
    var t = token();
    if (!t) {
      log("Brak tokenu - wklej PAT w polu poniżej.");
      return;
    }
    log("Wysyłam żądanie uruchomienia workflow " + workflow + "…");
    fetch(API + "/repos/" + repo + "/actions/workflows/" + workflow + "/dispatches", {
      method: "POST",
      headers: headers({ "Content-Type": "application/json" }),
      body: JSON.stringify({ ref: ref })
    })
      .then(function (response) {
        if (response.status === 204) {
          log("Zaakceptowano (204). Przebieg powinien ruszyć.");
          poll();
        } else if (response.status === 401 || response.status === 403) {
          log("Brak uprawnień tokena do uruchamiania Actions (HTTP " + response.status + ").");
        } else {
          log("Błąd HTTP " + response.status + " " + response.statusText);
        }
      })
      .catch(function (error) {
        log("Błąd sieci: " + error);
      });
  }

  function poll() {
    var tries = 0;
    var timer = setInterval(function () {
      tries += 1;
      if (tries > 360) {
        clearInterval(timer);
        log("Koniec monitorowania.");
        return;
      }
      fetch(API + "/repos/" + repo + "/actions/workflows/" + workflow + "/runs?per_page=1", {
        headers: headers()
      })
        .then(function (response) {
          return response.ok ? response.json() : null;
        })
        .then(function (data) {
          if (!data || !data.workflow_runs || !data.workflow_runs.length) return;
          var run = data.workflow_runs[0];
          log("Przebieg #" + run.id + ": " + run.status + (run.conclusion ? " (" + run.conclusion + ")" : ""));
          if (run.status === "completed") {
            clearInterval(timer);
            if (run.conclusion === "success") {
              log("Gotowe. Odśwież stronę, aby zobaczyć nowe wersje.");
              setTimeout(function () { window.location.reload(); }, 4000);
            } else {
              log("Przebieg zakończony niepowodzeniem: " + run.conclusion);
            }
          }
        })
        .catch(function () {});
    }, 5000);
  }

  // ---------------------------------------------------------------- start

  document.addEventListener("DOMContentLoaded", function () {
    var saved = sessionStorage.getItem(PAT_KEY);
    if (saved && patInput) patInput.value = saved;

    var link = document.getElementById("github-run");
    if (link && repo) {
      link.href = runUrl();
    } else if (link) {
      link.href = "https://github.com";
    }

    renderTools();
    loadDeployed().then(function (tools) {
      renderStatus(tools);
      checkLatest();
    });

    var form = document.getElementById("pat-form");
    if (form) {
      form.addEventListener("submit", function (event) {
        event.preventDefault();
        var t = token();
        if (t) sessionStorage.setItem(PAT_KEY, t);
        runChecksWithToken();
        dispatch();
      });
    }
  });

  function runChecksWithToken() {
    var t = token();
    if (!t) return;
    fetch(API + "/repos/" + repo, { headers: headers() })
      .then(function (response) {
        log(
          response.ok
            ? "Token przyjęty, uprawnienia: " + (response.headers.get("x-oauth-scopes") || "nieokreślone")
            : "Token odrzucony (HTTP " + response.status + ")."
        );
      })
      .catch(function () {});
  }
})();
