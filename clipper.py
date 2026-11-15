import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
LANG_NAMES = {"hi": "Hindi", "en": "English", "pa": "Punjabi (Gurmukhi script)", "ur": "Urdu"}
HIGHLIGHTS = {  # ASS colour format: &HBBGGRR&
    "Yellow": "&H00FFFF&", "Green": "&H00FF00&", "Red": "&H4B2BFF&",
    "Cyan": "&HFFFF00&", "Orange": "&H008CFF&", "White": "&HFFFFFF&",
}
CAPTION_SIZES = {"Small": 64, "Medium": 80, "Large": 96}


def _noop(pct, msg=""):
    pass


def _clean(msg):
    """Error message se rang ke ajeeb characters hatao."""
    return re.sub(r"\x1b\[[0-9;]*m|\[[0-9;]*m", "", str(msg)).replace("\ufffd", "").strip()


def safe_name(text):
    return re.sub(r'[\\/:*?"<>|\r\n]+', "", str(text)).strip()[:60] or "video"


# ---------- Folder helpers ----------
def pick_folder(initial=None):
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        p = filedialog.askdirectory(initialdir=initial or str(Path.home()),
                                    title="Clips save karne ka folder chuno")
        root.destroy()
        return p or None
    except Exception:
        return None


def open_folder(path):
    try:
        Path(path).mkdir(parents=True, exist_ok=True)
        if sys.platform.startswith("win"):
            os.startfile(str(path))  # noqa
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
    except Exception:
        pass


# ---------- 1. Download ----------
def download_video(url, out_dir, cookies_browser=None, progress=_noop):
    import yt_dlp
    out_dir = Path(out_dir)
    attempts = [
        {"format": "bv*[height<=1080][vcodec^=avc1]+ba[ext=m4a]/bv*[height<=1080]+ba/b[height<=1080]/b",
         "merge_output_format": "mkv"},
        {"format": "b[height<=720]/b"},
        {"format": "worst"},
    ]
    seen = {}

    def hook(d):
        if d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            if total:
                seen[d.get("filename")] = d.get("downloaded_bytes", 0) / total
                frac = sum(seen.values()) / max(2, len(seen))
                progress(2 + 18 * min(frac, 1), f"Video download ho rahi hai... {int(min(frac, 1) * 100)}%")
        elif d.get("status") == "finished":
            progress(20, "Download complete")

    last_err = None
    for extra in attempts:
        seen.clear()
        for old in out_dir.glob("source.*"):
            try:
                old.unlink()
            except OSError:
                pass
        opts = {
            "outtmpl": str(out_dir / "source.%(ext)s"), "noplaylist": True,
            "quiet": True, "no_warnings": True, "retries": 5, "fragment_retries": 5,
            "concurrent_fragment_downloads": 4, "progress_hooks": [hook], **extra,
        }
        if cookies_browser:
            opts["cookiesfrombrowser"] = (cookies_browser,)
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
            files = [p for p in out_dir.glob("source.*") if p.suffix not in (".part", ".ytdl")]
            if files:
                files.sort(key=lambda p: p.stat().st_size, reverse=True)
                return files[0], info.get("title", "video")
        except Exception as e:
            last_err = e
            low = str(e).lower()
            if "confirm your age" in low or "sign in" in low:
                raise RuntimeError(
                    "Ye video age-restricted hai (YouTube login mangta hai). Ya to koi aam video use karo, "
                    "ya sidebar mein 'Browser login' chuno (us browser mein YouTube par login hona chahiye).")
            if "cookie" in low or "dpapi" in low or "could not copy" in low:
                raise RuntimeError("Browser ki cookies nahi padh saka. Browser band karke dobara try karo, "
                                   "ya Firefox / Edge chuno. Detail: " + _clean(e))
    raise RuntimeError("Video download nahi ho saki. Link check karo (live stream ho to khatam ho chuki ho). "
                       "Detail: " + _clean(last_err))


