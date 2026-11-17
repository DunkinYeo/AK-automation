#!/usr/bin/env bash
# Decides whether a smoke workflow's macOS/Windows jobs should run.
#
# Org Actions budget (2026-11-17): macOS minutes cost 10x Linux, so the
# bundle smokes no longer run on every push. They run on PRs that touch
# packaging files (paths filter in the workflow), on manual dispatch, and
# nightly on weekdays -- but the nightly run only spends macOS/Windows
# minutes when main changed in a packaging-relevant way since the last
# successful nightly run. A failed nightly run keeps retrying each night
# until it passes, since "last success" stays behind.
#
# Env: EVENT, REPO, WORKFLOW, SHA, GH_TOKEN. Writes run=true|false to
# $GITHUB_OUTPUT.
set -uo pipefail

out() { echo "run=$1" >> "$GITHUB_OUTPUT"; echo "run=$1 ($2)"; }

if [ "$EVENT" != "schedule" ]; then
  out true "$EVENT"; exit 0
fi

last=$(gh run list -R "$REPO" --workflow "$WORKFLOW" --event schedule \
         --status success --limit 1 --json headSha --jq '.[0].headSha // ""' 2>/dev/null) || last=""
if [ -z "$last" ]; then
  out true "no earlier successful nightly run"; exit 0
fi
if [ "$last" = "$SHA" ]; then
  out false "main unchanged since $last"; exit 0
fi

files=$(gh api "repos/$REPO/compare/$last...$SHA" --jq '.files[].filename' 2>/dev/null) || {
  out true "could not compare $last...$SHA"; exit 0
}
# Same set as the PR paths filters (config/ ships in the ZIP), plus src/
# and web/: a nightly run is where a src-only change that broke the bundle
# gets caught.
if echo "$files" | grep -qE '^(src|web|scripts|config)/|^requirements\.txt$|^(run|install|smoke|STOP)\.(command|bat)$|^\.github/(workflows|scripts)/'; then
  out true "bundle-relevant files changed since $last"
else
  out false "only docs/tests changed since $last"
fi
