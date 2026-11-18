#!/usr/bin/env bash
# Decides whether a smoke workflow's macOS/Windows jobs should run.
#
# Org Actions budget (2026-11-17): macOS minutes cost 10x Linux, so the
# bundle smokes no longer run on every push. They run on PRs that touch
# packaging files (paths filter in the workflow), on manual dispatch, and
# nightly on weekdays -- but the nightly run only spends macOS/Windows
# minutes when packaging files on main changed since the last successful
# nightly run. A failed nightly run keeps retrying each night
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
# Same set as the smokes' PR paths filters: packaging files only. src/ and
# web/ changes are covered by the Linux unit tests on every PR and by the
# release build's smoke; running macOS/Windows for them nightly could use
# most of the org's 3,000 free minutes a month on its own (2026-11-17).
if echo "$files" | grep -qE '^(scripts|config)/|^src/app_root\.py$|^requirements\.txt$|^(run|install|smoke|STOP)\.(command|bat)$|^\.github/(workflows|scripts)/'; then
  out true "packaging files changed since $last"
else
  out false "no packaging files changed since $last"
fi
