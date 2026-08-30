# Creating a release

A release is an annotated `vX.Y.Z` tag. Nothing else creates one, and no version number is
ever edited by hand: `setuptools-scm` derives the version from the tag, so the tag *is* the
version. See [`AGENTS.md`](../../AGENTS.md) section 3.

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

Any of those failing stops the release before it is visible. Nothing is published
partially: the release is created in one step, at the end.

## If it fails

Delete the tag, fix the cause, and tag again:

```bash
git tag -d v0.1.0
git push origin :refs/tags/v0.1.0
```

Do not force-push a tag that already produced a published release; publish a new patch
version instead. Someone may already have downloaded the artifacts from the old one.

## Verifying afterwards

```bash
pip download germandubi==X.Y.Z --no-deps -d /tmp/check   # if published to an index
gh release view vX.Y.Z
```

The version the CLI reports should match the tag exactly, with no local segment:

```bash
germandubi version
```
