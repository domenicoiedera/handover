# Releasing

Version is single-sourced in `pyproject.toml` (and mirrored in `handover/__init__.py`; a test asserts they agree).

1. Bump the version in both places, update `CHANGELOG.md`.
2. Run the suite: `env -u PYTHONPATH -u VIRTUAL_ENV python3.12 -m unittest discover -s tests -t .`
3. Build **from a clean directory**, never from the repository root - a local `build/` shadows the `build` module:

   ```bash
   rm -rf /tmp/ho-build && mkdir -p /tmp/ho-build
   git archive --format=tar HEAD | tar -x -C /tmp/ho-build
   cd /tmp/ho-build && python3.12 -m build --outdir dist
   ```

4. Commit, tag `vX.Y.Z`, push branch and tag.
5. Create the release with both artifacts:

   ```bash
   gh release create vX.Y.Z \
     /tmp/ho-build/dist/handover-X.Y.Z-py3-none-any.whl \
     /tmp/ho-build/dist/handover-X.Y.Z.tar.gz \
     --title "vX.Y.Z" --notes-file /tmp/notes.md
   ```

6. **Execute every install line in the README on a clean machine before the release is announced.** A README install command is a claim; if it was not run, it is a lie.
7. Record the artifact sizes and sha256 in the release notes.
