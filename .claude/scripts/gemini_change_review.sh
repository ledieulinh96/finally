#!/usr/bin/env bash
# Stop hook: have the Gemini CLI review every change since the last commit
# (tracked diff vs HEAD + untracked files). Runs async; writes the review to
# .claude/reviews/gemini-latest.md. Skips if nothing changed since the last review.
#
# Override the model chain with GEMINI_REVIEW_MODELS="model-a model-b ...".
set -u

ROOT="${CLAUDE_PROJECT_DIR:-$(git rev-parse --show-toplevel 2>/dev/null)}"
cd "$ROOT" || exit 0
git rev-parse --git-dir >/dev/null 2>&1 || exit 0
command -v gemini >/dev/null 2>&1 || { echo '{"systemMessage":"Gemini review skipped: gemini CLI not installed"}'; exit 0; }

OUT_DIR=".claude/reviews"
mkdir -p "$OUT_DIR"
LOCK="$OUT_DIR/.lock"
mkdir "$LOCK" 2>/dev/null || exit 0          # another review is already running
trap 'rmdir "$LOCK" 2>/dev/null' EXIT

MODELS="${GEMINI_REVIEW_MODELS:-gemini-3.8-flash gemini-3.7-flash gemini-3.1-pro-preview gemini-pro-latest}"
MAX_BYTES=300000
# Never send secrets, databases, or our own review output to Gemini.
# glob magic + **/ makes these match at any depth (e.g. frontend/.env.local).
EXCLUDES=(
  ':(exclude,glob)**/.env'      ':(exclude,glob)**/.env.*'    ':(exclude,glob)**/.envrc'
  ':(exclude,glob)**/*.pem'     ':(exclude,glob)**/*.key'     ':(exclude,glob)**/*.p12'
  ':(exclude,glob)**/*.db'      ':(exclude,glob)**/*.sqlite*' ':(exclude,glob)db/**'
  ':(exclude,glob).claude/reviews/**'
)

DIFF="$(mktemp)"; RESULT="$(mktemp)"
trap 'rm -f "$DIFF" "$DIFF.cut" "$RESULT"; rmdir "$LOCK" 2>/dev/null' EXIT
{
  git --no-pager diff HEAD --no-color -- . "${EXCLUDES[@]}"
  git ls-files --others --exclude-standard -z -- . "${EXCLUDES[@]}" |
    while IFS= read -r -d '' f; do
      git --no-pager diff --no-index --no-color -- /dev/null "$f"
    done
} > "$DIFF" 2>/dev/null

[ -s "$DIFF" ] || exit 0                      # no changes since last commit

HASH="$(shasum -a 256 "$DIFF" | cut -d' ' -f1)"
[ "$(cat "$OUT_DIR/.last_hash" 2>/dev/null)" = "$HASH" ] && exit 0   # already reviewed

SIZE=$(wc -c < "$DIFF" | tr -d ' ')
NOTE=""
if [ "$SIZE" -gt "$MAX_BYTES" ]; then
  head -c "$MAX_BYTES" "$DIFF" > "$DIFF.cut" && mv "$DIFF.cut" "$DIFF"
  NOTE=" (diff truncated to ${MAX_BYTES} bytes of ${SIZE})"
fi

PROMPT="You are a senior code reviewer. The input is a unified git diff of all uncommitted changes in this project (tracked changes vs HEAD plus new untracked files)${NOTE}. Review it for bugs, security issues, inconsistencies with the project's planning docs, risky changes, and simplification opportunities. Output concise Markdown grouped by severity (Critical / Warning / Suggestion), citing file paths. If everything looks fine, say so briefly. Output only the review."

ERR="$OUT_DIR/gemini-last-error.log"; : > "$ERR"
USED=""
for m in $MODELS; do
  if gemini --skip-trust -m "$m" -p "$PROMPT" < "$DIFF" > "$RESULT" 2>>"$ERR" && [ -s "$RESULT" ]; then
    USED="$m"; break
  fi
  echo "--- model $m failed ---" >> "$ERR"
done

if [ -z "$USED" ]; then
  rm -f "$RESULT"
  echo "{\"systemMessage\":\"Gemini review failed on all models ($MODELS). See $ERR\"}"
  exit 0
fi

{
  echo "# Gemini review of uncommitted changes"
  echo
  echo "_$(date '+%Y-%m-%d %H:%M:%S') · model: ${USED} · base: $(git rev-parse --short HEAD)${NOTE}_"
  echo
  cat "$RESULT"
} > "$OUT_DIR/gemini-latest.md"
rm -f "$RESULT"
echo "$HASH" > "$OUT_DIR/.last_hash"
echo "{\"systemMessage\":\"Gemini review ready (${USED}): $OUT_DIR/gemini-latest.md\"}"
