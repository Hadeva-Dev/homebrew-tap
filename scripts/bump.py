#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["packaging>=24"]
# ///
"""Rewrite Formula/dawnmere.rb for one Dawnmere release.

    scripts/bump.py 0.1.6          # or v0.1.6

Reads the release's SHA256SUMS, downloads the two wheels it ships (lflabs_memory_cli, lflabs_memory_engine) and checks
them against it. The Python dependencies come from the release's constraints.txt (0.1.6 and later: every dependency
pinned with its hashes); a release without one is resolved here with the same `uv pip compile` RELEASING.md uses
(macOS 14+, arm64, Python 3.12). Each dependency becomes a resource: the wheel for macOS 14 arm64 / CPython 3.12 whose
sha256 is in the pin, from PyPI. Needs uv on PATH (only for releases without constraints.txt).
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from packaging.tags import compatible_tags, cpython_tags, mac_platforms
from packaging.utils import canonicalize_name, parse_wheel_filename

REPO = "LF-Labs-Inc/dawnmere"
PY = (3, 12)          # the Python the release targets (install.sh: --python 3.12); keep in step with the formula
MACOS = (14, 0)
FORMULA = Path(__file__).resolve().parent.parent / "Formula" / "dawnmere.rb"

PLATFORMS = list(mac_platforms(MACOS, "arm64"))
TAGS = list(cpython_tags(PY, platforms=PLATFORMS)) + list(compatible_tags(PY, platforms=PLATFORMS))
RANK = {t: i for i, t in enumerate(TAGS)}


def get(url, tries=6, headers=None):
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers or {}), timeout=60) as r:
                return r.read()
        except (urllib.error.URLError, TimeoutError) as e:
            if i == tries - 1 or getattr(e, "code", 500) < 500:
                sys.exit(f"{url}: {e}")
            time.sleep(2 ** i)


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def parse_pins(text):
    """{name: (version, {sha256, ...})} from a `uv pip compile --generate-hashes` file."""
    pins = {}
    for block in re.sub(r"\\\n", " ", text).splitlines():
        block = block.split("#", 1)[0].strip()
        if not block:
            continue
        m = re.match(r"([A-Za-z0-9_.\-\[\]]+)==(\S+)", block)
        if not m:
            sys.exit(f"cannot read pin: {block}")
        name = canonicalize_name(m.group(1).split("[")[0])
        pins[name] = (m.group(2).split(";")[0], set(re.findall(r"--hash=sha256:([0-9a-f]{64})", block)))
    return pins


def best_file(name, version, hashes):
    """(url, sha256) of the most specific wheel this Mac can use whose hash is pinned."""
    files = json.loads(get(f"https://pypi.org/pypi/{name}/{version}/json"))["urls"]
    best = None
    for f in files:
        if f["packagetype"] != "bdist_wheel" or f["digests"]["sha256"] not in hashes:
            continue
        ranks = [RANK[t] for t in parse_wheel_filename(f["filename"])[3] if t in RANK]
        if ranks and (best is None or min(ranks) < best[0]):
            best = (min(ranks), f["url"], f["digests"]["sha256"])
    if not best:
        sys.exit(f"{name}=={version}: no pinned wheel for macOS {MACOS[0]} arm64, CPython {PY[0]}.{PY[1]}")
    return best[1], best[2]


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    version = sys.argv[1].lstrip("v")
    base = f"https://github.com/{REPO}/releases/download/v{version}"
    # Assets are read through the API: github.com/.../releases/download/ answered 504 for minutes at a time (Nov 2026)
    api = {"Accept": "application/octet-stream"}
    if os.environ.get("GITHUB_TOKEN"):
        api["Authorization"] = f"Bearer {os.environ['GITHUB_TOKEN']}"
    release = json.loads(get(f"https://api.github.com/repos/{REPO}/releases/tags/v{version}",
                             headers={k: v for k, v in api.items() if k != "Accept"}))
    assets = {a["name"]: a["url"] for a in release["assets"]}

    def asset(name):
        if name not in assets:
            sys.exit(f"v{version} has no asset {name}")
        return get(assets[name], headers=api)

    sums = {}
    for line in asset("SHA256SUMS").decode().splitlines():
        digest, name = line.split()
        sums[name.lstrip("*")] = digest

    def wheel(prefix):
        names = [n for n in sums if n.startswith(prefix) and n.endswith(".whl")]
        if len(names) != 1:
            sys.exit(f"SHA256SUMS lists {len(names)} {prefix} wheels")
        return names[0]

    cli, engine = wheel("lflabs_memory_cli-"), wheel("lflabs_memory_engine-")
    if parse_wheel_filename(cli)[1].public != version:
        sys.exit(f"{cli} is not version {version}")

    with tempfile.TemporaryDirectory() as d:
        for name in (cli, engine):
            data = asset(name)
            if sha256(data) != sums[name]:
                sys.exit(f"{name} does not match SHA256SUMS")
            (Path(d) / name).write_bytes(data)
        if "constraints.txt" in sums:
            data = asset("constraints.txt")
            if sha256(data) != sums["constraints.txt"]:
                sys.exit("constraints.txt does not match SHA256SUMS")
            pins_text, source = data.decode(), "the release's constraints.txt"
        else:
            out = Path(d) / "constraints.txt"
            subprocess.run(
                ["uv", "pip", "compile", "-", "--generate-hashes", "--python-version", f"{PY[0]}.{PY[1]}",
                 "--python-platform", "aarch64-apple-darwin", "--no-header", "--quiet",
                 "--no-emit-package", "lflabs-memory-cli", "--no-emit-package", "lflabs-memory-engine", "-o", str(out)],
                input=f"{Path(d) / cli}\n{Path(d) / engine}\n", text=True, check=True,
                env={"MACOSX_DEPLOYMENT_TARGET": f"{MACOS[0]}.{MACOS[1]}", **os.environ})
            pins_text, source = out.read_text(), "uv pip compile (this release has no constraints.txt)"

    pins = parse_pins(pins_text)
    resources = [("lflabs-memory-engine", f"{base}/{engine}", sums[engine])]
    for name in sorted(pins):
        v, hashes = pins[name]
        resources.append((name, *best_file(name, v, hashes)))
        print(f"  {name}=={v}", file=sys.stderr)

    text = FORMULA.read_text()
    head, sep, rest = text.partition("  resource ")
    if not sep:
        sys.exit("Formula/dawnmere.rb has no resource blocks to replace")
    tail = rest[rest.index("\n  def install"):]
    head = re.sub(r'^  url ".*?"', f'  url "{base}/{cli}"', head, count=1, flags=re.M)
    head = re.sub(r'^  sha256 "[0-9a-f]{64}"', f'  sha256 "{sums[cli]}"', head, count=1, flags=re.M)
    blocks = "".join(f'  resource "{n}" do\n    url "{u}", using: :nounzip\n    sha256 "{s}"\n  end\n\n'
                     for n, u, s in resources)
    head = re.sub(r'(?m)^  url "(.*?)"$', r'  url "\1", using: :nounzip', head, count=1)
    FORMULA.write_text(head + blocks.rstrip("\n") + "\n" + tail)
    print(f"Formula/dawnmere.rb: {version}, {cli}, {len(resources)} resources ({source})", file=sys.stderr)


if __name__ == "__main__":
    main()
