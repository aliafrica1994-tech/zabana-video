"""Builds the Zabana video: AI images + TTS narration + ffmpeg (zoom, B&W film look)."""
import asyncio
import json
import pathlib
import subprocess
import sys
import time
import urllib.parse

import edge_tts
import requests

ROOT = pathlib.Path(__file__).parent
OUT = ROOT / "out"
TMP = OUT / "tmp"
TMP.mkdir(parents=True, exist_ok=True)
CFG = json.loads((ROOT / "story.json").read_text(encoding="utf-8"))
W, H, FPS = 1080, 1920, 30
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def run(cmd):
    subprocess.run(cmd, check=True)


def duration(path):
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True)
    return float(r.stdout.strip())


def make_image(i, prompt):
    path = TMP / f"img{i}.jpg"
    url = "https://image.pollinations.ai/prompt/" + urllib.parse.quote(
        CFG["style"] + ". " + prompt)
    params = {"width": 720, "height": 1280, "seed": CFG["seed"],
              "model": "flux", "nologo": "true"}
    for attempt in range(4):
        try:
            r = requests.get(url, params=params, timeout=180)
            if r.ok and r.headers.get("content-type", "").startswith("image"):
                path.write_bytes(r.content)
                return path
        except requests.RequestException:
            pass
        time.sleep(10 * (attempt + 1))
    sys.exit(f"Image generation failed for clip {i}")


async def tts(text, path):
    await edge_tts.Communicate(text, CFG["voice"], rate=CFG.get("rate", "-8%")).save(str(path))


def make_clip(i, clip):
    img = make_image(i, clip["image_prompt"])
    voice = TMP / f"voice{i}.mp3"
    asyncio.run(tts(clip["narration"], voice))
    dur = max(duration(voice) + 1.2, CFG["min_clip_seconds"])
    frames = int(dur * FPS)
    vf = (
        "scale=1620:2880,"
        f"zoompan=z='min(zoom+0.0006,1.15)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
        f":d={frames}:s={W}x{H}:fps={FPS},"
        "hue=s=0,noise=alls=18:allf=t,vignette=PI/4"
    )
    if clip.get("caption"):
        cap = clip["caption"].replace("'", "")
        vf += (f",drawtext=fontfile={FONT}:text='{cap}':fontcolor=white:fontsize=64:"
               f"borderw=4:bordercolor=black:x=(w-text_w)/2:y=h*0.78:"
               f"enable='between(t,1,{dur - 0.5:.2f})'")
    vf += ",format=yuv420p"
    out = TMP / f"clip{i}.mp4"
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(img), "-i", str(voice),
         "-vf", vf, "-af", "adelay=500|500,apad", "-t", f"{dur:.2f}", "-r", str(FPS),
         "-c:v", "libx264", "-preset", "medium", "-crf", "20",
         "-c:a", "aac", "-ar", "44100", "-ac", "2", str(out)])
    print(f"clip {i}: {dur:.1f}s", flush=True)
    return out


def main():
    clips = [make_clip(i, c) for i, c in enumerate(CFG["clips"], 1)]
    listing = TMP / "list.txt"
    listing.write_text("".join(f"file '{c.name}'\n" for c in clips))
    raw = OUT / "raw.mp4"
    run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
         "-i", str(listing), "-c", "copy", str(raw)])

    final = OUT / "zabana.mp4"
    music = ROOT / "assets" / "music.mp3"
    if music.exists():  # optional background music, mixed quietly
        run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(raw),
             "-stream_loop", "-1", "-i", str(music), "-filter_complex",
             "[1:a]volume=0.12[m];[0:a][m]amix=inputs=2:duration=first:normalize=0[a]",
             "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", str(final)])
    else:
        raw.replace(final)
    print(f"Done: {final} ({duration(final):.1f}s)")


if __name__ == "__main__":
    main()
