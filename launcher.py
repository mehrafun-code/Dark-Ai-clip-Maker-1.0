"""DarkClipMaker.exe ka entry point: Streamlit app ko app ki tarah chalata hai."""
import multiprocessing
import os
import sys
from pathlib import Path

import clipper  # noqa: F401  (PyInstaller ko batane ke liye ke ye module chahiye)


def base_dir():
    return Path(getattr(sys, "_MEIPASS", Path(__file__).parent))


if __name__ == "__main__":
    multiprocessing.freeze_support()
    b = base_dir()
    # saath bundle hui ffmpeg use karo
    os.environ["PATH"] = str(b / "ffmpeg") + os.pathsep + os.environ.get("PATH", "")

    from streamlit.web import cli as stcli

    sys.argv = [
        "streamlit", "run", str(b / "app.py"),
        "--global.developmentMode=false",
        "--browser.gatherUsageStats=false",
        "--server.headless=false",
        "--theme.base=dark",
        "--theme.primaryColor=#e11d48",
        "--theme.backgroundColor=#0b0b10",
        "--theme.secondaryBackgroundColor=#14141c",
        "--theme.textColor=#eaeaf0",
    ]
    sys.exit(stcli.main())
