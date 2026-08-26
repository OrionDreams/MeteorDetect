#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "$script_dir/.." && pwd)"
cd "$repo_root"

mode="patch"

fail() {
  echo "do-git-release failed: $*" >&2
  exit 1
}

usage() {
  echo "Usage: $0 [--patch|--minor|--major]" >&2
}

if [[ $# -gt 1 ]]; then
  usage
  exit 2
fi

case "${1:---patch}" in
  --patch) mode="patch" ;;
  --minor) mode="minor" ;;
  --major) mode="major" ;;
  *)
    usage
    exit 2
    ;;
esac

bump_version() {
  local version="$1"
  local bump_mode="$2"
  local major minor patch

  IFS='.' read -r major minor patch <<< "$version"
  case "$bump_mode" in
    patch)
      patch=$((patch + 1))
      ;;
    minor)
      minor=$((minor + 1))
      patch=0
      ;;
    major)
      major=$((major + 1))
      minor=0
      patch=0
      ;;
    *)
      fail "unknown version bump mode: $bump_mode"
      ;;
  esac

  printf '%s.%s.%s\n' "$major" "$minor" "$patch"
}

require_file() {
  local path="$1"
  [[ -f "$path" ]] || fail "$path was not found."
}

current_branch="$(git branch --show-current)"
[[ "$current_branch" == "main" ]] || fail "current branch is '$current_branch', but releases must be made from 'main'."

upstream="$(git rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>/dev/null || true)"
[[ -n "$upstream" ]] || fail "main has no upstream configured. Set the upstream to origin/main first."

git fetch --tags origin

unpushed_count="$(git rev-list --count "$upstream..HEAD")"
[[ "$unpushed_count" == "0" ]] || fail "there are $unpushed_count unpushed commit(s). Push or reconcile them first."

unpulled_count="$(git rev-list --count "HEAD..$upstream")"
[[ "$unpulled_count" == "0" ]] || fail "local main is behind $upstream by $unpulled_count commit(s). Pull or reconcile before releasing."

dirty_files="$(git status --porcelain --untracked-files=all | awk '{print $2}')"
if [[ -n "$dirty_files" ]]; then
  unexpected_dirty="$(
    printf '%s\n' "$dirty_files" |
      grep -Ev '^(docs/CHANGELOG.md)$' || true
  )"
  [[ -z "$unexpected_dirty" ]] || fail "working tree has non-changelog changes. Commit, stash, or discard them first:
$unexpected_dirty"
fi

latest_tag="$(
  git tag -l 'v[0-9]*.[0-9]*.[0-9]*' |
    grep -E '^v[0-9]+\.[0-9]+\.[0-9]+$' |
    sort -V |
    tail -n 1
)"

if [[ -z "$latest_tag" ]]; then
  latest_version="0.0.0"
else
  latest_version="${latest_tag#v}"
fi

next_version="$(bump_version "$latest_version" "$mode")"
next_tag="v$next_version"

if git rev-parse -q --verify "refs/tags/$next_tag" >/dev/null; then
  fail "tag $next_tag already exists."
fi

echo "Latest app tag: ${latest_tag:-none}"
echo "Next app release: $next_tag"

read -r -p "Have you updated the changelog for version $next_tag? [y/N] " changelog_answer
case "${changelog_answer,,}" in
  y|yes)
    ;;
  n|no|"")
    fail "aborted because the changelog was not confirmed for $next_tag."
    ;;
  *)
    fail "changelog confirmation must be yes or no."
    ;;
esac

app_project="src/MeteorDetect.App/MeteorDetect.App.csproj"
app_manifest="src/MeteorDetect.App/app.manifest"
detector_init="meteor_detector/__init__.py"
require_file "$app_project"
require_file "$detector_init"

detector_version="$(
  sed -n -E 's/^__version__[[:space:]]*=[[:space:]]*"([0-9]+\.[0-9]+\.[0-9]+)".*$/\1/p' "$detector_init"
)"
[[ -n "$detector_version" ]] || fail "could not read detector runtime version from $detector_init."

