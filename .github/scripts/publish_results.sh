#!/usr/bin/env bash
# Merge a bundle of small result files into the results branch, then push.
#
#   publish_results.sh <bundle directory> <commit message>
#
# Run from a checkout whose origin is the repository. Runs no project code, because the job calling it can write.
# The bundle comes from a job that ran project code, so nothing in it is trusted. Only these paths are copied, and
# any other path, any segment starting with a dot and anything that is not a regular file stops the whole publish:
#   ledger/*.jsonl         Append-only by byte. The old content must be an exact prefix of the new.
#   ledger/*, decisions/*  Append-only. A new file is added. Changing an existing one is refused.
#   run_log/*.jsonl        Append-only by line. Existing lines keep their place, and only new lines are added.
#   status.json, live_state.json   Current state. Replaced.
set -euo pipefail

bundle=$(cd "$1" && pwd)
message=$2
branch=${RESULTS_BRANCH:-results}

git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"

check_bundle() {
  # Before anything is copied, so a bad bundle changes nothing.
  (
    cd "$bundle"
    find . -mindepth 1 -print0
  ) | while IFS= read -r -d '' relative; do
    relative=${relative#./}
    case "/$relative/" in
      */.*)
        echo "Refusing a hidden path in the bundle: $relative" >&2
        exit 1
        ;;
    esac
    if [ -d "$bundle/$relative" ] && [ ! -L "$bundle/$relative" ]; then
      continue
    fi
    if [ -L "$bundle/$relative" ] || [ ! -f "$bundle/$relative" ]; then
      echo "Refusing something that is not a regular file: $relative" >&2
      exit 1
    fi
    case "$relative" in
      status.json | live_state.json | run_log/*.jsonl | ledger/* | decisions/*) ;;
      *)
        echo "Refusing a path that is not on the list: $relative" >&2
        exit 1
        ;;
    esac
  done
}

merge_bundle() {
  (
    cd "$bundle"
    find . -type f -print0
  ) | while IFS= read -r -d '' relative; do
    relative=${relative#./}
    source_file="$bundle/$relative"
    mkdir -p "$(dirname "$relative")"
    case "$relative" in
      ledger/*.jsonl)
        if [ -e "$relative" ]; then
          size=$(wc -c < "$relative")
          if ! head -c "$size" "$source_file" | cmp -s - "$relative"; then
            echo "Refusing to change an append-only record: $relative" >&2
            exit 1
          fi
        fi
        cp "$source_file" "$relative"
        ;;
      ledger/* | decisions/*)
        if [ -e "$relative" ] && ! cmp -s "$relative" "$source_file"; then
          echo "Refusing to change an append-only record: $relative" >&2
          exit 1
        fi
        cp "$source_file" "$relative"
        ;;
      run_log/*.jsonl)
        touch "$relative"
        # Every existing line is kept, duplicates too. Only the incoming file is filtered.
        awk 'NR==FNR { seen[$0] = 1; print; next } !($0 in seen) { seen[$0] = 1; print }' \
          "$relative" "$source_file" > "$relative.merged"
        mv "$relative.merged" "$relative"
        ;;
      status.json | live_state.json)
        cp "$source_file" "$relative"
        ;;
    esac
  done
}

check_bundle

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
