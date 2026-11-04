#!/usr/bin/env bash
# Merge a bundle of small result files into the results branch, then push.
#
#   publish_results.sh <bundle directory> <commit message>
#
# Run from a checkout whose origin is the repository. Runs no project code, because the job calling it can write.
# Files are treated by where they live:
#   *.jsonl                Append-only. Existing lines keep their place, and only new lines are added.
#   ledger/, decisions/    Append-only. A new file is added. Changing an existing one is refused.
#   anything else          Current state, such as status.json. Replaced.
set -euo pipefail

bundle=$(cd "$1" && pwd)
message=$2
branch=${RESULTS_BRANCH:-results}

git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"

merge_bundle() {
  (
    cd "$bundle"
    find . -type f -print0
  ) | while IFS= read -r -d '' relative; do
    relative=${relative#./}
    source_file="$bundle/$relative"
    mkdir -p "$(dirname "$relative")"
    case "$relative" in
      *.jsonl)
        touch "$relative"
        awk '!seen[$0]++' "$relative" "$source_file" > "$relative.merged"
        mv "$relative.merged" "$relative"
        ;;
      ledger/* | decisions/*)
        if [ -e "$relative" ] && ! cmp -s "$relative" "$source_file"; then
          echo "Refusing to change an append-only record: $relative" >&2
          exit 1
        fi
        cp "$source_file" "$relative"
        ;;
      *)
        cp "$source_file" "$relative"
        ;;
    esac
  done
}

# Another job may push between our fetch and our push. Start again from the new tip, a few times.
for attempt in 1 2 3 4 5; do
  if git ls-remote --exit-code --heads origin "$branch" > /dev/null 2>&1; then
    git fetch --quiet --depth=1 origin "$branch"
    git checkout --quiet --force -B "$branch" FETCH_HEAD
  else
    git checkout --quiet --force --orphan "$branch"
    git rm --quiet -rf --ignore-unmatch .
    git clean --quiet -fdx
  fi
  merge_bundle
  git add --all
  if git diff --cached --quiet; then
    echo "Nothing new to publish."
    exit 0
  fi
  git commit --quiet -m "$message"
  if git push --quiet origin "$branch"; then
    echo "Published to $branch."
    exit 0
  fi
  echo "Push attempt $attempt lost a race. Trying again."
  sleep $((attempt * 5))
done
echo "Could not publish after several attempts." >&2
exit 1
