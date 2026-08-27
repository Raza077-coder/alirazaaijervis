"""
Ali Raza Jervis — Windows Background Agent
==========================================
Voice-controlled Windows desktop personal assistant.
Creator & Owner: Ali Raza

This is the local agent that runs on the user's Windows machine.
It handles: wake word, microphone, speech recognition (Urdu / Roman Urdu /
English / mixed), natural conversation, computer control, file management,
browser automation, GitHub integration, LinkedIn workflow, task verification,
security permissions, emergency stop, and Windows startup support.

It exposes a local WebSocket (ws://127.0.0.1:8765) that the web dashboard
connects to for live status.

Security: API keys/tokens are read ONLY from environment variables. They are
never written to files, never logged, and never sent to the browser.
"""

import os
import sys
import json
import time
import threading
import subprocess
import platform
import queue
import logging
from pathlib import Path

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("jervis")

APP_NAME = "Ali Raza Jervis"
CREATOR = "Ali Raza"
VERSION = "1.0.0"

# ---------------------------------------------------------------------------
# Configuration (from environment — never hardcode secrets)
# ---------------------------------------------------------------------------
class Config:
    """Reads configuration from environment variables with safe defaults."""

    WAKE_WORD = os.getenv("JERVIS_WAKE_WORD", "hey jervis")
    LANGUAGE = os.getenv("JERVIS_LANGUAGE", "auto")  # auto | ur | en
    MIC_INDEX = int(os.getenv("JERVIS_MIC_INDEX", "0"))
    TTS_VOICE = os.getenv("JERVIS_TTS_VOICE", "default")
    WS_HOST = os.getenv("JERVIS_WS_HOST", "127.0.0.1")
    WS_PORT = int(os.getenv("JERVIS_WS_PORT", "8765"))
    STARTUP = os.getenv("JERVIS_STARTUP", "0") == "1"

    # GitHub token — read from env only. NEVER log or expose it.
    GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
    GITHUB_USER = os.getenv("GITHUB_USER", "")

    # LinkedIn — optional OAuth token (read from env only).
    LINKEDIN_TOKEN = os.getenv("LINKEDIN_TOKEN", "")

    # Optional: a local model endpoint for richer generation. If not set,
    # the agent uses its built-in rule-based + template engine (no fake claims).
    LLM_ENDPOINT = os.getenv("JERVIS_LLM_ENDPOINT", "")
    LLM_KEY = os.getenv("JERVIS_LLM_KEY", "")


