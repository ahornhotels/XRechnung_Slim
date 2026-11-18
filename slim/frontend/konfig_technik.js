// Konfiguration XRechnung: Muster-Assistent (Betreff) und SQL fuer Techniker/DBA.
// Lief frueher auf der Uebersicht; gehoert zur Erkennung, daher hier.
// Nutzt PAGE, esc und api aus settings.html.
(function () {
  if (typeof PAGE === "undefined" || PAGE !== "xrechnung") return;
  const $ = (id) => document.getElementById(id);
  const feld = (k) => $("f-" + k);

  const css = document.createElement("style");
  css.textContent = `
  .tk-grid { display:grid; grid-template-columns:minmax(180px,260px) 1fr; gap:8px 16px; align-items:center; padding:8px 0; }
  .tk-tabs { display:flex; gap:6px; flex-wrap:wrap; margin:8px 0; }
  .tk-tabs button.aktiv { outline:2px solid var(--accent); }
  pre.tk-sql { white-space:pre; overflow:auto; max-height:420px; background:var(--bg); border:1px solid var(--border);
               border-radius:6px; padding:10px; font-size:12px; font-family:ui-monospace,Consolas,monospace; }
  textarea.tk-sql { min-height:360px; font-size:12px; white-space:pre; }
  details.tk { border-top:1px solid var(--border); padding:10px 0; }
  details.tk summary { cursor:pointer; font-weight:500; }
  .tk-badge { font-size:10px; padding:1px 6px; border-radius:4px; background:var(--warn-bg); color:var(--warn); margin-left:6px; }
  @media (max-width:640px) { .tk-grid { grid-template-columns:1fr; } }`;
  document.head.appendChild(css);

  // ── Muster-Assistent: direkt unter "Erkennung und Anhang" ──
  const assistent = document.createElement("div");
  assistent.className = "card";
  assistent.id = "muster-assistent";
  assistent.innerHTML = `
    <h2>Muster-Assistent (Betreff)</h2>
    <p class="muted" style="margin-top:0">Ohne regulären Ausdruck: einen echten Betreff einer Suite8-Rechnungsmail eintragen,
      die Rechnungsnummer darin dazu – „Muster erzeugen“ trägt das Muster oben bei <b>Erkennung im Betreff</b> ein.
      Gibt es deutsche und englische Betreffe, beide ausfüllen. Übernommen wird es erst mit <b>Speichern</b> bei „Erkennung und Anhang“.</p>
    <div class="tk-grid">
      <label for="gen_example_de">Beispiel-Betreff deutsch</label>
      <input id="gen_example_de" type="text" placeholder="z. B. Ihre Rechnung Nr. 123456">
      <label for="gen_number_de">Rechnungsnummer darin</label>
      <input id="gen_number_de" type="text" placeholder="z. B. 123456">
      <label for="gen_example_en">Beispiel-Betreff englisch <span class="muted">(optional)</span></label>
      <input id="gen_example_en" type="text" placeholder="z. B. Your invoice no. 123456">
      <label for="gen_number_en">Rechnungsnummer darin</label>
      <input id="gen_number_en" type="text" placeholder="z. B. 123456">
    </div>
    <div class="actions"><button id="gen_btn">Muster erzeugen</button><span class="status" id="gen_result"></span></div>
    <h3 style="font-size:15px;margin:8px 0 0">Muster testen <span class="muted" style="font-weight:400">(nichts wird gespeichert)</span></h3>
    <div class="tk-grid">
      <label for="test_subject">Test-Betreff</label>
      <input id="test_subject" type="text" placeholder="z. B. Ihre Rechnung Nr. 123456">
      <label for="test_filename">Test-Dateiname</label>
      <input id="test_filename" type="text" placeholder="z. B. Folio_123456.pdf">
    </div>
    <div class="actions"><button class="secondary" id="test_btn">Testen</button><span class="status" id="test_result"></span></div>
    <p class="muted" style="font-size:13px">Ändert sich das Muster, muss der Datenbank-Administrator den Suite8-Trigger
      mit dem SQL unten („Trigger-SQL“) neu anlegen – sonst hält Suite8 die Mails nach dem alten Muster an.</p>`;

  // ── Fuer Techniker / DBA: Trigger-SQL und Mapping ──
  const technik = document.createElement("div");
  technik.className = "card";
  technik.id = "technik";
  technik.innerHTML = `
    <h2>Für Techniker / DBA</h2>
    <details class="tk" id="trigger_details">
      <summary>Trigger-SQL (Suite8 hält Rechnungsmails an)</summary>
      <p class="muted">Muss einmal als Suite8-Datenbankbenutzer ausgeführt werden und nach jeder Änderung des Musters erneut.
        Es spiegelt das gespeicherte Muster wider.</p>
      <pre class="tk-sql" id="trigger_sql">Lädt …</pre>
      <div class="actions"><button class="secondary" id="trigger_copy">In Zwischenablage kopieren</button>
        <button class="secondary" id="trigger_reload">Aktualisieren</button><span class="status" id="trigger_status"></span></div>
    </details>
    <details class="tk" id="mapping_details">
      <summary>Mapping und SQL-Quellen (wie Suite8 → XRechnung gelesen wird)</summary>
      <p class="muted" id="map_intro"></p>
      <div class="tk-tabs" id="map_tabs"></div>
      <p class="muted" id="map_desc"></p>
      <pre class="tk-sql" id="map_src">Lädt …</pre>
      <textarea class="tk-sql" id="map_edit" style="display:none"></textarea>
      <div class="actions">
        <button class="secondary" id="map_copy">In Zwischenablage kopieren</button>
        <button class="secondary" id="map_edit_btn" style="display:none">Bearbeiten</button>
        <button id="map_save_btn" style="display:none">Speichern</button>
        <button class="secondary" id="map_cancel_btn" style="display:none">Abbrechen</button>
        <button class="secondary" id="map_reset_btn" style="display:none;color:var(--error)">Auf Original zurücksetzen</button>
        <span class="status" id="map_status"></span>
      </div>
    </details>`;

  function einhaengen() {
    const erk = document.querySelector('[data-section="erkennung"]');
    if (!erk || $("muster-assistent")) return !!erk;
    erk.after(assistent);
    $("sections").after(technik);
    return true;
  }
  if (!einhaengen()) {
    const mo = new MutationObserver(() => { if (einhaengen()) mo.disconnect(); });
    mo.observe($("sections"), {childList: true});
  }

  function status(id, ok, text) {
    const el = $(id);
    el.className = "status" + (ok === true ? " ok" : ok === false ? " bad" : "");
    el.textContent = text;
  }
  async function kopieren(text, id) {
    try { await navigator.clipboard.writeText(text); status(id, true, "Kopiert."); }
    catch (e) { status(id, false, "Kopieren fehlgeschlagen"); }
    setTimeout(() => status(id, null, ""), 2000);
  }

  // ── Muster erzeugen / testen ──
  async function erzeugen() {
    const examples = [];
    for (const [sp, name] of [["de", "Deutsch"], ["en", "Englisch"]]) {
      const ex = $("gen_example_" + sp).value.trim(), nr = $("gen_number_" + sp).value.trim();
      if (!ex && !nr) continue;
      if (!ex || !nr) return status("gen_result", false, `${name}: bitte Betreff UND Rechnungsnummer eintragen.`);
      examples.push({example: ex, number: nr});
    }
    if (!examples.length) return status("gen_result", false, "Bitte mindestens einen Betreff mit Rechnungsnummer eingeben.");
    status("gen_result", null, "…");
    try {
      const r = await api("/api/config/pattern/generate", "POST", {examples, kind: "zinv_number"});
      if (!r.ok) return status("gen_result", false, r.error || "Kein Muster gefunden.");
      feld("suite8_recognize_subject_pattern").value = r.pattern;
      $("test_subject").value = examples[0].example;
      status("gen_result", true, `Muster eingetragen – Nummer(n) ${(r.matched || []).join(", ")} erkannt. Bitte oben speichern.`);
      testen();
    } catch (e) { status("gen_result", false, e.message); }
  }

  async function testen() {
    try {
      const j = await api("/api/config/pattern/test", "POST", {
        subject_pattern: feld("suite8_recognize_subject_pattern").value,
        filename_pattern: feld("suite8_recognize_filename_pattern").value,
        subject: $("test_subject").value,
        filename: $("test_filename").value,
      });
      if (j.matched) status("test_result", true, `Erkannt: Rechnungsnummer ${j.result} (aus ${j.source === "subject" ? "Betreff" : j.source === "filename" ? "Dateiname" : j.source})`);
      else status("test_result", false, j.error || "Nicht erkannt.");
    } catch (e) { status("test_result", false, e.message); }
  }

  // ── Trigger-SQL ──
  let triggerSql = "";
  async function triggerLaden() {
    try { triggerSql = (await api("/api/trigger-sql")).sql || ""; $("trigger_sql").textContent = triggerSql; }
    catch (e) { $("trigger_sql").textContent = "Fehler: " + e.message; }
  }

  // ── Mapping / SQL-Quellen ──
  let vorlagen = null, aktuell = null;
  async function mappingLaden() {
    try {
      const j = await api("/api/sql/templates");
      vorlagen = j.items.concat([{name: "VIEWS_Customized_final.txt",
        description: "Original-Views (CREATE VIEW + CREATE FUNCTION) – historische Referenz",
        url: j.views_source_url, readonly: true}]);
      $("map_intro").textContent = j.note || "";
      $("map_tabs").innerHTML = vorlagen.map((t, i) =>
        `<button class="secondary" data-i="${i}">${esc(t.name)}${t.overridden ? '<span class="tk-badge">geändert</span>' : ""}</button>`).join("");
      zeigen(0);
    } catch (e) { $("map_src").textContent = "Fehler: " + e.message; }
  }
  function bearbeiten(an) {
    $("map_src").style.display = an ? "none" : "block";
    $("map_edit").style.display = an ? "block" : "none";
    $("map_save_btn").style.display = an ? "inline-block" : "none";
    $("map_cancel_btn").style.display = an ? "inline-block" : "none";
    $("map_edit_btn").style.display = !an && aktuell && !aktuell.readonly ? "inline-block" : "none";
    $("map_reset_btn").style.display = !an && aktuell && !aktuell.readonly && aktuell.overridden ? "inline-block" : "none";
    if (an) $("map_edit").value = $("map_src").textContent;
  }
  async function zeigen(i) {
    aktuell = vorlagen[i];
    document.querySelectorAll("#map_tabs button").forEach(b => b.classList.toggle("aktiv", +b.dataset.i === i));
    $("map_desc").textContent = (aktuell.description || "")
      + (aktuell.overridden ? " – DIESE geänderte Fassung nutzt Slim gerade." : "");
    bearbeiten(false);
    $("map_src").textContent = "Lädt …";
    try {
      const r = await fetch(aktuell.url);
      if (!r.ok) throw new Error("HTTP " + r.status);
      $("map_src").textContent = await r.text();
    } catch (e) { $("map_src").textContent = "Fehler: " + e.message; }
  }
  async function speichern() {
    const name = encodeURIComponent(aktuell.name), sql = $("map_edit").value;
    status("map_status", null, "Prüft und speichert …");
    try {
      const v = await api(`/api/sql/templates/${name}/validate`, "POST", {sql});
      if (!v.ok) return status("map_status", false, "Prüfung fehlgeschlagen: " + v.error);
      await api(`/api/sql/templates/${name}`, "PUT", {sql});
      status("map_status", true, "Gespeichert. Wirkt beim nächsten Abruf.");
      await mappingLaden();
    } catch (e) { status("map_status", false, e.message); }
  }
  async function zuruecksetzen() {
    if (!confirm(`Änderung an ${aktuell.name} löschen?\nSlim nutzt danach wieder die mitgelieferte Vorlage.`)) return;
    try {
      await api(`/api/sql/templates/${encodeURIComponent(aktuell.name)}`, "DELETE");
      status("map_status", true, "Mitgelieferte Vorlage ist wieder aktiv.");
      await mappingLaden();
    } catch (e) { status("map_status", false, e.message); }
  }

  document.addEventListener("click", (e) => {
    const t = e.target.closest("button");
    if (!t) return;
    if (t.id === "gen_btn") erzeugen();
    else if (t.id === "test_btn") testen();
    else if (t.id === "trigger_reload") triggerLaden();
    else if (t.id === "trigger_copy") (triggerSql ? Promise.resolve() : triggerLaden()).then(() => kopieren(triggerSql, "trigger_status"));
    else if (t.parentElement && t.parentElement.id === "map_tabs") zeigen(+t.dataset.i);
    else if (t.id === "map_copy") kopieren($("map_edit").style.display === "block" ? $("map_edit").value : $("map_src").textContent, "map_status");
    else if (t.id === "map_edit_btn") bearbeiten(true);
    else if (t.id === "map_cancel_btn") zeigen(vorlagen.indexOf(aktuell));
    else if (t.id === "map_save_btn") speichern();
    else if (t.id === "map_reset_btn") zuruecksetzen();
  });
  technik.querySelector("#trigger_details").addEventListener("toggle", (e) => { if (e.target.open && !triggerSql) triggerLaden(); });
  technik.querySelector("#mapping_details").addEventListener("toggle", (e) => { if (e.target.open && !vorlagen) mappingLaden(); });
})();