# ---------- 2. Transcribe ----------
def transcribe(video_path, model_size="small", device="cpu", language=None, progress=_noop, models_dir=None):
    from faster_whisper import WhisperModel
    progress(21, "AI model load ho raha hai (pehli baar download hoga)...")
    compute = "int8" if device == "cpu" else "float16"
    if models_dir:
        Path(models_dir).mkdir(parents=True, exist_ok=True)
    model = WhisperModel(model_size, device=device, compute_type=compute,
                         download_root=str(models_dir) if models_dir else None)
    seg_iter, info = model.transcribe(str(video_path), language=language,
                                      word_timestamps=True, vad_filter=True)
    total = info.duration or 1
    result = []
    for s in seg_iter:
        words = [{"w": w.word.strip(), "start": w.start, "end": w.end}
                 for w in (s.words or []) if w.word.strip()]
        result.append({"start": s.start, "end": s.end, "text": s.text.strip(), "words": words})
        frac = min(s.end / total, 1)
        progress(22 + 36 * frac, f"Awaaz text ban rahi hai... {int(frac * 100)}%")
    return result, info.language


# ---------- 3. Best clips chunna ----------
def _snap(segments, start, end, min_d, max_d):
    starts = [s["start"] for s in segments]
    ends = [s["end"] for s in segments]
    start = min(starts, key=lambda x: abs(x - start))
    end = min(ends, key=lambda x: abs(x - end))
    if end - start > max_d:
        valid = [e for e in ends if min_d <= e - start <= max_d]
        end = valid[-1] if valid else start + max_d
    if end - start < min_d:
        end = start + min_d
    return round(start, 2), round(end, 2)


def pick_clips_ai(segments, api_key, model, n_clips, min_d, max_d):
    import anthropic
    transcript = "\n".join(f"[{s['start']:.1f}-{s['end']:.1f}] {s['text']}" for s in segments)[:150000]
    prompt = f"""Neeche ek video ka transcript timestamps ke saath hai.
Isme se {n_clips} sabse acche, viral hone wale clips chuno jo Instagram Reels / YouTube Shorts ke liye hon.
Rules:
- Har clip {min_d} se {max_d} seconds ka ho.
- Clip ka start ek mazboot hook se ho (sawal, hairan karne wali baat, bold claim).
- Clip apne aap mein mukammal ho (beech mein na shuru ho na beech mein khatam).
- Clips ek dosre se overlap na karein.
- Start/end transcript ke timestamps ke mutabiq hon.
- Title chhota ho aur transcript ki language mein ho.
Sirf JSON array do, aur kuch nahi. Format:
[{{"start": 12.5, "end": 58.0, "title": "chota title", "score": 92, "reason": "ek line mein wajah"}}]

Transcript:
{transcript}"""
    client = anthropic.Anthropic(api_key=api_key)
    resp = client.messages.create(model=model, max_tokens=2000,
                                  messages=[{"role": "user", "content": prompt}])
    text = "".join(b.text for b in resp.content if b.type == "text")
    items = json.loads(re.search(r"\[.*\]", text, re.S).group(0))
    clips = []
    for it in items:
        s, e = _snap(segments, float(it["start"]), float(it["end"]), min_d, max_d)
        clips.append({"start": s, "end": e, "title": it.get("title", "Clip"),
                      "score": it.get("score", 0), "reason": it.get("reason", "")})
    return clips


HOOK_WORDS = ["secret", "never", "mistake", "why", "how", "best", "worst", "money", "free", "truth",
              "shocking", "amazing", "biggest", "important", "kabhi", "raaz", "sach", "paisa", "galti", "sabse"]


