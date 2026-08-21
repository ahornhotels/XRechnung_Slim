#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# scripts/gh_release.sh — GitHub-Release per REST-API erstellen.
#
# Fuer Hosts OHNE 'gh'-CLI (Release-Schritt 4 der RELEASE_CHECKLIST.md).
# Das Token kommt aus dem Credential-Store (`git credential fill`) und wird
# NICHT ausgegeben. Das Ziel-Repo wird aus dem origin-Remote abgeleitet.
#
# Aufruf:
#   scripts/gh_release.sh <tag> <name> <body-datei>
# Beispiel:
#   scripts/gh_release.sh v1.10.5 "v1.10.5 — Titel" notes.md
# ---------------------------------------------------------------------------
set -euo pipefail

if [ "$#" -ne 3 ]; then
  echo "Aufruf: $0 <tag> <name> <body-datei>" >&2
  exit 2
fi
TAG="$1"; NAME="$2"; BODY_FILE="$3"

[ -f "$BODY_FILE" ] || { echo "FEHLER: Body-Datei nicht gefunden: $BODY_FILE" >&2; exit 2; }

# Ziel-Repo (OWNER/REPO) aus dem origin-Remote ableiten — funktioniert fuer
# https://github.com/OWNER/REPO(.git) und git@github.com:OWNER/REPO(.git).
ORIGIN=$(git config --get remote.origin.url)
REPO=$(printf '%s' "$ORIGIN" | sed -E 's#.*github\.com[/:]([^/]+/[^/]+?)(\.git)?$#\1#')
[ -n "$REPO" ] || { echo "FEHLER: konnte OWNER/REPO nicht aus '$ORIGIN' ableiten" >&2; exit 1; }

TOKEN=$(printf 'protocol=https\nhost=github.com\n\n' | git credential fill | sed -n 's/^password=//p')
[ -n "$TOKEN" ] || { echo "FEHLER: kein Token aus 'git credential fill'" >&2; exit 1; }

PAYLOAD=$(python -c "import json,sys
d={'tag_name':sys.argv[1],'name':sys.argv[2],
   'body':open(sys.argv[3],encoding='utf-8').read(),
   'draft':False,'prerelease':False,'make_latest':'true'}
print(json.dumps(d))" "$TAG" "$NAME" "$BODY_FILE")

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
