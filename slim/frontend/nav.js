// Gemeinsame Menueleiste aller Slim-Seiten mit dem XRechnung-Schalter rechts.
// Der Schalter zeigt immer den echten Zustand des Suite8-Triggers
// WMAI_XRECHNUNG_BLOCK (GET /api/schalter); Slim speichert ihn nicht selbst.
(function () {
  const MENUE = [
    ["/", "Übersicht", false],
    ["/konfiguration", "Konfiguration XRechnung", true],
    ["/hoteldaten", "Hoteldaten", true],
    ["/archiv", "Archiv", false],
    ["/system", "System", true],
    ["/users", "Benutzer", true],
    ["/handbuch", "Handbuch", false],
  ];
  const TEXT_AUS = "Neue Rechnungsmails gehen ohne XRechnung (nur PDF) raus. Bereits wartende Mails bleiben gesperrt, bis wieder eingeschaltet wird.";
  const TEXT_EIN = "Neue Rechnungsmails werden wieder gesperrt und bekommen die XRechnung. Wartende Mails werden jetzt verarbeitet.";
  const ANZEIGE = {
    aktiv: ["● XRechnung EIN", "ein"],
    inaktiv: ["○ XRechnung AUS", "aus"],
    fehlt: ["Trigger fehlt", "grau"],
    nicht_pruefbar: ["XRechnung nicht prüfbar", "grau"],
  };
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]));

  const css = `
  .slim-nav { display:flex; justify-content:space-between; align-items:center; gap:12px; flex-wrap:wrap;
              padding:8px 16px; background:var(--panel,#fff); border-bottom:1px solid var(--border,#d8dce2);
              font:14px/1.4 system-ui,"Segoe UI",sans-serif; position:sticky; top:0; z-index:50; }
  .slim-nav .links { display:flex; gap:4px; flex-wrap:wrap; }
  .slim-nav .links a { color:var(--fg,#1a1a1a); text-decoration:none; padding:6px 10px; border-radius:6px; }
  .slim-nav .links a:hover { background:var(--bg,#f4f5f7); }
  .slim-nav .links a.aktiv { font-weight:700; background:var(--bg,#f4f5f7); }
  .slim-nav .schalter { border:0; border-radius:16px; padding:6px 14px; font-weight:700; cursor:pointer; color:#fff; font-size:14px; }
  .slim-nav .schalter.ein { background:#1a7f37; } .slim-nav .schalter.aus { background:#b42318; }
  .slim-nav .schalter.grau { background:#6a7280; }
  .slim-nav .schalter[disabled] { cursor:default; opacity:.9; }
  dialog.slim-dlg { max-width:760px; width:calc(100% - 32px); border:1px solid var(--border,#d8dce2); border-radius:12px;
                    background:var(--panel,#fff); color:var(--fg,#1a1a1a); padding:18px; }
  dialog.slim-dlg::backdrop { background:rgba(0,0,0,.45); }
  dialog.slim-dlg pre { white-space:pre-wrap; background:var(--bg,#f4f5f7); padding:10px; border-radius:6px; max-height:50vh; overflow:auto; font-size:12px; }
  dialog.slim-dlg .knoepfe { display:flex; gap:8px; justify-content:flex-end; margin-top:12px; flex-wrap:wrap; }
  dialog.slim-dlg button { padding:8px 14px; border-radius:6px; border:1px solid var(--border,#d8dce2); cursor:pointer; }
  dialog.slim-dlg .fehler { color:#b42318; }`;

  let rolle = null, zustand = null;

  function dialog(html, knoepfe) {
    const d = document.createElement("dialog");
    d.className = "slim-dlg";
    d.innerHTML = html + '<div class="knoepfe"></div>';
    for (const [label, fn] of knoepfe) {
      const b = document.createElement("button");
      b.textContent = label;
      b.onclick = async () => { if (fn) await fn(d); else d.close(); };
      d.querySelector(".knoepfe").appendChild(b);
    }
    d.addEventListener("close", () => d.remove());
    document.body.appendChild(d);
    d.showModal();
    return d;
  }

  function kopieren(text) {
    return ["In Zwischenablage kopieren", async () => {
      try { await navigator.clipboard.writeText(text); } catch (e) {}
    }];
  }

  async function laden() {
    try {
      const r = await fetch("/api/schalter", {cache: "no-store"});
      if (r.status === 401) { location.href = "/login"; return; }
      zustand = await r.json();
    } catch (e) {
      zustand = {state: "nicht_pruefbar", error: String(e)};
    }
    zeigen();
  }

  function zeigen() {
    const b = document.getElementById("slim-schalter");
    if (!b || !zustand) return;
    const [label, klasse] = ANZEIGE[zustand.state] || ANZEIGE.nicht_pruefbar;
    b.textContent = label;
    b.className = "schalter " + klasse;
    b.disabled = rolle !== "verwalten" || (zustand.state === "nicht_pruefbar" && !zustand.grant_sql);
    b.title = zustand.error ? zustand.error : "";
  }

  async function schalten(ein) {
    const r = await fetch("/api/schalter", {method: "POST", headers: {"Content-Type": "application/json"},
                                           body: JSON.stringify({ein})});
    let j = {}; try { j = await r.json(); } catch (e) {}
    if (!r.ok) throw new Error(typeof j.detail === "string" ? j.detail : "Schalten fehlgeschlagen");
    zustand = j;
    zeigen();
  }

  async function klick() {
    if (!zustand || rolle !== "verwalten") return;
    if (zustand.state === "nicht_pruefbar" && !zustand.grant_sql) return;
    if (zustand.state === "nicht_pruefbar") {
      dialog(`<h3>XRechnung nicht prüfbar</h3><p>Der Trigger gehört einem anderen Datenbankbenutzer und ist
              für den App-Benutzer nicht sichtbar. Die App arbeitet wie bisher weiter. Damit der Schalter
              funktioniert, muss der Datenbank-Administrator einmal ausführen:</p><pre>${esc(zustand.grant_sql)}</pre>`,
             [kopieren(zustand.grant_sql), ["Schließen"]]);
      return;
    }
    if (zustand.state === "fehlt") {
      let sql = "";
      try { sql = (await (await fetch("/api/trigger-sql")).json()).sql || ""; } catch (e) {}
      dialog(`<h3>Trigger fehlt</h3><p>In Suite8 ist der Trigger <code>WMAI_XRECHNUNG_BLOCK</code> nicht angelegt.
              Ohne ihn hält Suite8 keine Rechnungsmail zurück. Bitte dieses SQL einmal vom Datenbank-Administrator
              ausführen lassen:</p><pre>${esc(sql)}</pre>`, [kopieren(sql), ["Schließen"]]);
      return;
    }
    const ein = zustand.state !== "aktiv";
    dialog(`<h3>XRechnung ${ein ? "einschalten" : "ausschalten"}?</h3><p>${esc(ein ? TEXT_EIN : TEXT_AUS)}</p>
            <p class="fehler" id="slim-schalt-fehler"></p>`, [
      ["Abbrechen"],
      [ein ? "Einschalten" : "Ausschalten", async (d) => {
        try { await schalten(ein); d.close(); }
        catch (e) {
          d.querySelector("#slim-schalt-fehler").textContent = e.message;
          if (zustand && zustand.grant_sql) {
            d.querySelector("#slim-schalt-fehler").insertAdjacentHTML("afterend",
              `<p>Der Trigger gehört einem anderen Datenbankbenutzer. Der DBA muss einmal ausführen:</p>
               <pre>${esc(zustand.grant_sql)}</pre>`);
          }
        }
      }],
    ]);
  }

  async function start() {
    const style = document.createElement("style");
    style.textContent = css;
    document.head.appendChild(style);
    try {
      const s = await (await fetch("/api/auth/state", {cache: "no-store"})).json();
      rolle = s.role || null;
    } catch (e) {}
    const pfad = location.pathname;
    const links = MENUE.filter(([, , admin]) => !admin || rolle === "verwalten")
      .map(([href, label]) => `<a href="${href}"${pfad === href ? ' class="aktiv"' : ""}>${esc(label)}</a>`).join("");
    const nav = document.createElement("nav");
    nav.className = "slim-nav";
    nav.innerHTML = `<div class="links">${links}</div><button type="button" id="slim-schalter" class="schalter grau">…</button>`;
    document.body.insertBefore(nav, document.body.firstChild);
    document.getElementById("slim-schalter").addEventListener("click", klick);
    await laden();
    setInterval(laden, 30000);
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
  else start();
})();
