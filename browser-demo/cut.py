"""Cut a 25-35 s highlight clip from one browser-demo recording, for the 3-minute project video.

    python browser-demo/cut.py <run folder>

Keeps five moments, in order, using the times journey.cjs logged: the warm-up payment, the refusal
when the faults land, the retry that is paid and the retry answered "already paid", the handover,
and the checker's verdict. The stage clock in the top right keeps running real time, so every
cut stays visible. Writes browser-demo-cut.mp4 and cut.json (the source time ranges) beside the run.
"""

import json
import os
import subprocess
import sys


def main():
    run_dir = os.path.abspath(sys.argv[1])
    events = [json.loads(line) for line in open(os.path.join(run_dir, "journey.jsonl"), encoding="utf-8")]

    def at(event, **match):
        for ev in events:
            if ev["event"] == event and all(ev.get(k) == v for k, v in match.items()):
                return ev["video_s"]
        return None

    def after(t0, event):
        return next((ev["video_s"] for ev in events if ev["event"] == event and ev["video_s"] > t0), None)

    warm = at("caption", step="1 ·")
    fault = at("faults_injected")
    refused = after(fault, "result") if fault else None
    first_ok_retry = next((ev["video_s"] for ev in events if ev["event"] == "result" and ev.get("outcome") == "ok"
                           and fault and ev["video_s"] > fault), None)
    retry_click = max((ev["video_s"] for ev in events if ev["event"] == "click" and first_ok_retry
                       and ev["video_s"] < first_ok_retry), default=None)
    replay = at("screenshot", file="shots/04-replayed.png") or at("screenshot", file="shots/03-retry-paid.png")
    handover = at("handover")
    checker = at("checker")
    end = at("done") or checker + 8
    wanted = [("warm-up payment", warm, warm and warm + 3.2),
              ("faults land, payment refused", fault and fault - 0.3, refused and refused + 2.6),
              ("retry paid, retry again: already paid", retry_click and retry_click - 0.8, replay and replay + 2.4),
              ("hand over", handover and handover - 0.4, handover and handover + 5.0),
              ("checker verdict", checker and checker - 0.6, checker and min(checker + 6.0, end))]
    segments = [(name, round(a, 2), round(b, 2)) for name, a, b in wanted if a is not None and b is not None and b > a]
    parts, labels = [], []
    for i, (_, a, b) in enumerate(segments):
        parts.append(f"[0:v]trim=start={a}:end={b},setpts=PTS-STARTPTS[v{i}]")
        labels.append(f"[v{i}]")
    graph = ";".join(parts) + ";" + "".join(labels) + f"concat=n={len(segments)}:v=1:a=0[out]"
    out = os.path.join(run_dir, "browser-demo-cut.mp4")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", os.path.join(run_dir, "browser-demo.webm"),
                    "-filter_complex", graph, "-map", "[out]", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18",
                    "-r", "25", "-movflags", "+faststart", out], check=True)
    total = sum(b - a for _, a, b in segments)
    with open(os.path.join(run_dir, "cut.json"), "w", encoding="utf-8") as handle:
        json.dump({"segments": [{"what": n, "from_s": a, "to_s": b} for n, a, b in segments],
                   "length_s": round(total, 1)}, handle, indent=1)
    print(f"cut: {out} ({total:.1f} s, {len(segments)} moments)")


if __name__ == "__main__":
    main()
