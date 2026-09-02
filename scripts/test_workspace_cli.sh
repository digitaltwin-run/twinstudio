#!/usr/bin/env bash
set -euo pipefail

evidence_root="${TWINSTUDIO_CLI_E2E_ROOT:-$(mktemp -d /tmp/twinstudio-workspace-cli.XXXXXX)}"
port="${TWINSTUDIO_CLI_E2E_PORT:-18500}"
twinstudio_bin="${TWINSTUDIO_BIN:-.venv/bin/twinstudio}"
mkdir -p "$evidence_root/data" "$evidence_root/workspaces"

export TWINSTUDIO_DATA_DIR="$evidence_root/data"
export TWINSTUDIO_WORKSPACES_ROOT="$evidence_root/workspaces"
export TWINSTUDIO_KICAD_ROOT="$evidence_root/workspaces"
export DATABASE_URL="sqlite:///$evidence_root/data/twinstudio.db"
export DEV_AUTH_BYPASS=true
export TWINSTUDIO_PUBLIC_URL="http://127.0.0.1:$port"

"$twinstudio_bin" serve --host 127.0.0.1 --port "$port" >"$evidence_root/server.log" 2>&1 &
server_pid=$!
cleanup() {
  kill "$server_pid" >/dev/null 2>&1 || true
  wait "$server_pid" >/dev/null 2>&1 || true
}
trap cleanup EXIT

for _attempt in $(seq 1 60); do
  if curl -fsS "http://127.0.0.1:$port/health" >"$evidence_root/health.json" 2>/dev/null; then
    break
  fi
  sleep 0.25
done
curl -fsS "http://127.0.0.1:$port/health" >/dev/null

cli=("$twinstudio_bin" workspace --url "http://127.0.0.1:$port")
"${cli[@]}" create 'CLI source' --project-id cli-source --kind electronics \
  >"$evidence_root/create.json"
"${cli[@]}" upload cli-source LICENSE --path docs/LICENSE-reference.txt \
  >"$evidence_root/upload.json"
"${cli[@]}" upload cli-source LICENSE --path pcb/main.kicad_pcb \
  >"$evidence_root/upload-pcb.json"

pcb_sha="$(
  "${cli[@]}" show cli-source \
    | jq -r '.files[] | select(.path == "pcb/main.kicad_pcb") | .sha256'
)"
set +e
"${cli[@]}" upload cli-source LICENSE --path pcb/main.kicad_pcb \
  --overwrite --expected-sha256 "$pcb_sha" \
  >"$evidence_root/eda-guard.out" 2>"$evidence_root/eda-guard.err"
eda_guard_status=$?
set -e
if [[ "$eda_guard_status" -eq 0 ]] \
  || ! rg -q 'PROJECT_EDA_CANDIDATE_REQUIRED' "$evidence_root/eda-guard.err"; then
  echo 'EDA overwrite guard was not enforced' >&2
  exit 1
fi

"${cli[@]}" show cli-source >"$evidence_root/source.json"
"${cli[@]}" export cli-source --out "$evidence_root/cli-source.zip" \
  >"$evidence_root/export.out"
unzip -t "$evidence_root/cli-source.zip" >"$evidence_root/unzip-test.txt"
"${cli[@]}" import "$evidence_root/cli-source.zip" \
  --name 'CLI copy' --project-id cli-copy >"$evidence_root/import.json"
"${cli[@]}" show cli-copy >"$evidence_root/copy.json"

source_fingerprint="$(jq -r '.project.content_fingerprint_sha256' "$evidence_root/source.json")"
copy_fingerprint="$(jq -r '.project.content_fingerprint_sha256' "$evidence_root/copy.json")"
if [[ "$source_fingerprint" != "$copy_fingerprint" ]]; then
  echo "content fingerprint mismatch: $source_fingerprint != $copy_fingerprint" >&2
  exit 1
fi

"${cli[@]}" upload cli-copy README.md --path docs/extra.md \
  >"$evidence_root/upload-extra.json"
"${cli[@]}" merge-plan cli-source cli-copy --strategy reject \
  >"$evidence_root/merge-plan.json"
plan_sha="$(jq -r '.plan_sha256' "$evidence_root/merge-plan.json")"
if [[ ! "$plan_sha" =~ ^[0-9a-f]{64}$ ]]; then
  echo 'merge plan has no valid SHA-256' >&2
  exit 1
fi
"${cli[@]}" merge-apply cli-source cli-copy --strategy reject \
  --plan-sha256 "$plan_sha" >"$evidence_root/merge-apply.json"
"${cli[@]}" download cli-source docs/extra.md \
  --out "$evidence_root/downloaded-extra.md" >"$evidence_root/download.out"
cmp README.md "$evidence_root/downloaded-extra.md"
"${cli[@]}" plan cli-source >"$evidence_root/planfile.json"

jq -n \
  --arg status passed \
  --arg evidence_root "$evidence_root" \
  --arg content_fingerprint_sha256 "$source_fingerprint" \
  --arg merge_plan_sha256 "$plan_sha" \
  --argjson eda_overwrite_guard_exit "$eda_guard_status" \
  '{
    status: $status,
    evidence_root: $evidence_root,
    content_fingerprint_sha256: $content_fingerprint_sha256,
    merge_plan_sha256: $merge_plan_sha256,
    eda_overwrite_guard_exit: $eda_overwrite_guard_exit
  }' | tee "$evidence_root/report.json"
