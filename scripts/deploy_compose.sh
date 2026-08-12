#!/usr/bin/env bash

set -Eeuo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"

compose=(docker compose -f compose.yaml)
deploy_branch="${DEPLOY_BRANCH:-origin/main}"
deploy_sha="${DEPLOY_COMMIT_SHA:-$(git rev-parse HEAD)}"
app_image="${TWINSTUDIO_APP_IMAGE:-twinstudio-app}:${TWINSTUDIO_APP_TAG:-latest}"
rollback_image="twinstudio-app-rollback:${deploy_sha:0:12}"
health_attempts="${TWINSTUDIO_HEALTH_ATTEMPTS:-30}"
health_interval="${TWINSTUDIO_HEALTH_INTERVAL_SECONDS:-2}"

fail() {
  printf 'deployment failed: %s\n' "$*" >&2
  exit 1
}

command -v docker >/dev/null || fail "docker is not installed"
command -v git >/dev/null || fail "git is not installed"
docker compose version >/dev/null || fail "docker compose is unavailable"
[[ -f .env ]] || fail "missing .env; copy .env.example and provide deployment values"
[[ -z "$(git status --porcelain)" ]] || fail "worktree is not clean"

git fetch --quiet origin
remote_sha="$(git rev-parse "$deploy_branch")"
[[ "$deploy_sha" == "$remote_sha" ]] || fail "$deploy_sha is not the current $deploy_branch ($remote_sha)"

if [[ "${SKIP_CI_GATE:-0}" != "1" ]]; then
  command -v gh >/dev/null || fail "gh is required for the CI gate"
  ci_status="$(gh run list --commit "$deploy_sha" --workflow ci --limit 1 --json status --jq '.[0].status // "missing"')"
  ci_conclusion="$(gh run list --commit "$deploy_sha" --workflow ci --limit 1 --json conclusion --jq '.[0].conclusion // "missing"')"
  [[ "$ci_status" == "completed" && "$ci_conclusion" == "success" ]] || \
    fail "CI is not green for $deploy_sha (status=$ci_status, conclusion=$ci_conclusion)"
fi

"${compose[@]}" config --quiet

old_image_id="$(docker image inspect --format '{{.Id}}' "$app_image" 2>/dev/null || true)"
if [[ -n "$old_image_id" ]]; then
  docker image tag "$old_image_id" "$rollback_image"
fi

rollback() {
  local reason="$1"
  printf 'deployment health check failed: %s\n' "$reason" >&2
  if [[ -z "$old_image_id" ]]; then
    printf 'no previous image is available for rollback\n' >&2
    return 1
  fi
  docker image tag "$rollback_image" "$app_image"
  TWINSTUDIO_BUILD_SHA="rollback-$deploy_sha" "${compose[@]}" up -d --no-deps --force-recreate app
  printf 'rolled back app to image %s\n' "$old_image_id" >&2
  return 1
}

TWINSTUDIO_BUILD_SHA="$deploy_sha" "${compose[@]}" build app
TWINSTUDIO_BUILD_SHA="$deploy_sha" "${compose[@]}" up -d

deployed_image_id="$("${compose[@]}" images -q app)"
deployed_revision="$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$deployed_image_id")"
[[ "$deployed_revision" == "$deploy_sha" ]] || rollback "image label is $deployed_revision, expected $deploy_sha"

published_port="$("${compose[@]}" port app 8000 | head -n 1)"
published_port="${published_port##*:}"
[[ "$published_port" =~ ^[0-9]+$ ]] || rollback "cannot resolve the published app port"
health_url="${TWINSTUDIO_HEALTH_URL:-http://127.0.0.1:${published_port}/health}"

health_payload=""
for ((attempt = 1; attempt <= health_attempts; attempt++)); do
  health_payload="$(curl --fail --silent --show-error --max-time 5 "$health_url" 2>/dev/null || true)"
  if [[ "$health_payload" == *'"status":"ok"'* && "$health_payload" == *"\"revision\":\"$deploy_sha\""* ]]; then
    printf 'deployment succeeded: revision=%s health=%s\n' "$deploy_sha" "$health_url"
    exit 0
  fi
  sleep "$health_interval"
done

rollback "health endpoint did not confirm revision $deploy_sha"