def pick_clips_heuristic(segments, n_clips, min_d, max_d):
    candidates = []
    for i, seg in enumerate(segments):
        start = seg["start"]
        j = i
        while j < len(segments) and segments[j]["end"] - start <= max_d:
            j += 1
        j -= 1
        if j < i or segments[j]["end"] - start < min_d:
            continue
        chunk = segments[i:j + 1]
        text = " ".join(c["text"] for c in chunk).lower()
        dur = chunk[-1]["end"] - start
        score = len(text.split()) / dur
        score += 0.5 * sum(text.count(w) for w in HOOK_WORDS)
        score += 0.3 * (text.count("?") + text.count("!"))
        if "?" in chunk[0]["text"]:
            score += 1.5
        candidates.append({"start": start, "end": chunk[-1]["end"], "title": chunk[0]["text"][:50],
                           "score": round(score * 10), "reason": "Simple scoring (bina AI)"})
    candidates.sort(key=lambda c: c["score"], reverse=True)
    chosen = []
    for c in candidates:
        if all(c["end"] <= x["start"] or c["start"] >= x["end"] for x in chosen):
            chosen.append(c)
        if len(chosen) == n_clips:
            break
    return chosen


# ---------- 4. Translation ----------
def _translate_claude(texts, src, tgt, api_key, model):
    import anthropic
    src_name = LANG_NAMES.get(src, "the original language")
    prompt = (f"Translate each line from {src_name} to {LANG_NAMES[tgt]}. Keep meaning and tone natural, "
              f"suitable for short-video captions. Return ONLY a JSON array of strings with exactly "
              f"{len(texts)} items, in the same order.\n\n{json.dumps(texts, ensure_ascii=False)}")
    client = anthropic.Anthropic(api_key=api_key)
    resp = client.messages.create(model=model, max_tokens=4000,
                                  messages=[{"role": "user", "content": prompt}])
    text = "".join(b.text for b in resp.content if b.type == "text")
    out = json.loads(re.search(r"\[.*\]", text, re.S).group(0))
    if len(out) != len(texts):
        raise ValueError("length mismatch")
    return [str(x) for x in out]


def translate_texts(texts, src, tgt, api_key="", model=""):
    if not texts:
        return []
    if api_key:
        try:
            return _translate_claude(texts, src, tgt, api_key, model)
        except Exception:
            pass  # Google translate par wapas
    try:
        from deep_translator import GoogleTranslator
        tr = GoogleTranslator(source=src or "auto", target=tgt)
        out = tr.translate_batch([t if t.strip() else "." for t in texts])
        return [o or t for o, t in zip(out, texts)]
    except Exception as e:
        raise RuntimeError("Translation nahi ho saki (internet check karo). Detail: " + _clean(e))


def clip_caption_words(segments, clip, src, tgt, api_key="", model=""):
    start, end = clip["start"], clip["end"]
    segs = [s for s in segments if s["end"] > start and s["start"] < end]
    if not tgt or tgt == src:
        return [w for s in segs for w in s["words"] if w["start"] >= start - 0.1 and w["end"] <= end + 0.1]
    translated = translate_texts([s["text"] for s in segs], src, tgt, api_key, model)
    words = []
    for s, t in zip(segs, translated):
        ws = t.split()
        if not ws:
            continue
        a, b = max(s["start"], start), min(s["end"], end)
        step = max(b - a, 0.1) / len(ws)
        for k, w in enumerate(ws):
            words.append({"w": w, "start": a + k * step, "end": a + (k + 1) * step})
    return words