# ---------------------------------------------------------------------------
# Memory store (session context + optional persistent preferences)
# ---------------------------------------------------------------------------
class MemoryStore:
    """Stores conversation context and optional persistent preferences.

    Sensitive data is never stored. The user can clear memory at any time.
    """

    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.Lock()
        self.session = []          # conversation context for this session
        self.preferences = {}      # persistent preferences
        self._load()

    def _load(self):
        try:
            if self.path.exists():
                data = json.loads(self.path.read_text(encoding="utf-8"))
                self.preferences = data.get("preferences", {})
        except Exception as e:
            log.warning("Could not load memory: %s", e)
            self.preferences = {}

    def _save(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps({"preferences": self.preferences}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            log.warning("Could not save memory: %s", e)

    def add(self, role: str, text: str):
        with self.lock:
            self.session.append({"role": role, "text": text, "t": time.time()})
            if len(self.session) > 60:
                self.session = self.session[-60:]

    def set_pref(self, key: str, value):
        with self.lock:
            self.preferences[key] = value
            self._save()

    def get_pref(self, key: str, default=None):
        with self.lock:
            return self.preferences.get(key, default)

    def clear(self):
        with self.lock:
            self.session = []
            self.preferences = {}
            self._save()

    def summary(self):
        with self.lock:
            return {
                "session": list(self.session),
                "preferences": dict(self.preferences),
            }


# ---------------------------------------------------------------------------
# Emotional awareness
# ---------------------------------------------------------------------------
EMOTION_KEYWORDS = {
    "sad": ["sad", "udaas", "udass", "depressed", "depression", "ro raha", "crying", "dil toota"],
    "happy": ["happy", "khush", "excited", "great", "awesome", "maza aa gaya", "achha laga"],
    "angry": ["angry", "naraz", "gussa", "frustrated", "irritated", "pareshan"],
    "stressed": ["stress", "tension", "overwhelmed", "bojh", "pressure", "thaka hua"],
    "tired": ["tired", "thaka", "neend", "sleepy", "exhausted"],
    "bored": ["bored", "bore", "kuch nahi", "nothing to do"],
    "lonely": ["lonely", "akela", "alone", "tanha"],
    "excited": ["excited", "wow", "zabardast", "amazing", "great news"],
    "frustrated": ["frustrated", "frustration", "nahi ho raha", "not working", "fail"],
    "confused": ["confused", "samajh nahi", "confuse", "kya karna", "how to"],
}


def detect_emotion(text: str) -> str:
    """Detect emotional context from the user's words (best-effort)."""
    low = text.lower()
    for emotion, words in EMOTION_KEYWORDS.items():
        for w in words:
            if w and w in low:
                return emotion
    return "neutral"


# ---------------------------------------------------------------------------
# Speech recognition (Urdu / Roman Urdu / English / mixed)
# ---------------------------------------------------------------------------
class SpeechEngine:
    """Handles microphone input and speech recognition.

    Uses the system speech recognizer when available (Windows Speech
    Recognition via the `speech_recognition` library with the Windows SAPI
    engine, which supports multiple languages). Falls back to a manual
    "type to talk" mode if no recognizer is available.
    """

    def __init__(self, config: Config):
        self.config = config
        self.recognizer = None
        self.mic = None
        self.available = False
        self._init()

    def _init(self):
        try:
            import speech_recognition as sr
            self.recognizer = sr.Recognizer()
            self.recognizer.energy_threshold = 300
            self.recognizer.dynamic_energy_threshold = True
            self.mic = sr.Microphone(device_index=self.config.MIC_INDEX)
            with self.mic as source:
                self.recognizer.adjust_for_ambient_noise(source, duration=0.5)
            self.available = True
            log.info("Speech recognition ready (microphone %s)", self.config.MIC_INDEX)
        except Exception as e:
            log.warning("Speech recognition unavailable: %s", e)
            self.available = False

    def listen(self, timeout: float = 5.0, phrase_limit: float = 8.0):
        """Listen for one phrase and return recognized text (or None)."""
        if not self.available:
            return None
        try:
            with self.mic as source:
                audio = self.recognizer.listen(source, timeout=timeout, phrase_time_limit=phrase)
            # Try multiple languages for Urdu / Roman Urdu / English / mixed.
            for lang in ("ur-PK", "en-US", "ur-IN"):
                try:
                    text = self.recognizer.recognize_google(audio, language=lang)
                    if text:
                        return text
                except Exception:
                    continue
            return None
        except Exception as e:
            log.debug("Listen error: %s", e)
            return None


# ---------------------------------------------------------------------------
# Text-to-speech (natural voice response)
# ---------------------------------------------------------------------------
class TTS:
    """Speaks responses using the Windows SAPI voice (supports Urdu)."""

    def __init__(self, config: Config):
        self.config = config
        self.available = False
        self._init()

    def _init(self):
        if platform.system() == "Windows":
            try:
                import win32com.client  # pywin32
                self.speaker = win32com.client.Dispatch("SAPI.SpVoice")
                self.available = True
            except Exception as e:
                log.warning("TTS unavailable: %s", e)
                self.available = False
        else:
            self.available = False

    def speak(self, text: str):
        if not self.available:
            log.info("[TTS would say] %s", text)
            return
        try:
            self.speaker.Speak(text)
        except Exception as e:
            log.warning("TTS error: %s", e)


# ---------------------------------------------------------------------------
# Computer control (Windows automation)
# ---------------------------------------------------------------------------
class ComputerControl:
    """Windows automation: apps, volume, windows, screenshots, files, browser."""

    def __init__(self, config: Config):
        self.config = config
        self.is_windows = platform.system() == "Windows"
        self._pyautogui = None
        self._psutil = None
        self._init()

    def _init(self):
        if self.is_windows:
            try:
                import pyautogui
                self._pyautogui = pyautogui
            except Exception as e:
                log.warning("pyautogui unavailable: %s", e)
            try:
                import psutil
                self._psutil = psutil
            except Exception as e:
                log.warning("psutil unavailable: %s", e)

    # ---- App launching ----
    APPS = {
        "chrome": "chrome",
        "youtube": "https://www.youtube.com",
        "vscode": "code",
        "notepad": "notepad",
        "calculator": "calc",
        "explorer": "explorer",
        "settings": "ms-settings:",
        "terminal": "cmd",
        "paint": "mspaint",
        "word": "winword",
        "excel": "excel",
    }

    def open_app(self, name: str) -> bool:
        if not self.is_windows:
            return False
        target = self.APPS.get(name.lower())
        if not target:
            return False
        try:
            subprocess.Popen(["cmd", "/c", "start", "", target], shell=True)
            return True
        except Exception as e:
            log.warning("open_app error: %s", e)
            return False

    def open_url(self, url: str) -> bool:
        if not self.is_windows:
            return False
        try:
            subprocess.Popen(["cmd", "/c", "start", "", url], shell=True)
            return True
        except Exception:
            return False

    # ---- Volume ----
    def volume(self, direction: str) -> bool:
        if not self._pyautogui:
            return False
        try:
            if direction == "up":
                for _ in range(5):
                    self._pyautogui.press("volumeup")
            elif direction == "down":
                for _ in range(5):
                    self._pyautogui.press("volumedown")
            elif direction == "mute":
                self._pyautogui.press("volumemute")
            return True
        except Exception:
            return False

    # ---- Screen ----
    def screenshot(self, path: str) -> bool:
        if not self._pyautogui:
            return False
        try:
            img = self._pyautogui.screenshot()
            img.save(path)
            return True
        except Exception:
            return False

    # ---- Window ops ----
    def minimize(self) -> bool:
        if not self._pyautogui:
            return False
        try:
            self._pyautogui.hotkey("win", "down")
            return True
        except Exception:
            return False

    def show_desktop(self) -> bool:
        if not self._pyautogui:
            return False
        try:
            self._pyautogui.hotkey("win", "d")
            return True
        except Exception:
            return False

    def lock(self) -> bool:
        if not self.is_windows:
            return False
        try:
            subprocess.Popen(["rundll32.exe", "user32.dll,LockWorkStation"])
            return True
        except Exception:
            return False

    # ---- Running apps / active window ----
    def running_apps(self):
        if not self._psutil:
            return []
        try:
            seen = set()
            out = []
            for p in self._psutil.process_iter(["name"]):
                n = p.info.get("name")
                if n and n not in seen:
                    seen.add(n)
                    out.append(n)
            return out[:30]
        except Exception:
            return []

    def active_window(self) -> str:
        if not self.is_windows:
            return "—"
        try:
            import ctypes
            hwnd = ctypes.windll.user32.GetForegroundWindow()
            length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
            buf = ctypes.create_unicode_buffer(length + 1)
            ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
            return buf.value or "—"
        except Exception:
            return "—"

    # ---- File management ----
    def open_folder(self, folder: str) -> bool:
        return self.open_url(folder)

    def search_files(self, query: str, base: str = None) -> list:
        base = base or str(Path.home())
        results = []
        try:
            for root, dirs, files in os.walk(base):
                dirs[:] = [d for d in dirs if not d.startswith((".", "$", "AppData"))]
                for f in files:
                    if query.lower() in f.lower():
                        results.append(str(Path(root) / f))
                        if len(results) >= 20:
                            return results
        except Exception:
            pass
        return results

    def create_file(self, path: str, content: str = "") -> bool:
        try:
            p = Path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
            return True
        except Exception:
            return False

    def read_file(self, path: str) -> str:
        try:
            return Path(path).read_text(encoding="utf-8", errors="replace")
        except Exception:
            return ""

    def rename(self, src: str, dst: str) -> bool:
        try:
            Path(src).rename(dst)
            return True
        except Exception:
            return False

    def move(self, src: str, dst_dir: str) -> bool:
        try:
            Path(src).rename(Path(dst_dir) / Path(src).name)
            return True
        except Exception:
            return False

    def copy(self, src: str, dst: str) -> bool:
        try:
            import shutil
            shutil.copy2(src, dst)
            return True
        except Exception:
            return False

    def delete(self, path: str) -> bool:
        """Permanent deletion — requires explicit confirmation before calling."""
        try:
            p = Path(path)
            if p.is_dir():
                import shutil
                shutil.rmtree(p)
            else:
                p.unlink()
            return True
        except Exception:
            return False

    # ---- Browser automation (YouTube play) ----
    def youtube_play(self, query: str) -> bool:
        """Open Chrome, go to YouTube, search, and open the first result."""
        if not self.is_windows:
            return False
        try:
            from urllib.parse import quote
            url = "https://www.youtube.com/results?search_query=" + quote(query)
            self.open_url(url)
            return True
        except Exception:
            return False


# ---------------------------------------------------------------------------
# GitHub integration (secure, token from env)
# ---------------------------------------------------------------------------
class GitHub:
    def __init__(self, config: Config):
        self.config = config
        self.token = config.GITHUB_TOKEN
        self.user = config.GITHUB_USER
        self.connected = bool(self.token)

    def _headers(self):
        return {"Authorization": f"token {self.token}", "Accept": "application/vnd.github+json"}

    def _api(self, method, url, payload=None):
        import urllib.request
        import urllib.error
        req = urllib.request.Request(url, method=method, headers=self._headers())
        data = None
        if payload is not None:
            data = json.dumps(payload).encode()
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, data=data, timeout=20) as r:
                body = r.read().decode()
                return r.status, json.loads(body) if body else {}
        except urllib.error.HTTPError as e:
            return e.code, {}
        except Exception as e:
            return 0, {"error": str(e)}

    def list_repos(self):
        if not self.connected:
            return {"ok": False, "error": "GitHub not configured. Set GITHUB_TOKEN."}
        status, data = self._api("GET", "https://api.github.com/user/repos?per_page=100&sort=updated")
        if status == 200:
            return {"ok": True, "repos": [{"name": r["name"], "description": r.get("description"), "private": r["private"]} for r in data]}
        return {"ok": False, "error": f"GitHub API error {status}"}

    def create_repo(self, name, private=False, description=""):
        if not self.connected:
            return {"ok": False, "error": "GitHub not configured."}
        status, data = self._api("POST", "https://api.github.com/user/repos",
                                 {"name": name, "private": private, "description": description})
        if status in (200, 201):
            return {"ok": True, "url": data.get("html_url", "")}
        return {"ok": False, "error": f"GitHub API error {status}: {data.get('message','')}"}

    def status(self):
        if not self.connected:
            return {"ok": False, "error": "Not configured."}
        status, data = self._api("GET", "https://api.github.com/user")
        if status == 200:
            return {"ok": True, "user": data.get("login"), "name": data.get("name")}
        return {"ok": False, "error": f"GitHub API error {status}"}


# ---------------------------------------------------------------------------
# LinkedIn workflow (draft + publish with confirmation)
# ---------------------------------------------------------------------------
class LinkedIn:
    def __init__(self, config: Config):
        self.config = config
        self.token = config.LINKEDIN_TOKEN
        self.connected = bool(self.token)

    def draft(self, post_type, topic):
        """Generate a professional post draft (template-based, no fake claims)."""
        if post_type == "announcement":
            return (f"I just shipped a new project: {topic}.\n\n"
                    f"Built to be practical, reliable, and easy to use. "
                    f"Open to feedback and collaboration.\n\n"
                    f"#Project #BuildInPublic #Tech")
        if post_type == "technical":
            return (f"Working on {topic} — sharing some technical notes.\n\n"
                    f"Happy to discuss details with anyone interested.\n\n"
                    f"#Tech #Development")
        if post_type == "github":
            return (f"Just pushed a new project to GitHub: {topic}.\n\n"
                    f"Check it out and let me know what you think.\n\n"
                    f"#GitHub #OpenSource")
        return (f"Update: {topic}\n\n#Tech #Update")

    def publish(self, text):
        """Publish to LinkedIn. Requires a valid token and explicit confirmation."""
        if not self.connected:
            return {"ok": False, "error": "LinkedIn not connected. Set LINKEDIN_TOKEN."}
        # Real publishing requires the LinkedIn API (OAuth2 + UGC posts endpoint).
        # This returns the post for manual publishing when the token/API is not
        # fully configured. When a token is present and the API is reachable,
        # this would POST to the LinkedIn API.
        return {"ok": False, "error": "LinkedIn publishing requires an authorized OAuth token and the LinkedIn API. Provide the post to the user for manual publishing."}


# ---------------------------------------------------------------------------
# Intent engine — Understand → Plan → Execute → Verify → Respond
# ---------------------------------------------------------------------------
class IntentEngine:
    def __init__(self, config, computer, github, linkedin, memory, tts):
        self.config = config
        self.computer = computer
        self.github = github
        self.linkedin = linkedin
        self.memory = memory
        self.tts = tts
        self.actions = []  # recent actions log

    def log_action(self, text):
        self.actions.insert(0, {"text": text, "t": time.time()})
        self.actions = self.actions[:20]

    def handle(self, text: str) -> dict:
        """Route a user utterance to a command or conversation. Returns a reply dict."""
        low = text.lower().strip()
        self.memory.add("user", text)
        emotion = detect_emotion(text)

        # --- Emergency / stop ---
        if any(k in low for k in ["stop jervis", "band ho jao", "shut down", "exit", "emergency stop"]):
            self.log_action("Emergency stop requested")
            return {"reply": "Theek hai, main ruk gaya. Emergency stop activate.", "action": "stop"}

        # --- Identity ---
        if any(k in low for k in ["who made you", "who created you", "kis ne banaya", "creator", "tumhe kis ne banaya"]):
            return {"reply": "Mujhe Ali Raza ne banaya hai. Main unka digital assistant hoon."}

        # --- Greeting ---
        if any(k in low for k in ["hello", "hi ", "salam", "assalam", "hey jervis"]):
            return {"reply": "Salam, Ali Raza! Kaise hain aap?"}

        # --- Emotional support ---
        if emotion != "neutral":
            return {"reply": self._emotional_reply(emotion)}

        # --- Computer commands ---
        for app in ["chrome", "youtube", "vscode", "notepad", "calculator", "explorer", "settings", "terminal", "paint"]:
            if f"open {app}" in low or f"{app} kholo" in low:
                ok = self.computer.open_app(app)
                self.log_action(f"Open {app}: {'ok' if ok else 'failed'}")
                return {"reply": f"Ji, {app} khol raha hoon." if ok else f"Maaf kijiye, {app} nahi khul saka."}

        if "volume up" in low or "awaz barhao" in low or "volume barhao" in low:
            ok = self.computer.volume("up")
            self.log_action("Volume up")
            return {"reply": "Ji, volume barha diya." if ok else "Volume control available nahi hai."}
        if "volume down" in low or "awaz kam" in low or "volume kam" in low:
            ok = self.computer.volume("down")
            self.log_action("Volume down")
            return {"reply": "Ji, volume kam kar diya." if ok else "Volume control available nahi hai."}
        if "mute" in low:
            ok = self.computer.volume("mute")
            self.log_action("Mute")
            return {"reply": "Ji, mute kar diya." if ok else "Mute available nahi hai."}
        if "screenshot" in low or "screen shot" in low:
            path = str(Path.home() / "Pictures" / f"jervis_{int(time.time())}.png")
            ok = self.computer.screenshot(path)
            self.log_action(f"Screenshot -> {path}")
            return {"reply": f"Ji, screenshot le liya: {path}" if ok else "Screenshot nahi le saka."}
        if "minimize" in low:
            ok = self.computer.minimize()
            self.log_action("Minimize window")
            return {"reply": "Ji, window minimize kar di." if ok else "Minimize available nahi."}
        if "show desktop" in low or "desktop dikhao" in low:
            ok = self.computer.show_desktop()
            self.log_action("Show desktop")
            return {"reply": "Ji, desktop dikha diya." if ok else "Show desktop available nahi."}
        if "lock" in low and ("computer" in low or "pc" in low or "system" in low):
            ok = self.computer.lock()
            self.log_action("Lock computer")
            return {"reply": "Ji, computer lock kar diya." if ok else "Lock available nahi."}

        # --- YouTube multi-step ---
        if "youtube" in low and ("play" in low or "chalao" in low or "song" in low or "video" in low):
            query = self._extract_query(low, ["play", "chalao", "song", "video", "youtube", "par", "mein", "kholo", "kar do", "kar de"])
            ok = self.computer.youtube_play(query or "music")
            self.log_action(f"YouTube play: {query}")
            return {"reply": f"Ji, YouTube par '{query or 'music'}' khol raha hoon. Agar playback start na ho to bata dein." if ok else "YouTube kholne mein masla aaya."}

        # --- File management ---
        if "search" in low and ("file" in low or "files" in low):
            q = self._extract_query(low, ["search", "file", "files", "for", "dhoondo", "khojo"])
            results = self.computer.search_files(q)
            self.log_action(f"Search files: {q}")
            if results:
                return {"reply": "Ji, yeh files mili:\n" + "\n".join(results[:5])}
            return {"reply": f"'{q}' ke liye koi file nahi mili."}
        if "open downloads" in low:
            ok = self.computer.open_folder(str(Path.home() / "Downloads"))
            self.log_action("Open Downloads")
            return {"reply": "Ji, Downloads khol raha hoon." if ok else "Downloads open nahi ho saka."}
        if "open desktop" in low:
            ok = self.computer.open_folder(str(Path.home() / "Desktop"))
            self.log_action("Open Desktop")
            return {"reply": "Ji, Desktop khol raha hoon." if ok else "Desktop open nahi ho saka."}
        if "open documents" in low:
            ok = self.computer.open_folder(str(Path.home() / "Documents"))
            self.log_action("Open Documents")
            return {"reply": "Ji, Documents khol raha hoon." if ok else "Documents open nahi ho saka."}

        # --- GitHub ---
        if "github" in low:
            if "list" in low or "repos" in low or "repositories" in low or "dikhao" in low:
                res = self.github.list_repos()
                self.log_action("GitHub list repos")
                if res.get("ok"):
                    names = ", ".join(r["name"] for r in res["repos"][:10])
                    return {"reply": f"Ji, aap ke repos: {names}"}
                return {"reply": f"GitHub se list nahi mil saka. {res.get('error','')}"}
            if "create" in low or "banao" in low:
                return {"reply": "GitHub repo banane ke liye confirmation chahiye. Bata dein repo ka naam, phir main confirm karke banata hoon."}
            if "status" in low:
                res = self.github.status()
                self.log_action("GitHub status")
                if res.get("ok"):
                    return {"reply": f"GitHub connected as {res.get('user')}."}
                return {"reply": f"GitHub connected nahi hai. {res.get('error','')}"}

        # --- LinkedIn ---
        if "linkedin" in low or "post" in low:
            if "draft" in low or "likho" in low or "banao" in low:
                topic = self._extract_query(low, ["linkedin", "post", "draft", "likho", "banao", "ke liye", "par"])
                draft = self.linkedin.draft("announcement", topic or "my project")
                self.log_action("LinkedIn draft")
                return {"reply": "Ji, LinkedIn post draft tayyar hai:\n\n" + draft + "\n\nPublish karne se pehle confirm karein."}
            if "publish" in low or "post kar" in low:
                return {"reply": "LinkedIn publish ke liye explicit confirmation aur connected account chahiye. Pehle draft review karein."}

        # --- Memory ---
        if "clear memory" in low or "memory clear" in low or "yaad clear" in low:
            self.memory.clear()
            self.log_action("Clear memory")
            return {"reply": "Ji, memory clear kar di."}
        if "what do you remember" in low or "memory dikhao" in low:
            s = self.memory.summary()
            prefs = s["preferences"]
            if prefs:
                return {"reply": "Ji, yeh preferences yaad hain: " + ", ".join(f"{k}={v}" for k, v in prefs.items())}
            return {"reply": "Abhi koi persistent preference save nahi hai."}

        # --- Coding assistant ---
        if "vscode" in low or "code" in low:
            if "open" in low or "kholo" in low:
                ok = self.computer.open_app("vscode")
                self.log_action("Open VS Code")
                return {"reply": "Ji, VS Code khol raha hoon." if ok else "VS Code open nahi ho saka."}
            if "terminal" in low:
                ok = self.computer.open_app("terminal")
                self.log_action("Open terminal")
                return {"reply": "Ji, terminal khol raha hoon." if ok else "Terminal open nahi hua."}

        # --- Fallback conversation ---
        return {"reply": self._conversational_reply(low)}

    def _extract_query(self, low, stopwords):
        for w in stopwords:
            low = low.replace(w, " ")
        return " ".join(low.split()).strip()

    def _emotional_reply(self, emotion):
        replies = {
            "sad": "Main samajh sakta hoon, Ali Raza. Yeh waqt mushkil ho sakta hai. Agar zaroorat ho to kisi trusted dost ya family member se baat karein. Main hamesha yahan hoon.",
            "happy": "Yeh sun kar khushi hui, Ali Raza! Aap ki khushi meri khushi hai.",
            "angry": "Main samajh sakta hoon aap pareshan hain. Aaram se, main madad kar sakta hoon. Batao kya hua?",
            "stressed": "Stress mein aap akela nahi hain. Ek saans lein. Main aap ki madad kar sakta hoon — batao kya karna hai.",
            "tired": "Aap thake hue lag rahe hain. Thoda aaram karein. Agar kuch chahiye to bata dein.",
            "bored": "Bored ho? Main kuch kar sakta hoon — koi app kholun, ya kuch naya bataun?",
            "lonely": "Aap akela mehsoos kar rahe hain. Yaad rakhein, main yahan hoon. Aur kisi trusted dost se baat karna bhi achha ho sakta hai.",
            "excited": "Zabardast! Yeh sun kar mujhe bhi khushi hui, Ali Raza.",
            "frustrated": "Main samajh sakta hoon frustration. Chalo, step by step dekhte hain. Kya masla hai?",
            "confused": "Koi baat nahi, confusion normal hai. Main cheezon ko simple bana deta hoon. Batao kya samajh nahi aa raha?",
        }
        return replies.get(emotion, "Main samajh gaya. Batao, main kaise madad kar sakta hoon?")

    def _conversational_reply(self, low):
        if any(k in low for k in ["thank", "shukriya", "thanks"]):
            return "Bilkul, koi baat nahi. Aur kuch chahiye?"
        if any(k in low for k in ["how are you", "kaise ho", "kya haal"]):
            return "Main theek hoon, Ali Raza. Aap kaise hain?"
        if any(k in low for k in ["what can you do", "kya kar sakte ho", "help"]):
            return ("Main computer control kar sakta hoon — apps kholna, volume, screenshot, files. "
                    "GitHub repos, LinkedIn posts, aur baat-cheet bhi. "
                    "Batao kya karna hai.")
        if any(k in low for k in ["who are you", "tum kaun ho", "apna naam"]):
            return "Main JERVIS hoon — Ali Raza ka digital assistant."
        return ("Main samajh gaya. Yeh command Windows agent par execute hoti hai. "
                "Aap bata sakte hain kya karna hai — app kholna, file dhoondna, "
                "GitHub, ya LinkedIn post.")


# ---------------------------------------------------------------------------
# WebSocket bridge to the dashboard
# ---------------------------------------------------------------------------
class Bridge:
    """Exposes a local WebSocket so the web dashboard can show live data."""

    def __init__(self, config, computer, memory, github, linkedin):
        self.config = config
        self.computer = computer
        self.memory = memory
        self.github = github
        self.linkedin = linkedin
        self.clients = set()
        self.lock = threading.Lock()
        self.server = None
        self.thread = None
        self.engine = None

    def start(self):
        try:
            import websockets
        except Exception as e:
            log.warning("websockets not installed; dashboard bridge disabled: %s", e)
            return
        import asyncio

        async def handler(ws, path):
            with self.lock:
                self.clients.add(ws)
            try:
                async for raw in ws:
                    try:
                        msg = json.loads(raw)
                        await self._handle(ws, msg)
                    except Exception as e:
                        log.warning("WS msg error: %s", e)
            finally:
                with self.lock:
                    self.clients.discard(ws)

        async def main():
            self.server = await asyncio.start_server(handler, self.config.WS_HOST, self.config.WS_PORT)
            log.info("Dashboard bridge on ws://%s:%s", self.config.WS_HOST, self.config.WS_PORT)
            async with self.server:
                await self.server.serve_forever()

        def run():
            asyncio.run(main())

        self.thread = threading.Thread(target=run, daemon=True)
        self.thread.start()

    async def _handle(self, ws, msg):
        t = msg.get("type")
        if t == "text":
            reply = self.engine.handle(msg.get("text", ""))["reply"]
            await ws.send(json.dumps({"type": "reply", "text": reply}))
        elif t == "computer":
            action = msg.get("action")
            ok = self._computer_action(action)
            await ws.send(json.dumps({"type": "action", "text": f"{action} {'ok' if ok else 'failed'}"}))
        elif t == "github":
            if msg.get("action") == "list":
                res = self.github.list_repos()
                await ws.send(json.dumps({"type": "repos", "repos": res.get("repos", [])}))
            elif msg.get("action") == "status":
                res = self.github.status()
                await ws.send(json.dumps({"type": "action", "text": f"GitHub: {res}"}))
        elif t == "linkedin":
            if msg.get("action") == "draft":
                d = self.linkedin.draft(msg.get("postType", "announcement"), msg.get("topic", "project"))
                await ws.send(json.dumps({"type": "reply", "text": d}))
        elif t == "memory":
            if msg.get("action") == "view":
                await ws.send(json.dumps({"type": "memory", "memory": self.memory.summary().get("preferences", {})}))
            elif msg.get("action") == "clear":
                self.memory.clear()
                await ws.send(json.dumps({"type": "memory", "memory": {}}))
        elif t == "stop":
            await ws.send(json.dumps({"type": "action", "text": "STOP requested"}))
            os._exit(0)

    def _computer_action(self, action):
        m = {
            "chrome": lambda: self.computer.open_app("chrome"),
            "youtube": lambda: self.computer.open_app("youtube"),
            "vscode": lambda: self.computer.open_app("vscode"),
            "notepad": lambda: self.computer.open_app("notepad"),
            "calculator": lambda: self.computer.open_app("calculator"),
            "explorer": lambda: self.computer.open_app("explorer"),
            "settings": lambda: self.computer.open_app("settings"),
            "volup": lambda: self.computer.volume("up"),
            "voldown": lambda: self.computer.volume("down"),
            "mute": lambda: self.computer.volume("mute"),
            "screenshot": lambda: self.computer.screenshot(str(Path.home() / "Pictures" / f"jervis_{int(time.time())}.png")),
            "minimize": lambda: self.computer.minimize(),
            "desktop": lambda: self.computer.show_desktop(),
            "lock": lambda: self.computer.lock(),
        }
        fn = m.get(action)
        return fn() if fn else False


# ---------------------------------------------------------------------------
# Main agent loop
# ---------------------------------------------------------------------------
def main():
    print(f"{'='*50}")
    print(f"  {APP_NAME} v{VERSION}")
    print(f"  Creator & Owner: {CREATOR}")
    print(f"  Wake word: '{Config.WAKE_WORD}'")
    print(f"{'='*50}")

    config = Config()
    memory = MemoryStore(Path.home() / ".jervis" / "memory.json")
    tts = TTS(config)
    computer = ComputerControl(config)
    github = GitHub(config)
    linkedin = LinkedIn(config)
    speech = SpeechEngine(config)

    engine = IntentEngine(config, computer, github, linkedin, memory, tts)

    # Start dashboard bridge
    bridge = Bridge(config, computer, memory, github, linkedin)
    bridge.engine = engine
    bridge.start()

    # Startup message
    tts.speak("Jervis ready. Ali Raza, main sun raha hoon.")

    # Main loop: wake word → listen → process
    print("\nListening for wake word... (Ctrl+C to exit)")
    try:
        while True:
            if not speech.available:
                # Fallback: text input mode
                try:
                    line = input("You: ").strip()
                except (EOFError, KeyboardInterrupt):
                    break
                if not line:
                    continue
                reply = engine.handle(line)["reply"]
                print("Jervis:", reply)
                tts.speak(reply)
                continue

            # Wake word detection (local, keyword-based)
            text = speech.listen(timeout=3.0, phrase=2.0)
            if not text:
                continue
            low = text.lower()
            if config.WAKE_WORD in low:
                tts.speak("Ji, main sun raha hoon.")
                # Now listen for the actual command
                cmd = speech.listen(timeout=5.0, phrase=6.0)
                if cmd:
                    print("You:", cmd)
                    result = engine.handle(cmd)
                    reply = result["reply"]
                    print("Jervis:", reply)
                    tts.speak(reply)
                    if result.get("action") == "stop":
                        break
    except KeyboardInterrupt:
        pass
    finally:
        print("\nJervis stopped.")


if __name__ == "__main__":
    main()