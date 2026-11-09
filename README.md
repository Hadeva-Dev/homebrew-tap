# Hadeva-Dev Homebrew tap

Formulae for [Dawnmere](https://dawnmere.app): one local memory shared by Claude Code, Codex and Cursor on a Mac.

```sh
brew install hadeva-dev/tap/dawnmere
dawnmere setup
```

Needs a Mac with Apple silicon and macOS 14 or later. Homebrew installs Node and Python 3.12 alongside it.
The formula installs the same two wheels as each [release](https://github.com/Hadeva-Dev/dawnmere/releases), checked
by sha256, with every Python dependency pinned to a wheel and its hash. It does not run `dawnmere setup` for you.

Homebrew (7.0 and later) loads a third-party tap's formulae only when they are named in full in `install`, `reinstall`
or `upgrade`, until you trust the tap. So update with `brew upgrade hadeva-dev/tap/dawnmere`, or run
`brew trust hadeva-dev/tap` once to let a plain `brew upgrade` and `brew info dawnmere` see it.

To remove it, run `dawnmere uninstall` first (it takes out the app connections and the background service), then
`brew uninstall dawnmere`.

The curl install line on [dawnmere.app](https://dawnmere.app) remains the main way to install; this tap is the
Homebrew route to the same release.

## A new release

```sh
scripts/bump.py 0.1.6        # rewrites Formula/dawnmere.rb: version, URLs, sha256s, the dependency resources
git commit -am "dawnmere 0.1.6" && git push
```

`bump.py` reads the release's `SHA256SUMS`, checks both wheels against it and takes the dependency pins from the
release's `constraints.txt` (or resolves them with `uv pip compile` for a release that has none). CI audits, builds
and tests the formula on macOS 14 and 15.
