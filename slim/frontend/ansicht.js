// Lesbare Darstellung einer XRechnung (Kopf, Parteien, Positionen, Steuern,
// Summen) - gemeinsam fuer das Archiv und die Detailseite einer Rechnung.
// Erwartet die Antwort von /api/archive/ansicht bzw. das Feld "ansicht" von /api/rechnung.
window.SlimAnsicht = (function () {
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]));
  const datum = (iso) => iso ? iso.slice(0, 10).split("-").reverse().join(".") : "–";
  const zeit = (iso) => iso ? datum(iso) + " " + iso.slice(11, 16) : "–";
  const geld = (v, w) => v == null ? "–" : Number(v).toLocaleString("de-DE", {minimumFractionDigits: 2, maximumFractionDigits: 2}) + " " + (w === "EUR" || !w ? "€" : w);

  function partei(titel, p) {
    p = p || {};
    return `<div><b>${esc(titel)}</b><br>${esc(p.name || "–")}<br>${esc(p.strasse || "")}<br>${esc(p.ort || "")}` +
           (p.ust_id ? `<br>USt-IdNr. ${esc(p.ust_id)}` : "") + "</div>";
  }

  function html(a) {
    const f = a.fakten, w = f.waehrung;
    return `
      <p>Rechnungsdatum <b>${esc(datum(f.rechnungsdatum))}</b>${f.kaeuferreferenz ? ` · Käuferreferenz (BT-10) <b>${esc(f.kaeuferreferenz)}</b>` : ""}</p>
      <div class="parteien">${partei("Verkäufer", a.verkaeufer)}${partei("Käufer", a.kaeufer)}</div>
      ${a.hinweise.length ? `<p>${a.hinweise.map(esc).join("<br>")}</p>` : ""}
      <div class="tabelle"><table>
        <thead><tr><th>Pos.</th><th>Bezeichnung</th><th class="zahl">Menge</th><th class="zahl">Einzelpreis</th><th class="zahl">Netto</th><th class="zahl">USt.</th></tr></thead>
        <tbody>${a.positionen.map(p => `<tr><td>${esc(p.nr)}</td><td>${esc(p.bezeichnung)}</td>
          <td class="zahl">${esc(p.menge)} ${esc(p.einheit || "")}</td><td class="zahl">${esc(geld(p.preis, w))}</td>
          <td class="zahl">${esc(geld(p.netto, w))}</td><td class="zahl">${esc(p.steuer_prozent ?? "")} %</td></tr>`).join("")}</tbody>
      </table></div>
      <h3>Steuern</h3>
      <table><tbody>${a.steuern.map(s => `<tr><td>${esc(s.kategorie)} ${esc(s.prozent ?? "")} %</td>
        <td class="zahl">Basis ${esc(geld(s.basis, w))}</td><td class="zahl">Steuer ${esc(geld(s.betrag, w))}</td></tr>`).join("")}</tbody></table>
      <h3>Summen</h3>
      <table><tbody>
        <tr><td>Netto</td><td class="zahl">${esc(geld(a.summen.netto, w))}</td></tr>
        <tr><td>Steuer</td><td class="zahl">${esc(geld(a.summen.steuer, w))}</td></tr>
        <tr><td>Brutto</td><td class="zahl">${esc(geld(a.summen.brutto, w))}</td></tr>
        ${a.summen.vorauszahlung ? `<tr><td>Vorauszahlung</td><td class="zahl">${esc(geld(a.summen.vorauszahlung, w))}</td></tr>` : ""}
        <tr><td><b>Zahlbetrag</b></td><td class="zahl"><b>${esc(geld(a.summen.zahlbetrag, w))}</b></td></tr>
      </tbody></table>` +
      (a.xml ? `<details style="margin-top:14px"><summary>Original-XML anzeigen</summary><pre>${esc(a.xml)}</pre></details>` : "");
  }

  return {esc, datum, zeit, geld, html};
})();
