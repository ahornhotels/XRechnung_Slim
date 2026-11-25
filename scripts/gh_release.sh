#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# scripts/gh_release.sh — GitHub-Release per REST-API erstellen.
#
# Fuer Hosts OHNE 'gh'-CLI (Release-Schritt 4 der RELEASE_CHECKLIST.md).
# Das Token kommt aus dem Credential-Store (`git credential fill`) und wird
# NICHT ausgegeben. Das Ziel-Repo wird aus dem origin-Remote abgeleitet.
#
# Aufruf:
#   scripts/gh_release.sh <tag> <name> <body-datei> [kanal]
# Beispiel:
#   scripts/gh_release.sh v1.10.5 "v1.10.5 — Titel" notes.md
#   scripts/gh_release.sh v1.10.5-ahorn "v1.10.5-ahorn — Titel" notes.md kanal
#
# Mit 'kanal' wird das Release als Vorabversion und NICHT als "Latest"
# angelegt. Nur so bleibt es fuer die Standard-Haeuser unsichtbar: deren
# Updater fragt /releases/latest, und das liefert nie eine Vorabversion.
# ---------------------------------------------------------------------------
set -euo pipefail

if [ "$#" -ne 3 ] && [ "$#" -ne 4 ]; then
  echo "Aufruf: $0 <tag> <name> <body-datei> [kanal]" >&2
  exit 2
fi
TAG="$1"; NAME="$2"; BODY_FILE="$3"; ART="${4:-}"
if [ -n "$ART" ] && [ "$ART" != "kanal" ]; then
  echo "FEHLER: viertes Argument darf nur 'kanal' sein" >&2
  exit 2
fi
# Schutz gegen Verwechslung: Kanal-Tags tragen einen Anhang (v1.2.3-ahorn),
# Standard-Tags nicht. Ein Kanal-Release als "Latest" ginge an alle Haeuser.
case "$TAG" in
  *-*) [ "$ART" = "kanal" ] || { echo "FEHLER: Tag '$TAG' hat einen Kanal-Anhang, aber 'kanal' fehlt" >&2; exit 2; } ;;
  *)   [ -z "$ART" ] || { echo "FEHLER: 'kanal' angegeben, aber Tag '$TAG' hat keinen Anhang" >&2; exit 2; } ;;
esac

[ -f "$BODY_FILE" ] || { echo "FEHLER: Body-Datei nicht gefunden: $BODY_FILE" >&2; exit 2; }

# Ziel-Repo (OWNER/REPO) aus dem origin-Remote ableiten — funktioniert fuer
# https://github.com/OWNER/REPO(.git) und git@github.com:OWNER/REPO(.git).
ORIGIN=$(git config --get remote.origin.url)
# Kein lazy '+?' verwenden - POSIX-ERE kennt das nicht, '.git' bliebe im
# Namen haengen und die API-URL liefe ins 404. Zweistufig abschneiden.
REPO=$(printf '%s' "$ORIGIN" | sed -E 's#.*github[.]com[/:]##; s#[.]git$##')
[ -n "$REPO" ] || { echo "FEHLER: konnte OWNER/REPO nicht aus '$ORIGIN' ableiten" >&2; exit 1; }

TOKEN=$(printf 'protocol=https\nhost=github.com\n\n' | git credential fill | sed -n 's/^password=//p')
[ -n "$TOKEN" ] || { echo "FEHLER: kein Token aus 'git credential fill'" >&2; exit 1; }

PAYLOAD=$(python -c "import json,sys
d={'tag_name':sys.argv[1],'name':sys.argv[2],
   'body':open(sys.argv[3],encoding='utf-8').read(),
   'draft':False,'prerelease':sys.argv[4]=='kanal',
   'make_latest':'false' if sys.argv[4]=='kanal' else 'true'}
print(json.dumps(d))" "$TAG" "$NAME" "$BODY_FILE" "$ART")

# Body + HTTP-Status in einer Antwort einsammeln (keine Temp-Datei).
RESP=$(curl -s -w $'\n%{http_code}' -X POST \
  -H "Authorization: Bearer $TOKEN" \
  -H "Accept: application/vnd.github+json" \
  -H "X-GitHub-Api-Version: 2022-11-28" \
  "https://api.github.com/repos/$REPO/releases" \
  -d "$PAYLOAD")

HTTP=$(printf '%s' "$RESP" | tail -n1)
BODY=$(printf '%s' "$RESP" | sed '$d')

if [ "$HTTP" = "201" ]; then
  URL=$(printf '%s' "$BODY" | python -c "import json,sys; print(json.load(sys.stdin).get('html_url',''))")
  echo "Release erstellt ($HTTP): $URL"
else
  echo "FEHLER ($HTTP) beim Anlegen des Release:" >&2
  printf '%s\n' "$BODY" >&2
  exit 1
fi
