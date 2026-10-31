"""Run the browser-customer demo end to end and keep everything it produced. Demo only, not evidence.

    python browser-demo/run_demo.py [--port-base 27800] [--out browser-demo/out/<name>]

1. Records `python run.py hash --json` (the frozen hashes) before anything runs.
2. Starts server.py (the customer's app) and journey.cjs (Chromium, filmed beside the terminal).
3. Runs `python run.py demo` with the keyless replay of the frozen agent, logging its terminal.
4. Copies the bank copy's folder, records the hashes again, converts the video to MP4, cuts the
   highlight clip (cut.py) and writes the visual report (report.py).

It never sets a model key: the agent's answers come from replays/demo-frozen.jsonl.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
REPLAY = "replay:replays/demo-frozen.jsonl"
CONTAINER_PLAYWRIGHT = "/opt/node-tools/node_modules/playwright"   # preinstalled in the project's cloud container


def git(*argv):
    try:
        return subprocess.run(["git", *argv], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def playwright_module():
    """Playwright for node: $PLAYWRIGHT_NODE_MODULE, else a copy installed in this folder, else the cloud
    container's. None leaves it to node's own lookup of require("playwright")."""
    for path in (os.environ.get("PLAYWRIGHT_NODE_MODULE"), os.path.join(HERE, "node_modules", "playwright"),
                 CONTAINER_PLAYWRIGHT):
        if path and os.path.isdir(path):
            return path
    return None


def hashes():
    out = subprocess.run([sys.executable, "run.py", "hash", "--json"], cwd=ROOT, capture_output=True, text=True)
    return json.loads(out.stdout)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port-base", type=int, default=27800)
    parser.add_argument("--out", default=None)
    parser.add_argument("--model", default=REPLAY)
    args = parser.parse_args()
    out = os.path.abspath(args.out or os.path.join(HERE, "out", time.strftime("%Y%m%d-%H%M%S")))
    os.makedirs(out, exist_ok=True)
    env = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "IC_RECORD")}
    env.update(PYTHONUNBUFFERED="1", COLUMNS="400")
    env.pop("PLAYWRIGHT_NODE_MODULE", None)
    module = playwright_module()
    if module:
        env["PLAYWRIGHT_NODE_MODULE"] = module

    meta = {"label": "demo, not evidence", "port_base": args.port_base, "model": args.model,
            "commit": git("rev-parse", "HEAD"), "describe": git("describe", "--tags", "--always", "--dirty"),
            "hashes_before": hashes(), "t_run_start": time.time()}
    subprocess.run([sys.executable, "run.py", "down", "--port-base", str(args.port_base)], cwd=ROOT, env=env,
                   capture_output=True)

    terminal_log = os.path.join(out, "terminal.log")
    open(terminal_log, "w").close()
    server = subprocess.Popen([sys.executable, os.path.join(HERE, "server.py"), "--port-base", str(args.port_base),
                               "--terminal-log", terminal_log], cwd=ROOT, env=env)
    url = f"http://127.0.0.1:{args.port_base + 30}"
    time.sleep(1.0)
    journey = subprocess.Popen(["node", os.path.join(HERE, "journey.cjs"), "--url", url, "--terminal-log", terminal_log,
                                "--out", out], cwd=ROOT, env=env)
    time.sleep(4.0)   # the stage page is open and filming before the demo prints its first line

    command = [sys.executable, "run.py", "demo", "--port-base", str(args.port_base), "--model", args.model]
    meta["command"] = "python " + " ".join(command[1:])
    demo = subprocess.Popen(command, cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

    def tee():
        with open(terminal_log, "a", encoding="utf-8") as log, \
                open(os.path.join(out, "terminal.jsonl"), "w", encoding="utf-8") as stamped:
            log.write(f"$ {meta['command']}\n")
            log.flush()
            for line in demo.stdout:
                log.write(line)
                log.flush()
                stamped.write(json.dumps({"t": time.time(), "line": line.rstrip("\n")}) + "\n")
                sys.stdout.write(line)
    reader = threading.Thread(target=tee)
    reader.start()
    meta["demo_exit"] = demo.wait()
    reader.join()
    meta["journey_exit"] = journey.wait(timeout=180)
    server.terminate()
    server.wait()
    meta["t_run_end"] = time.time()

    data = os.path.join(ROOT, "runs", f"bank-{args.port_base}")
    shutil.copytree(data, os.path.join(out, "run-data"), dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("control.token"))
    meta["hashes_after"] = hashes()
    meta["hashes_match"] = meta["hashes_before"] == meta["hashes_after"]
    with open(os.path.join(out, "run.json"), "w", encoding="utf-8") as handle:
        json.dump(meta, handle, indent=1)

    webm = os.path.join(out, "browser-demo.webm")
    if os.path.exists(webm) and shutil.which("ffmpeg"):
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", webm, "-c:v", "libx264", "-pix_fmt", "yuv420p",
                        "-crf", "20", "-movflags", "+faststart", os.path.join(out, "browser-demo.mp4")])
        subprocess.run([sys.executable, os.path.join(HERE, "cut.py"), out], cwd=ROOT, env=env)
    subprocess.run([sys.executable, os.path.join(HERE, "report.py"), out], cwd=ROOT, env=env)
    print(f"\nhashes {'match' if meta['hashes_match'] else 'DIFFER'}; everything is in {out}")
    return 0 if meta["demo_exit"] == 0 and meta["journey_exit"] == 0 and meta["hashes_match"] else 1


if __name__ == "__main__":
    sys.exit(main())
