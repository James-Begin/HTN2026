"""Turn a desktop screen recording into the short, captioned README demo.

Requires ffmpeg on PATH. The source recording is deliberately kept out of git;
run: python3 scripts/edit_demo_video.py recording.mov docs/assets/
"""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path


def text(font: Path, value: str, size: int, y: str, color: str = "white") -> str:
    return (
        f"drawtext=fontfile={font}:text='{value}':fontsize={size}:"
        f"fontcolor={color}:x=(w-text_w)/2:y={y}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("recording", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--font", type=Path, default=Path("/System/Library/Fonts/Supplemental/Arial.ttf"))
    args = parser.parse_args()
    if not args.font.is_file():
        parser.error(f"Font not found: {args.font} (pass --font with a TrueType font path)")
    args.output_dir.mkdir(parents=True, exist_ok=True)

    # The opening is real-time so the floating cards are readable. Later
    # graph-building footage is progressively compressed to keep the edit
    # under a minute without losing its live, accumulating character.
    common = "fps=30,scale=1920:984:flags=lanczos,pad=1920:1080:0:48:black,eq=gamma=1.18:saturation=1.15"
    caption = "drawtext=fontfile=" + str(args.font) + ":fontsize=24:fontcolor=0xaed9ef:x=52:y=1020"
    filters = [
        "color=c=0x02060b:s=1920x1080:r=30:d=2.5,"
        + text(args.font, "sequitor.", 126, "(h-text_h)/2-70")
        + ","
        + text(args.font, "FOLLOW THE CONVERSATION", 27, "(h-text_h)/2+95", "0x8bd5ed")
        + ",fade=t=in:st=0:d=0.5,fade=t=out:st=2.15:d=0.35[intro]",
        f"[0:v]trim=start=0:end=15,setpts=PTS-STARTPTS,{common},"
        f"{caption}:text='01   START WITH A POST'[first]",
        f"[0:v]trim=start=15:end=35,setpts=(PTS-STARTPTS)/1.3,{common},"
        f"{caption}:text='02   WATCH THE CONVERSATION TAKE SHAPE'[second]",
        f"[0:v]trim=start=35:end=61.1,setpts=(PTS-STARTPTS)/1.8,{common},"
        f"{caption}:text='03   EXPLORE THE LINEAGE',fade=t=out:st=13.7:d=0.8[third]",
        "color=c=0x02060b:s=1920x1080:r=30:d=3,"
        + text(args.font, "Find the thread behind the post.", 64, "(h-text_h)/2-50")
        + ","
        + text(args.font, "sequitor.", 38, "(h-text_h)/2+65", "0x8bd5ed")
        + ",fade=t=in:st=0:d=0.45,fade=t=out:st=2.6:d=0.4[outro]",
        "[intro][first][second][third][outro]concat=n=5:v=1:a=0[v]",
    ]
    video = args.output_dir / "sequitor-demo.mp4"
    subprocess.run(
        [
            args.ffmpeg, "-hide_banner", "-y", "-i", str(args.recording),
            "-filter_complex", ";".join(filters), "-map", "[v]",
            "-c:v", "libx264", "-preset", "medium", "-crf", "23",
            "-map_metadata", "-1", "-metadata", "title=Sequitor demo",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(video),
        ],
        check=True,
    )
    poster = args.output_dir / "sequitor-poster.jpg"
    subprocess.run(
        [
            args.ffmpeg, "-hide_banner", "-y", "-ss", "47", "-i", str(args.recording),
            "-frames:v", "1", "-vf",
            "scale=1280:656:flags=lanczos,pad=1280:720:0:32:black,"
            "eq=gamma=1.25:saturation=1.2,"
            f"{text(args.font, 'sequitor.', 34, '8')},"
            f"{text(args.font, 'Follow the conversation.', 25, '680', '0xaed9ef')}",
            "-q:v", "3", str(poster),
        ],
        check=True,
    )
    print(video)
    print(poster)


if __name__ == "__main__":
    main()
