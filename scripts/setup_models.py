"""Provision the local inference stack for the Phase 0 demo + Phase 1 vectors.

Downloads (all resumable; safe to re-run):

  1. llama.cpp prebuilt server (Windows CUDA or macOS arm64) -> bin/llamacpp/
  2. Qwen2.5-7B-Instruct Q4_K_M GGUF (the navigator SLM) -> models/
  3. bge-m3 GGUF (the embedder for the canopy layer) -> models/

Run it from a terminal with network access (this is the only step that
needs the internet):

    python scripts/setup_models.py            # everything
    python scripts/setup_models.py --only llm # just the chat model
    python scripts/setup_models.py --only emb # just the embedder
    python scripts/setup_models.py --only bin # just the llama.cpp binary

Nothing here touches the GPU; serving happens in scripts/serve_llm.py.
Everything lands under models/ and bin/ which are git-ignored.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODELS = ROOT / "models"
BIN = ROOT / "bin" / "llamacpp"

# Pinned defaults (override with --llm-repo/--llm-file etc. if you want bigger).
LLM_REPO = "bartowski/Qwen2.5-7B-Instruct-GGUF"
LLM_FILE = "Qwen2.5-7B-Instruct-Q4_K_M.gguf"          # ~4.7 GB
EMB_REPO = "gpustack/bge-m3-GGUF"
EMB_FILE = "bge-m3-Q8_0.gguf"                           # ~610 MB, full quality

LLAMA_RELEASES_API = "https://api.github.com/repos/ggml-org/llama.cpp/releases/latest"


def _hf_download(repo: str, filename: str) -> Path:
    from huggingface_hub import hf_hub_download

    print(f"  → {repo}/{filename}")
    path = hf_hub_download(
        repo_id=repo,
        filename=filename,
        local_dir=str(MODELS),
        # resume + dedup handled by the hub cache; local_dir gives a flat copy
    )
    print(f"    saved: {path}")
    return Path(path)


def _http_json(url: str) -> dict:
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    req = urllib.request.Request(url, headers={"User-Agent": "monkeyllm-setup"})
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=60) as r:  # noqa: S310
        return json.loads(r.read().decode())


def _download(url: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"  → {url}")

    def _hook(block, bsize, total):
        if total > 0:
            pct = min(100, block * bsize * 100 // total)
            sys.stdout.write(f"\r    {pct:3d}%")
            sys.stdout.flush()

    urllib.request.urlretrieve(url, dest, _hook)  # noqa: S310
    print()
    return dest


def _bin_asset_patterns() -> tuple[str, str | None, str]:
    """(main-asset regex, companion-asset regex, human label) per platform."""
    machine = platform.machine().lower()
    arm = machine in ("arm64", "aarch64")
    if sys.platform == "darwin":
        arch = "arm64" if arm else "x64"
        return (rf"^llama-.*bin-macos-{arch}\.(zip|tar\.gz)$", None,
                f"macOS {arch}" + ("/Metal" if arm else ""))
    if sys.platform.startswith("linux"):
        arch = "arm64" if arm else "x64"
        # plain CPU build: universal. CUDA users on Linux typically build or
        # install llama.cpp themselves — serve_llm.py also accepts it on PATH.
        return (rf"^llama-.*bin-ubuntu-{arch}\.(zip|tar\.gz)$", None,
                f"Linux {arch} (CPU build; for CUDA install llama.cpp yourself)")
    # Windows: main bin (CUDA) + the matching CUDA runtime.
    # NB: the cudart asset also contains "bin-win-cuda...x64.zip", so the main
    # binary must be matched by its "llama-" prefix. Prefer CUDA 12.x (Ampere).
    return (r"^llama-.*bin-win-cuda-.*x64\.zip$",
            r"^cudart-.*win-cuda-.*x64\.zip$", "Windows CUDA")


def setup_bin() -> None:
    main_pat, extra_pat, label = _bin_asset_patterns()
    print(f"[1/3] llama.cpp server ({label} prebuilt)")
    BIN.mkdir(parents=True, exist_ok=True)
    if (BIN / "llama-server.exe").exists() or list(BIN.rglob("llama-server")):
        print("  already present, skipping (delete bin/ to force re-download)")
        return
    rel = _http_json(LLAMA_RELEASES_API)
    tag = rel["tag_name"]
    assets = {a["name"]: a["browser_download_url"] for a in rel["assets"]}

    def pick(pattern: str) -> str | None:
        hits = sorted(n for n in assets if re.search(pattern, n))
        return hits[0] if hits else None  # 12.4 sorts before 13.3

    main = pick(main_pat)
    extra = pick(extra_pat) if extra_pat else None
    if not main:
        print(f"  !! no matching asset in release {tag}. Assets:\n   " +
              "\n   ".join(sorted(assets)))
        print("  Pick one manually from https://github.com/ggml-org/llama.cpp/releases")
        sys.exit(1)
    print(f"  release {tag}")
    for name in filter(None, (main, extra)):
        arc_path = BIN / name
        _download(assets[name], arc_path)
        if name.endswith(".tar.gz"):
            with tarfile.open(arc_path) as t:
                t.extractall(BIN)  # noqa: S202 — official release archive
        else:
            with zipfile.ZipFile(arc_path) as z:
                z.extractall(BIN)
        arc_path.unlink()
    print(f"  extracted to {BIN}")
    if sys.platform != "win32":
        # zipfile drops the exec bit; restore it on every extracted binary
        for f in BIN.rglob("*"):
            if f.is_file() and not f.suffix:
                f.chmod(f.stat().st_mode | 0o755)
    server = list(BIN.rglob("llama-server.exe")) or list(BIN.rglob("llama-server"))
    if server:
        print(f"  note: llama-server at {server[0].relative_to(ROOT)}")


def setup_llm(repo: str, file: str) -> None:
    print("[2/3] navigator SLM (chat)")
    MODELS.mkdir(parents=True, exist_ok=True)
    _hf_download(repo, file)


def setup_emb(repo: str, file: str) -> None:
    print("[3/3] embedder (canopy / bge-m3)")
    MODELS.mkdir(parents=True, exist_ok=True)
    _hf_download(repo, file)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", choices=["bin", "llm", "emb"], help="download just one component")
    ap.add_argument("--llm-repo", default=LLM_REPO)
    ap.add_argument("--llm-file", default=LLM_FILE)
    ap.add_argument("--emb-repo", default=EMB_REPO)
    ap.add_argument("--emb-file", default=EMB_FILE)
    args = ap.parse_args()

    do = args.only
    if do in (None, "bin"):
        setup_bin()
    if do in (None, "llm"):
        setup_llm(args.llm_repo, args.llm_file)
    if do in (None, "emb"):
        setup_emb(args.emb_repo, args.emb_file)

    print("\n✓ done. Next:")
    print("    python scripts/serve_llm.py            # start both servers")
    print("    python examples/demo/run_demo.py                # run the 10-question demo")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
