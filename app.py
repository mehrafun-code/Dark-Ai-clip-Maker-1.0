import base64
import shutil
import tempfile
import time
from pathlib import Path

import streamlit as st

import clipper

# ================== APNI BRANDING YAHAN BADLO ==================
APP_NAME = "Dark Clip Maker"
OWNER_NAME = "DarkDeathEvil"
TAGLINE = "YouTube link dalo, best clips lo, Reels/Shorts par upload karo"
LOGO_FILE = Path(__file__).parent / "logo.png"
# ================================================================

SRC_LANGS = {"Auto detect": None, "Hindi": "hi", "English": "en", "Punjabi": "pa", "Urdu": "ur"}
TGT_LANGS = {"Same as video (translate nahi)": None, "English": "en", "Hindi": "hi",
             "Punjabi": "pa", "Urdu": "ur"}

logo_exists = LOGO_FILE.exists()
st.set_page_config(page_title=APP_NAME, page_icon=str(LOGO_FILE) if logo_exists else "🎬", layout="wide")

CSS = """
<style>
#MainMenu, footer {visibility: hidden;}
.stApp {background: radial-gradient(1100px 520px at 8% -8%, #2b0a14 0%, #0b0b10 55%) fixed;}
section[data-testid="stSidebar"] {background: #0f0f16; border-right: 1px solid #22222e;}
.block-container {padding-top: 1.6rem; max-width: 1250px;}
.hero {display:flex; align-items:center; gap:20px; padding:18px 24px; border:1px solid #2c2c3a;
  border-radius:20px; background:linear-gradient(135deg,#171722 0%,#140a10 100%);
  box-shadow:0 10px 40px rgba(225,29,72,.10);}
.hero img {width:92px; height:92px; object-fit:contain; filter:drop-shadow(0 0 14px rgba(225,29,72,.45));}
.hero h1 {margin:0; font-size:2.1rem; font-weight:800; letter-spacing:.3px;
  background:linear-gradient(90deg,#ff2d55,#ff8a3d); -webkit-background-clip:text; background-clip:text; color:transparent;}
.hero p {margin:4px 0 0; color:#9a9aae; font-size:.95rem;}
.badge {display:inline-block; margin-top:8px; padding:3px 12px; border-radius:999px; font-size:.75rem;
  color:#ff6b86; border:1px solid #4a1624; background:#1c0c12;}
.pbox {border:1px solid #2c2c3a; border-radius:16px; padding:16px 20px; background:#12121a; margin:14px 0;}
.prow {display:flex; align-items:baseline; gap:14px;}
.pct {font-size:2.2rem; font-weight:800; color:#ff3b5c; min-width:90px;}
.pmsg {flex:1; color:#d8d8e6;}
.ptime {color:#7c7c92; font-variant-numeric:tabular-nums;}
.ptrack {height:12px; border-radius:99px; background:#22222e; overflow:hidden; margin-top:10px;}
.pfill {height:100%; border-radius:99px; background:linear-gradient(90deg,#e11d48,#f97316);
  box-shadow:0 0 14px rgba(249,115,22,.55); transition:width .25s ease;}
div.stButton > button[kind="primary"] {background:linear-gradient(90deg,#e11d48,#f97316); border:0; color:#fff;
  font-weight:700; padding:.7rem 1.6rem; border-radius:12px; width:100%;}
div.stButton > button[kind="primary"]:hover {filter:brightness(1.1);}
div.stButton > button:not([kind="primary"]) {border-radius:10px; border:1px solid #34344a;}
.rcard {border:1px solid #2a2a38; border-radius:16px; padding:12px; background:#12121a; margin-bottom:8px;}
.rtitle {font-weight:700; margin:8px 0 2px; color:#f0f0f8;}
.rmeta {color:#8d8da3; font-size:.85rem;}
.score {display:inline-block; padding:2px 10px; border-radius:99px; background:#2a0f18; color:#ff6b86;
  font-weight:700; font-size:.8rem; margin-right:6px;}
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)

logo_html = ""
if logo_exists:
    b64 = base64.b64encode(LOGO_FILE.read_bytes()).decode()
    logo_html = f'<img src="data:image/png;base64,{b64}">'
st.markdown(
    f'<div class="hero">{logo_html}<div><h1>{APP_NAME}</h1><p>{TAGLINE}</p>'
    f'<span class="badge">by {OWNER_NAME}</span></div></div>', unsafe_allow_html=True)

st.session_state.setdefault("out_dir", str(Path.home() / "Videos" / "DarkClipMaker"))
st.session_state.setdefault("temp_dir", str(Path(tempfile.gettempdir()) / "DarkClipMaker"))


def browse_folder(key):
    p = clipper.pick_folder(st.session_state.get(key))
    if p:
        st.session_state[key] = p


def free_space(path):
    try:
        p = Path(path)
        while not p.exists() and p != p.parent:
            p = p.parent
        return f"{shutil.disk_usage(p).free / 1024 ** 3:.1f} GB khali"
    except Exception:
        return ""


# ---------------- Sidebar ----------------
with st.sidebar:
    st.markdown("### Settings")

    with st.expander("Language / Translation", expanded=True):
        src_label = st.selectbox("Video ki language", list(SRC_LANGS))
        tgt_label = st.selectbox("Captions ki language", list(TGT_LANGS))
        st.caption("Misaal: Hindi → English, Punjabi → Hindi. Hindi/Punjabi ke liye Whisper model "
                   "'medium' behtar hai.")

    with st.expander("Clips & Captions", expanded=True):
        n_clips = st.slider("Kitne clips", 1, 10, 5)
        min_d, max_d = st.slider("Clip length (seconds)", 15, 90, (30, 60))
        captions = st.checkbox("Captions lagao", True)
        cap_color = st.selectbox("Caption highlight rang", list(clipper.HIGHLIGHTS), index=0)
        cap_size = st.select_slider("Caption size", list(clipper.CAPTION_SIZES), value="Medium")
        face_track = st.checkbox("Chehra track karo", True)

    with st.expander("Branding (video par)", expanded=False):
        channel_name = st.text_input("Channel name", placeholder="@DarkDeathEvil",
                                     help="Khali chhodo to video par naam nahi lagega.")
        channel_pos = st.radio("Naam ki jagah", ["Top", "Bottom"], horizontal=True)
        logo_choice = st.radio("Logo", ["Koi nahi", "Mera default logo", "Apna logo upload karo"],
                               index=0)
        uploaded_logo = None
        if logo_choice == "Apna logo upload karo":
            uploaded_logo = st.file_uploader("Logo (PNG)", type=["png", "jpg", "jpeg", "webp"])
        logo_pos = st.selectbox("Logo ki jagah", ["Top-right", "Top-left", "Bottom-right", "Bottom-left"])
        logo_scale = st.slider("Logo size (%)", 8, 30, 16)

    with st.expander("Output folder", expanded=True):
        st.text_input("Clips yahan save hongi", key="out_dir")
        c1, c2 = st.columns(2)
        c1.button("Folder chuno", on_click=browse_folder, args=("out_dir",), use_container_width=True,
                  key="browse_out")
        if c2.button("Folder kholo", use_container_width=True, key="open_out"):
            clipper.open_folder(st.session_state["out_dir"])
        st.caption(free_space(st.session_state["out_dir"]))

    with st.expander("Temp folder (kaam ki files)", expanded=True):
        st.text_input("Temp data yahan save hoga", key="temp_dir",
                      help="Download hui video aur AI model yahan aate hain. C drive bhar raha ho to "
                           "kisi aur drive ka folder chuno.")
        t1, t2 = st.columns(2)
        t1.button("Folder chuno", on_click=browse_folder, args=("temp_dir",), use_container_width=True,
                  key="browse_tmp")
        if t2.button("Folder kholo", use_container_width=True, key="open_tmp"):
            clipper.open_folder(st.session_state["temp_dir"])
        cleanup = st.checkbox("Kaam khatam hone par temp video delete karo", True)
        st.caption(f"{free_space(st.session_state['temp_dir'])}. Kam se kam 5 GB khali rakho. "
                   "AI model isi folder ke 'models' mein rehta hai (ek hi baar download hota hai).")

    with st.expander("AI & Engine", expanded=False):
        api_key = st.text_input("Anthropic API key (optional)", type="password",
                                help="Better clips aur better translation ke liye. Khali = simple scoring.")
        ai_model = st.text_input("AI model", value="claude-sonnet-5-5")
        whisper_size = st.selectbox("Whisper model", ["tiny", "base", "small", "medium"], index=2)
        device = st.selectbox("Device", ["cpu", "cuda"], help="NVIDIA GPU ho to cuda (sirf Python version mein)")
        cookies_choice = st.selectbox("Browser login (age-restricted videos)",
                                      ["Nahi", "firefox", "edge", "chrome"])

# ---------------- Main ----------------
url = st.text_input("YouTube link", placeholder="https://www.youtube.com/watch?v=...")
go = st.button("Generate Clips", type="primary")
progress_ph = st.empty()


def draw_progress(pct, msg, t0):
    el = int(time.time() - t0)
    progress_ph.markdown(
        f'<div class="pbox"><div class="prow"><span class="pct">{int(pct)}%</span>'
        f'<span class="pmsg">{msg}</span><span class="ptime">{el // 60:02d}:{el % 60:02d}</span></div>'
        f'<div class="ptrack"><div class="pfill" style="width:{pct:.1f}%"></div></div></div>',
        unsafe_allow_html=True)


if go:
    if not url.strip():
        st.warning("Pehle YouTube link daalo.")
    elif logo_choice == "Apna logo upload karo" and uploaded_logo is None:
        st.warning("Logo upload karo ya sidebar mein 'Koi nahi' chuno.")
    else:
        logo_path = None
        if logo_choice == "Mera default logo" and logo_exists:
            logo_path = str(LOGO_FILE)
        elif uploaded_logo is not None:
            lp = Path(st.session_state["temp_dir"]) / "dcm_logo_upload.png"
            lp.parent.mkdir(parents=True, exist_ok=True)
            lp.write_bytes(uploaded_logo.getvalue())
            logo_path = str(lp)

        temp_base = Path(st.session_state["temp_dir"])
        try:
            temp_base.mkdir(parents=True, exist_ok=True)
            job_dir = Path(tempfile.mkdtemp(prefix="job_", dir=str(temp_base)))
        except Exception as e:
            st.error(f"Temp folder nahi ban saka: {clipper._clean(e)}")
            st.stop()

        settings = dict(
            url=url.strip(), work_dir=str(job_dir), models_dir=str(temp_base / "models"), cleanup=cleanup,
            out_dir=st.session_state["out_dir"],
            cookies_browser=None if cookies_choice == "Nahi" else cookies_choice,
            api_key=api_key.strip(), ai_model=ai_model.strip(), whisper_size=whisper_size, device=device,
            src_lang=SRC_LANGS[src_label], tgt_lang=TGT_LANGS[tgt_label],
            n_clips=n_clips, min_d=min_d, max_d=max_d, captions=captions, cap_color=cap_color,
            cap_size=cap_size, face_track=face_track, channel_name=channel_name, channel_pos=channel_pos,
            logo_path=logo_path, logo_pos=logo_pos, logo_scale=logo_scale)

        t0 = time.time()
        state = {"p": 0.0, "t": 0.0, "m": ""}

        def progress(pct, msg=""):
            pct = max(state["p"], min(float(pct), 100.0))
            now = time.time()
            if pct < 100 and msg == state["m"] and now - state["t"] < 0.3:
                state["p"] = pct
                return
            state.update(p=pct, t=now, m=msg)
            draw_progress(pct, msg, t0)

        draw_progress(0, "Shuru ho raha hai...", t0)
        try:
            st.session_state["results"] = clipper.run_pipeline(settings, progress)
            st.session_state["results_dir"] = settings["out_dir"]
            progress(100, "Ho gaya!")
        except Exception as e:
            progress_ph.empty()
            st.error(f"Error: {clipper._clean(e)}")

results = st.session_state.get("results")
if results:
    st.success(f"{len(results)} clips tayyar hain. Folder: {st.session_state.get('results_dir')}")
    if st.button("Output folder kholo"):
        clipper.open_folder(st.session_state.get("results_dir"))
    cols = st.columns(3)
    for i, r in enumerate(results):
        with cols[i % 3]:
            st.markdown('<div class="rcard">', unsafe_allow_html=True)
            st.video(r["path"])
            st.markdown(
                f'<div class="rtitle">#{i + 1}  {r["clip"]["title"]}</div>'
                f'<div class="rmeta"><span class="score">Score {r["clip"]["score"]}</span>'
                f'{r["duration"]} sec</div>'
                f'<div class="rmeta">{r["clip"].get("reason", "")}</div>', unsafe_allow_html=True)
            st.caption(Path(r["path"]).name)
            st.markdown("</div>", unsafe_allow_html=True)

st.markdown(f'<p style="text-align:center;color:#5c5c70;margin-top:40px">© {OWNER_NAME} | {APP_NAME}</p>',
            unsafe_allow_html=True)
