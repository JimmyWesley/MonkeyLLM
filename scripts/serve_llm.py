"""Launch the local inference servers on the RTX 3090 (llama.cpp).

Two OpenAI-compatible servers:

  chat        port 8090  -> the navigator SLM (Qwen2.5-7B Q4)
  embeddings  port 8091  -> bge-m3 (the canopy layer)

Both fully offloaded to the GPU (-ngl 99; the 3090's 24 GB fits both with
room to spare). Binaries and GGUFs are the ones fetched by setup_models.py.

    python scripts/serve_llm.py                 # both servers, stay attached
    python scripts/serve_llm.py --only chat     # just the SLM
    python scripts/serve_llm.py --only emb      # just the embedder

Then, in another terminal, point the demo / canopy at them:

    set MONKEYLLM_LLM_ENDPOINT=http://localhost:8090/v1
    set MONKEYLLM_LLM_MODEL=qwen2.5-7b
    set MONKEYLLM_EMBED_ENDPOINT=http://localhost:8091/v1
    set MONKEYLLM_EMBED_MODEL=bge-m3
"""

from __future__ import annotations

import argparse
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "bin" / "llamacpp"
MODELS = ROOT / "models"


def _runs(server: Path) -> bool:
    """Prebuilt binaries can be linked against a newer OS than this one
    (e.g. macOS release builds on macOS 14 die with a Metal dyld error) —
    probe with --version before committing to a candidate."""
    try:
        proc = subprocess.run([str(server), "--version"], capture_output=True, timeout=30)
        return proc.returncode >= 0  # negative = killed by a signal (dyld abort)
    except OSError:
        return False
    except subprocess.TimeoutExpired:
        return True  # slow but alive


def find_server() -> Path:
    hits = list(BIN.rglob("llama-server.exe")) or list(BIN.rglob("llama-server"))
    on_path = shutil.which("llama-server")  # e.g. Homebrew / apt / self-built
    for cand in [*hits[:1], *( [Path(on_path)] if on_path else [] )]:
        if _runs(cand):
            return cand
        print(f"  (skipping {cand}: binary does not run on this OS)")
    sys.exit(f"no working llama-server under {BIN} nor on PATH. "
             "Run: python scripts/setup_models.py --only bin "
             "(or install llama.cpp via your package manager)")


def find_gguf(*needles: str) -> Path:
    for g in sorted(MODELS.glob("*.gguf")):
        name = g.name.lower()
        if all(n.lower() in name for n in needles):
            return g
    sys.exit(f"no GGUF matching {needles} in {MODELS}. Run: python scripts/setup_models.py")


def find_chat_gguf(substring: str | None) -> Path:
    """The chat model: explicit substring match, or the newest non-embedding
    GGUF in models/ (so a freshly downloaded model wins automatically)."""
    if substring:
        return find_gguf(substring)
    cands = [g for g in MODELS.glob("*.gguf") if "bge" not in g.name.lower()]
    if not cands:
        sys.exit(f"no chat GGUF in {MODELS}. Run: python scripts/setup_models.py --only llm")
    return max(cands, key=lambda g: g.stat().st_mtime)


def launch(server: Path, model: Path, *, port: int, alias: str, embedding: bool, ngl: int, ctx: int,
           parallel: int = 1, reasoning: str = "off"):
    cmd = [
        str(server), "-m", str(model),
        "--host", "127.0.0.1", "--port", str(port),
        # llama.cpp splits -c across slots: pass total = ctx-per-slot * slots
        "-ngl", str(ngl), "-c", str(ctx * parallel),
        "--alias", alias,
        # lean & fast: no vision/audio projector, no thinking, flash attention,
        # quantized KV cache (q8_0 halves KV memory)
        "--no-mmproj",
        "-fa", "on",
        "-np", str(parallel),
    ]
    if embedding:
        cmd += ["--embedding", "--pooling", "cls", "-b", str(ctx), "-ub", str(ctx)]
    else:
        cmd += ["--reasoning", reasoning,
                "-ctk", "q8_0", "-ctv", "q8_0"]
    print(f"  $ {' '.join(cmd)}")
    return subprocess.Popen(cmd)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", choices=["chat", "emb"])
    # NB: 8080 is often reserved by Windows' HTTP.sys (System, PID 4) — default
    # to 8090/8091 instead.
    ap.add_argument("--chat-port", type=int, default=8090)
    ap.add_argument("--emb-port", type=int, default=8091)
    ap.add_argument("--ngl", type=int, default=99, help="GPU layers to offload (99 = all)")
    ap.add_argument("--ctx", type=int, default=8192)
    ap.add_argument("--chat-gguf", help="substring to pick the chat GGUF (default: newest in models/)")
    ap.add_argument("--reasoning", choices=["on", "off", "auto"], default="off",
                    help="thinking mode for the chat model (hybrid reasoners like "
                         "MiniCPM5 need 'on'; pair with MONKEYLLM_LLM_REASONING=on)")
    ap.add_argument("--parallel", type=int, default=1,
                    help="chat slots (llama.cpp -np): continuous batching for the "
                         "Troop (N monkeys share the GPU at ~1x wall-clock). "
                         "--ctx is per slot; total KV = ctx * parallel.")
    args = ap.parse_args()

    server = find_server()
    procs: list[subprocess.Popen] = []

    try:
        if args.only in (None, "chat"):
            gguf = find_chat_gguf(args.chat_gguf)
            # alias from the file: "gemma-4-12B-it-Q4_K_M.gguf" -> "gemma-4"
            alias = "-".join(gguf.stem.lower().split("-")[:2])
            print(f"[chat] navigator SLM: {gguf.name} (alias {alias})")
            procs.append(launch(
                server, gguf, port=args.chat_port,
                alias=alias, embedding=False, ngl=args.ngl, ctx=args.ctx,
                parallel=args.parallel, reasoning=args.reasoning,
            ))
        if args.only in (None, "emb"):
            print("[emb] bge-m3 embedder")
            procs.append(launch(
                server, find_gguf("bge-m3"), port=args.emb_port,
                alias="bge-m3", embedding=True, ngl=args.ngl,
                ctx=2048,  # summaries/chunks are short; small ctx = less VRAM
            ))

        print("\nservers starting (model load takes a few seconds)...")
        print(f"  chat  : http://localhost:{args.chat_port}/v1")
        print(f"  embed : http://localhost:{args.emb_port}/v1")
        print("Ctrl+C to stop.\n")

        # wait until any child exits
        while True:
            for p in procs:
                if p.poll() is not None:
                    print(f"server exited with code {p.returncode}")
                    return p.returncode or 0
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nstopping...")
    finally:
        for p in procs:
            if p.poll() is None:
                p.send_signal(signal.SIGTERM)
        for p in procs:
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
