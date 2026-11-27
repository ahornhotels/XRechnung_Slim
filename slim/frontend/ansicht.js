// Lesbare Darstellung einer XRechnung: jede Angabe, die in der Datei steht
// (Kopf, Bemerkung, Bezuege, Parteien, Positionen, Ab-/Zuschlaege, Steuern, Summen) - gemeinsam fuer das Archiv und die Detailseite einer Rechnung.
// Erwartet die Antwort von /api/archive/ansicht bzw. das Feld "ansicht" von /api/rechnung.
window.SlimAnsicht = (function () {
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]));
  const datum = (iso) => iso ? iso.slice(0, 10).split("-").reverse().join(".") : "–";
  const zeit = (iso) => iso ? datum(iso) + " " + iso.slice(11, 16) : "–";
  const geld = (v, w) => v == null ? "–" : Number(v).toLocaleString("de-DE", {minimumFractionDigits: 2, maximumFractionDigits: 2}) + " " + (w === "EUR" || !w ? "€" : w);

  function partei(titel, p) {
    p = p || {};
    const k = p.kontakt || {};
    const z = [p.name || "–", p.strasse, p.zusatz, p.adresszeile, [p.ort, p.land].filter(Boolean).join(" · "),
               p.ust_id ? "USt-IdNr. " + p.ust_id : null,
               p.email ? "Elektronische Adresse: " + p.email : null,
               (k.name || k.telefon || k.email) ? "Kontakt: " + [k.name, k.telefon, k.email].filter(Boolean).join(", ") : null];
    return `<div><b>${esc(titel)}</b><br>${z.filter(Boolean).map(esc).join("<br>")}</div>`;
  }

  const ARTEN = {"380": "Rechnung", "381": "Gutschrift", "384": "Rechnungskorrektur", "386": "Anzahlungsrechnung",
                 "389": "Gutschrift (Selbstfakturierung)", "326": "Teilrechnung"};

  // Kopfangaben als Liste "Bezeichnung: Wert" - nur, was in der Datei steht.
  function kopf(a) {
    const f = a.fakten, k = a.kopf || {}, z = k.zahlung || {};
    const zeilen = [
      ["Art", k.typ ? (ARTEN[k.typ] || "Code") + " (" + k.typ + ")" : null],
      ["Rechnungsdatum", datum(f.rechnungsdatum)],
      ["Fällig am", k.faellig ? datum(k.faellig) : null],
      ["Leistungszeitraum", k.von || k.bis ? datum(k.von) + " bis " + datum(k.bis) : null],
      ["Käuferreferenz (BT-10)", f.kaeuferreferenz],
      ["Bestellnummer (BT-13)", k.bestellnummer],
      ["Bezug auf Rechnung", (k.bezuege || []).map(b => b.nr + (b.datum ? " vom " + datum(b.datum) : "")).join(", ")],
      ["Leistungsempfänger (BT-70)", k.leistungsempfaenger],
      ["Zahlungsbedingungen", k.zahlungsbedingungen],
      ["IBAN", z.konto], ["Kontoinhaber", z.inhaber], ["BIC", z.bic],
    ].filter(x => x[1]);
    return `<table><tbody>${zeilen.map(x => `<tr><td class="muted">${esc(x[0])}</td><td>${esc(x[1])}</td></tr>`).join("")}</tbody></table>`;
  }

  function html(a) {
    const f = a.fakten, w = f.waehrung;
    return `
      ${kopf(a)}
      <div class="parteien">${partei("Verkäufer", a.verkaeufer)}${partei("Käufer", a.kaeufer)}</div>
      ${a.hinweise.length ? `<h3>Bemerkung (BT-22)</h3><p style="white-space:pre-line">${a.hinweise.map(esc).join("\n")}</p>` : ""}
      <h3>Positionen</h3>
      <div class="tabelle"><table>
        <thead><tr><th>Pos.</th><th>Bezeichnung</th><th class="zahl">Menge</th><th class="zahl">Einzelpreis</th><th class="zahl">Netto</th><th class="zahl">USt.</th></tr></thead>
        <tbody>${a.positionen.map(p => `<tr><td>${esc(p.nr)}</td><td>${esc(p.bezeichnung)}${p.hinweis ? `<br><span class="muted">${esc(p.hinweis)}</span>` : ""}${
            p.von || p.bis ? `<br><span class="muted">${esc(datum(p.von))} bis ${esc(datum(p.bis))}</span>` : ""}</td>
          <td class="zahl">${esc(p.menge)} ${esc(p.einheit || "")}</td><td class="zahl">${esc(geld(p.preis, w))}</td>
          <td class="zahl">${esc(geld(p.netto, w))}</td><td class="zahl">${esc(p.steuer_prozent ?? "")} %</td></tr>`).join("")}</tbody>
      </table></div>
      ${(a.nachlaesse || []).length ? `<h3>Abschläge und Zuschläge</h3>
      <table><tbody>${a.nachlaesse.map(n => `<tr><td>${n.zuschlag ? "Zuschlag" : "Abschlag"}</td><td>${esc(n.grund || "")}</td>
        <td class="zahl">${esc(n.kategorie || "")} ${esc(n.prozent ?? "")} %</td>
        <td class="zahl">${n.zuschlag ? "" : "−"}${esc(geld(n.betrag, w))}</td></tr>`).join("")}</tbody></table>` : ""}
      <h3>Steuern</h3>
      <table><tbody>${a.steuern.map(s => `<tr><td>${esc(s.kategorie)} ${esc(s.prozent ?? "")} %</td>
        <td class="zahl">Basis ${esc(geld(s.basis, w))}</td><td class="zahl">Steuer ${esc(geld(s.betrag, w))}</td></tr>`).join("")}</tbody></table>
      <h3>Summen</h3>
      <table><tbody>
        ${a.summen.abschlaege || a.summen.zuschlaege ? `<tr><td>Summe Positionen</td><td class="zahl">${esc(geld(a.summen.positionen, w))}</td></tr>` : ""}
        ${a.summen.abschlaege ? `<tr><td>Abschläge</td><td class="zahl">−${esc(geld(a.summen.abschlaege, w))}</td></tr>` : ""}
        ${a.summen.zuschlaege ? `<tr><td>Zuschläge</td><td class="zahl">${esc(geld(a.summen.zuschlaege, w))}</td></tr>` : ""}
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