# ---------- 5. Face tracking ----------
def face_center(video_path, start, end, track=True, samples=8):
    import cv2
    cap = cv2.VideoCapture(str(video_path))
    w = cap.get(cv2.CAP_PROP_FRAME_WIDTH)
    h = cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
    fps = cap.get(cv2.CAP_PROP_FPS) or 25
    xs = []
    if track:
        det = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        for k in range(samples):
            t = start + (end - start) * (k + 0.5) / samples
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(t * fps))
            ok, frame = cap.read()
            if not ok:
                continue
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = det.detectMultiScale(gray, 1.2, 5, minSize=(int(h * 0.1), int(h * 0.1)))
            if len(faces):
                x, y, fw, fh = max(faces, key=lambda f: f[2] * f[3])
                xs.append(x + fw / 2)
    cap.release()
    xs.sort()
    return int(w), int(h), (xs[len(xs) // 2] if xs else w / 2)


# ---------- 6. Captions + channel name (ASS) ----------
def _ass_time(t):
    t = max(t, 0)
    return f"{int(t // 3600)}:{int((t % 3600) // 60):02d}:{t % 60:05.2f}"


def make_ass(words, clip_start, clip_end, path, font="Arial", size=80, highlight="&H00FFFF&",
             brand_text="", brand_pos="Top", brand_font="Arial", per_line=3):
    brand_align, brand_margin = (8, 110) if brand_pos == "Top" else (2, 250)
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920

[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: Default,{font},{size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,6,2,2,60,60,520,1
Style: Brand,{brand_font},54,&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,4,2,{brand_align},60,60,{brand_margin},1

[Events]
Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
"""
    ws = [w for w in words if w["start"] >= clip_start - 0.1 and w["end"] <= clip_end + 0.1]
    lines = []
    for i in range(0, len(ws), per_line):
        group = ws[i:i + per_line]
        for k, w in enumerate(group):
            s = w["start"] - clip_start
            e = (group[k + 1]["start"] if k + 1 < len(group) else w["end"]) - clip_start
            parts = []
            for idx, g in enumerate(group):
                txt = g["w"].replace("{", "").replace("}", "")
                if txt.isascii():
                    txt = txt.upper()
                parts.append(f"{{\\c{highlight if idx == k else '&HFFFFFF&'}}}{txt}")
            lines.append(f"Dialogue: 0,{_ass_time(s)},{_ass_time(e)},Default,,0,0,0,,{' '.join(parts)}")
    if brand_text:
        safe = brand_text.replace("{", "").replace("}", "")
        lines.append(f"Dialogue: 1,{_ass_time(0)},{_ass_time(clip_end - clip_start)},Brand,,0,0,0,,{safe}")
    Path(path).write_text(header + "\n".join(lines), encoding="utf-8")


def _prepare_fonts(work_dir):
    """Windows ke fonts (Hindi/Punjabi ke liye Nirmala UI) clip folder mein copy karo."""
    fdir = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    copied = False
    if fdir.exists():
        for pat in ("Nirmala*", "arial.ttf", "arialbd.ttf"):
            for f in fdir.glob(pat):
                try:
                    dst = Path(work_dir) / f.name
                    if not dst.exists():
                        shutil.copy2(f, dst)
                    copied = True
                except OSError:
                    pass
    return copied


# ---------- 7. Render ----------
def render_clip(video_path, clip, words, work_dir, index, s, on_frac=None):
    work_dir = Path(work_dir)
    start, end = clip["start"], clip["end"]
    dur = max(end - start, 0.1)
    try:
        w, h, cx = face_center(video_path, start, end, track=bool(s.get("face_track")))
        cw = int(h * 9 / 16) // 2 * 2
        x = int(min(max(cx - cw / 2, 0), w - cw)) // 2 * 2
        crop = f"crop={cw}:{h}:{x}:0,"
    except Exception:
        crop = "crop=ih*9/16:ih,"
    vf = crop + "scale=1080:1920"

    brand = (s.get("channel_name") or "").strip()
    out_name = f"clip_{index}.mp4"
    if s.get("captions") or brand:
        cap_lang = s.get("cap_lang")
        font = "Nirmala UI" if cap_lang in ("hi", "pa") else "Arial"
        brand_font = "Nirmala UI" if any(ord(ch) > 127 for ch in brand) else "Arial"
        ass_name = f"clip_{index}.ass"
        make_ass(words if s.get("captions") else [], start, end, work_dir / ass_name, font=font,
                 size=CAPTION_SIZES.get(s.get("cap_size"), 80),
                 highlight=HIGHLIGHTS.get(s.get("cap_color"), "&H00FFFF&"),
                 brand_text=brand, brand_pos=s.get("channel_pos", "Top"), brand_font=brand_font)
        vf += f",subtitles={ass_name}" + (":fontsdir=." if _prepare_fonts(work_dir) else "")

    src = str(Path(video_path).resolve())
    enc = ["-c:v", "libx264", "-preset", "fast", "-crf", "20", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "160k"]
    common = ["ffmpeg", "-y", "-loglevel", "error", "-progress", "pipe:1", "-nostats"]
    logo = s.get("logo_path")
    if logo and Path(logo).exists():
        lw = int(1080 * s.get("logo_scale", 16) / 100)
        pos = {"Top-left": "40:90", "Top-right": "W-w-40:90",
               "Bottom-left": "40:H-h-300", "Bottom-right": "W-w-40:H-h-300"}.get(s.get("logo_pos"), "W-w-40:90")
        fc = f"[0:v]{vf}[v];[1:v]scale={lw}:-1[lg];[v][lg]overlay={pos}[out]"
        cmd = common + ["-ss", str(start), "-t", str(round(dur, 2)), "-i", src, "-i", str(Path(logo).resolve()),
                        "-filter_complex", fc, "-map", "[out]", "-map", "0:a?", *enc, out_name]
    else:
        cmd = common + ["-ss", str(start), "-i", src, "-t", str(round(dur, 2)), "-vf", vf, *enc, out_name]

    errlog_path = work_dir / f"ffmpeg_{index}.log"
    with open(errlog_path, "w", encoding="utf-8", errors="ignore") as errlog:
        proc = subprocess.Popen(cmd, cwd=str(work_dir), stdout=subprocess.PIPE, stderr=errlog,
                                text=True, creationflags=CREATE_NO_WINDOW)
        for line in proc.stdout:
            if line.startswith("out_time_ms=") and on_frac:
                try:
                    on_frac(min(int(line.split("=")[1]) / 1_000_000 / dur, 1))
                except ValueError:
                    pass
        proc.wait()
    if proc.returncode != 0:
        tail = errlog_path.read_text(encoding="utf-8", errors="ignore")[-1200:]
        raise RuntimeError("ffmpeg error:\n" + tail)
    return work_dir / out_name


# ---------- 8. Poora pipeline ----------
def run_pipeline(s, progress=_noop):
    work = Path(s["work_dir"])
    work.mkdir(parents=True, exist_ok=True)
    out_dir = Path(s["out_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        progress(1, "Shuru ho raha hai...")
        video, title = download_video(s["url"], work, s.get("cookies_browser"), progress)
        segments, detected = transcribe(video, s["whisper_size"], s["device"], s.get("src_lang"), progress,
                                        s.get("models_dir"))
        if not segments:
            raise RuntimeError("Video mein koi awaaz/speech nahi mili.")
        src = s.get("src_lang") or detected
        tgt = s.get("tgt_lang")
        s["cap_lang"] = tgt or src

        progress(59, "Best moments dhundh rahe hain...")
        api_key = s.get("api_key") or ""
        if api_key:
            clips = pick_clips_ai(segments, api_key, s["ai_model"], s["n_clips"], s["min_d"], s["max_d"])
        else:
            clips = pick_clips_heuristic(segments, s["n_clips"], s["min_d"], s["max_d"])
        if not clips:
            raise RuntimeError("Koi acha clip nahi mila. Clip length badal kar dobara try karo.")
        clips.sort(key=lambda c: c["score"], reverse=True)

        results, n, stamp = [], len(clips), time.strftime("%H%M%S")
        for i, c in enumerate(clips, 1):
            p0 = 64 + 35 * (i - 1) / n
            span = 35 / n
            progress(p0, f"Clip {i}/{n} ban rahi hai...")
            words = clip_caption_words(segments, c, src, tgt, api_key, s.get("ai_model", "")) if s.get("captions") else []
            path = render_clip(video, c, words, work, i, s,
                               on_frac=lambda f, p0=p0, span=span, i=i: progress(
                                   p0 + span * f, f"Clip {i}/{n} ban rahi hai... {int(f * 100)}%"))
            final = out_dir / f"{safe_name(title)}_{stamp}_clip{i}.mp4"
            shutil.copy2(path, final)
            results.append({"clip": c, "path": str(final), "duration": round(c["end"] - c["start"])})
        progress(100, "Ho gaya!")
        return results
    finally:
        if s.get("cleanup", True):
            shutil.rmtree(work, ignore_errors=True)