echo "Current detector runtime: $detector_version"
read -r -p "Should I bump the detector version? [n]o, [p]atch, [m]inor, m[a]jor: " detector_answer
case "${detector_answer,,}" in
  ""|n|no)
    next_detector_version="$detector_version"
    ;;
  p|patch)
    next_detector_version="$(bump_version "$detector_version" patch)"
    ;;
  m|minor)
    next_detector_version="$(bump_version "$detector_version" minor)"
    ;;
  a|major)
    next_detector_version="$(bump_version "$detector_version" major)"
    ;;
  *)
    fail "detector version answer must be n, p, m, or a."
    ;;
esac

sed -i -E "s#<Version>[0-9]+\.[0-9]+\.[0-9]+</Version>#<Version>$next_version</Version>#" "$app_project"
sed -i -E "s#<PackageVersion>[0-9]+\.[0-9]+\.[0-9]+</PackageVersion>#<PackageVersion>$next_version</PackageVersion>#" "$app_project"
sed -i -E "s#<AssemblyVersion>[0-9]+\.[0-9]+\.[0-9]+\.0</AssemblyVersion>#<AssemblyVersion>$next_version.0</AssemblyVersion>#" "$app_project"
sed -i -E "s#<FileVersion>[0-9]+\.[0-9]+\.[0-9]+\.0</FileVersion>#<FileVersion>$next_version.0</FileVersion>#" "$app_project"
sed -i -E "s#<InformationalVersion>v[0-9]+\.[0-9]+\.[0-9]+</InformationalVersion>#<InformationalVersion>$next_tag</InformationalVersion>#" "$app_project"

if [[ -f "$app_manifest" ]]; then
  sed -i -E "s#(<assemblyIdentity version=\")[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+(\")#\1$next_version.0\2#" "$app_manifest"
fi

if [[ "$next_detector_version" != "$detector_version" ]]; then
  sed -i -E "s#^__version__[[:space:]]*=[[:space:]]*\"[0-9]+\.[0-9]+\.[0-9]+\"#__version__ = \"$next_detector_version\"#" "$detector_init"
fi

grep -q "<Version>$next_version</Version>" "$app_project" || fail "failed to set app Version in $app_project."
grep -q "<PackageVersion>$next_version</PackageVersion>" "$app_project" || fail "failed to set app PackageVersion in $app_project."
grep -q "<AssemblyVersion>$next_version.0</AssemblyVersion>" "$app_project" || fail "failed to set app AssemblyVersion in $app_project."
grep -q "<FileVersion>$next_version.0</FileVersion>" "$app_project" || fail "failed to set app FileVersion in $app_project."
grep -q "<InformationalVersion>$next_tag</InformationalVersion>" "$app_project" || fail "failed to set app InformationalVersion in $app_project."
grep -q "__version__ = \"$next_detector_version\"" "$detector_init" || fail "failed to set detector runtime version in $detector_init."

git add "$app_project" "$detector_init"
if [[ -f "$app_manifest" ]]; then
  git add "$app_manifest"
fi
if ! git diff --quiet -- docs/CHANGELOG.md; then
  git add docs/CHANGELOG.md
fi

git diff --cached --quiet && fail "no release changes were staged."

commit_message="chore: prepare $next_tag release"
if [[ "$next_detector_version" != "$detector_version" ]]; then
  commit_message="$commit_message with detector runtime $next_detector_version"
fi

git commit -m "$commit_message"

release_commit="$(git rev-parse HEAD)"
git push origin "HEAD:$current_branch"
remote_branch_commit="$(git ls-remote origin "refs/heads/$current_branch" | awk '{print $1}')"
[[ "$remote_branch_commit" == "$release_commit" ]] || fail "origin/$current_branch does not point at the release commit after push."

git tag "$next_tag"

read -r -p "Tag $next_tag created. Push now? [y/N] " push_tag_answer
case "${push_tag_answer,,}" in
  y|yes)
    git push origin "$next_tag"
    echo "Tag pushed"
    ;;
  n|no|"")
    echo "Tag not pushed"
    ;;
  *)
    fail "tag push confirmation must be yes or no. Tag $next_tag exists locally and was not pushed."
    ;;
esac

echo "Prepared $next_tag."
echo "App version: $next_version"
echo "Detector runtime: $next_detector_version"
