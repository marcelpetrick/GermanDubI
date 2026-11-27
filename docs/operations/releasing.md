# Creating a release

A release starts with an annotated `vX.Y.Z` tag. `setuptools-scm` derives the build version
from that tag. See [`AGENTS.md`](../../AGENTS.md) section 3.

## Before tagging

1. Move the release's entries out of `## [Unreleased]` in `CHANGELOG.md` into a
   `## [X.Y.Z] - YYYY-MM-DD` section. The release workflow refuses to publish a version
   with no section of its own, and uses that section as the release notes.
2. Run the full gate on the exact commit you intend to tag:

   ```bash
   ./localPipeline.sh
   ```

3. Confirm the working tree is clean. A dirty tree produces a version with a `.dNNNNNNNN`
   suffix, which will not match the tag.

## Tagging

```bash
git tag -a v0.1.0 -m "GermanDubI 0.1.0"
git push origin main --follow-tags
```

Pushing the tag is the act that publishes. The `Release` workflow then:

- reruns the entire pipeline at the tagged commit, because a tag can be pushed at a commit
  that never passed CI;
- checks that the version `setuptools-scm` derives equals the tag;
- checks that `CHANGELOG.md` has a non-empty section for exactly this version;
- installs the built wheel into a clean virtualenv and runs `germandubi version`;
- publishes the wheel and the sdist as a GitHub release, with the changelog section as its
  notes.

The release job publishes the GitHub release after its checks pass. The container job
then builds and publishes the image for `linux/amd64` and `linux/arm64`.

## If it fails

If the release job fails before publication, delete the tag, fix the cause, and tag again:

```bash
git tag -d v0.1.0
git push origin :refs/tags/v0.1.0
```

Keep tags that already have a published release. If container publishing fails after
the release is public, rerun the failed image jobs when the failure is transient. Publish
a new patch version if a source change is needed.

## Verifying afterwards

```bash
gh release view vX.Y.Z
docker buildx imagetools inspect ghcr.io/marcelpetrick/germandubi:X.Y.Z
```

The version the CLI reports should match the tag exactly, with no local segment:

```bash
germandubi version
```
