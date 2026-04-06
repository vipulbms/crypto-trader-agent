#!/usr/bin/env bash
# =============================================================================
# Kryptos — Retroactive Epic→Story Sub-Issue Linker
#
# Run this ONCE to link the 45 already-created Stories to their parent Epics
# using the GitHub Sub-Issues API.
#
# Epics and Stories must already exist with labels:
#   - Epics:   "epic" + "E{N}"
#   - Stories: "story" + "E{N}"
#
# Usage:    bash scripts/link_epics.sh
# Requires: gh CLI authenticated — run: gh auth status
# =============================================================================

set -e
REPO="vipulbms/crypto-trader-agent"

link_epic() {
  local epic_label="$1"   # e.g. "E1"

  echo "==> Processing ${epic_label}..."

  # Find the epic issue number (has both "epic" and the epoch label)
  local epic_num
  epic_num=$(gh issue list \
    --repo "$REPO" \
    --label "epic,${epic_label}" \
    --state all \
    --json number \
    --jq '.[0].number')

  if [[ -z "$epic_num" || "$epic_num" == "null" ]]; then
    echo "    [SKIP] No epic found with labels: epic, ${epic_label}"
    return
  fi

  echo "    Epic #${epic_num} found."

  # Find all story issue numbers for this epic
  local story_nums
  story_nums=$(gh issue list \
    --repo "$REPO" \
    --label "story,${epic_label}" \
    --state all \
    --json number \
    --jq '.[].number')

  if [[ -z "$story_nums" ]]; then
    echo "    [SKIP] No stories found with labels: story, ${epic_label}"
    return
  fi

  for story_num in $story_nums; do
    echo -n "    Linking Story #${story_num} → Epic #${epic_num}... "
    gh api --method POST \
      -H "Accept: application/vnd.github+json" \
      -H "X-GitHub-Api-Version: 2026-03-10" \
      "/repos/${REPO}/issues/${epic_num}/sub_issues" \
      -F "sub_issue_id=${story_num}" \
      --silent 2>/dev/null \
      && echo "OK" \
      || echo "FAILED (already linked or API error)"
  done
}

# -----------------------------------------------------------------------------
echo "Linking Stories to Epics via GitHub Sub-Issues API..."
echo ""

for N in 1 2 3 4 5 6 7 8 9 10 11 12; do
  link_epic "E${N}"
done

echo ""
echo "Done."
