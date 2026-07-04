#!/usr/bin/env bash
# Probe a candidate price URL and classify it. Read-only GET of a public price page.
# Usage: bash probe.sh <url> [extra curl args...]
set -u
URL="${1:?usage: probe.sh <url>}"
shift || true
UA="Mozilla/5.0"

body="$(curl -s --max-time 20 -A "$UA" -H "X-Requested-With: XMLHttpRequest" "$URL" "$@" 2>/dev/null)"
code="$(curl -s --max-time 20 -A "$UA" -o /dev/null -w '%{http_code}' "$URL" "$@" 2>/dev/null)"

echo "URL:    $URL"
echo "HTTP:   $code"

head="$(printf '%s' "$body" | head -c 400)"
trimmed="$(printf '%s' "$body" | sed -e 's/^[[:space:]]*//' | head -c 1)"

if printf '%s' "$body" | grep -qiE "just a moment|challenges\.cloudflare|cf-browser-verification"; then
  echo "VERDICT: CLOUDFLARE-BLOCKED — skip this source (cannot scrape with curl)."
elif [ "$trimmed" = "{" ] || [ "$trimmed" = "[" ]; then
  echo "VERDICT: JSON — best case. Price field names:"
  printf '%s' "$body" | grep -oE '"[a-zA-Z_]+":' | sort -u | head -20 | sed 's/^/         /'
elif printf '%s' "$body" | grep -qiE "<table|<td|<html"; then
  echo "VERDICT: HTML — look for an underlying data endpoint instead of scraping the page:"
  printf '%s' "$body" | grep -oiE "url:[^,]{0,60}|/[A-Za-z]+/[A-Za-z]+Partial|/api/[A-Za-z/]+" | sort -u | head -10 | sed 's/^/         /'
else
  echo "VERDICT: UNKNOWN — first 400 bytes:"
  echo "$head"
fi
