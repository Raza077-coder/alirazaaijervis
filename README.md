# Ali Raza Jervis

**Voice-controlled Windows desktop personal assistant.**
Creator & Owner: **Ali Raza**

Jervis is a real, functional Windows background agent that listens for the wake word **"Hey Jervis"**, understands natural speech in **Urdu / Roman Urdu / English / mixed**, and performs computer tasks — all with verification and honest reporting. It never claims success without actually doing the work.

> Public branding: **Ali Raza Jervis**. No third-party model/provider names appear in the UI, branding, or this README.

---

## What's included

| Component | Description |
|-----------|-------------|
| **Web Dashboard** | Dark futuristic command center (Home / Computer / GitHub / LinkedIn / Conversation / Settings). Owner profile image top-right. Large **STOP JERVIS** emergency button. |
| **Windows Agent** | Local Python agent: wake word, mic, speech recognition, TTS, computer control, file management, browser automation, GitHub, LinkedIn, memory, security permissions, startup support. |

---

## 1. Web Dashboard

Live URL: https://raza077-coder.github.io/alirazaaijervis/

The dashboard connects to the local agent over a WebSocket (`ws://127.0.0.1:8765`). When the agent is running, it shows **live** data. When it's not, it clearly shows **offline** state — it never fakes results.

---

## 2. Windows Agent — Installation

### Requirements
- Windows 10/11
- Python 3.9+ ([python.org](https://www.python.org/downloads/))
- A microphone

### Install
```bat
cd agent
pip install -r requirements.txt
```

> **pyaudio note:** if `pip install pyaudio` fails, install the prebuilt wheel from [PyAudio wheels](https://www.lfd.uci.edu/~gohlke/pythonlibs/#pyaudio) or use `pip install pipwin && pipwin install pyaudio`.

### Configure
1. Copy `.env.example` to `.env` and fill in your values (or set them as Windows environment variables).
2. **GitHub token** (required for GitHub features): GitHub → Settings → Developer settings → Personal access tokens → Generate new token. Scope: `repo` or `public_repo`. Put it in `GITHUB_TOKEN`.
3. **LinkedIn token** (optional, for publishing): LinkedIn Developer app → OAuth2 → `w_member_social` scope → put in `LINKEDIN_TOKEN`.

### Run
```bat
cd agent
python jervis_agent.py
```
Or double-click `start_jervis.bat`.

### Start with Windows (optional)
Use Task Scheduler:
1. Open **Task Scheduler** → **Create Task**.
2. Trigger: **At log on**.
3. Action: **Start a program** → `python` → arguments `jervis_agent.py` → start in `agent` folder.
4. Check **Run whether user is logged on or not** (optional).

---

## 3. Environment variables

| Variable | Purpose | Required |
|----------|---------|----------|
| `JERVIS_WAKE_WORD` | Wake phrase (default `hey jervis`) | No |
| `JERVIS_LANGUAGE` | `auto` / `ur` / `en` | No |
| `JERVIS_MIC_INDEX` | Microphone device index | No |
| `JERVIS_WS_HOST` / `JERVIS_WS_PORT` | Dashboard bridge | No |
| `JERVIS_STARTUP` | `1` to enable startup | No |
| `GITHUB_TOKEN` | GitHub personal access token | For GitHub |
| `GITHUB_USER` | Your GitHub username | For GitHub |
| `LINKEDIN_TOKEN` | LinkedIn OAuth2 token | For LinkedIn |

> **Security:** Tokens are read only from environment variables. They are never written to files, never logged, and never sent to the browser.

---

## 4. Supported voice commands

**Wake:** "Hey Jervis"

**Computer**
- "Open Chrome / YouTube / VS Code / Notepad / Calculator / File Explorer / Settings"
- "Volume up / volume down / mute"
- "Take a screenshot"
- "Minimize window" / "Show desktop" / "Lock computer"

**YouTube (multi-step)**
- "Chrome mein YouTube kholo aur sad song play kar do" → opens Chrome → YouTube → searches → plays → verifies → responds. If playback can't start, Jervis says so honestly.

**Files**
- "Search for [file]"
- "Open Downloads / Desktop / Documents"
- "Create / rename / move / copy a file" (deletion requires confirmation)

**Coding**
- "Open VS Code", "Open terminal", "Show project structure", "Check errors"

**GitHub**
- "List my repos", "Create a repo", "Repo status", "Upload project"
- Public repo creation and destructive changes require confirmation.

**LinkedIn**
- "Draft a LinkedIn post about [topic]"
- "Publish the post" (requires explicit confirmation + connected account)

**Memory**
- "What do you remember?", "Clear memory"

**Emotional support**
- Jervis detects mood (sad/happy/angry/stressed/tired/bored/lonely/excited/frustrated/confused) and responds calmly in Roman Urdu. For emergencies it encourages contacting a trusted person or emergency service.

---

## 5. Security & permissions

- **Safe actions** auto-execute (open apps, volume, screenshots).
- **Confirmation required** for: permanent file deletion, public GitHub repo creation, major GitHub changes, sending messages, publishing LinkedIn posts, installing software, important system changes, running unknown executables, financial actions.
- Jervis **never** steals credentials, extracts passwords, bypasses auth, disables security, or accesses unauthorized accounts.
- **Never expose API keys/tokens/passwords/OAuth secrets in frontend code** — all secrets live in the agent's environment.

---

## 6. Troubleshooting

| Problem | Fix |
|---------|-----|
| "Speech recognition unavailable" | Install `pyaudio`; check microphone; set `JERVIS_MIC_INDEX`. |
| No voice response | Install `pywin32`; check Windows TTS voice. |
| GitHub not connected | Set `GITHUB_TOKEN` and `GITHUB_USER`; restart agent. |
| Dashboard shows offline | Start the agent; it opens `ws://127.0.0.1:8765`. |
| Wake word not detected | Speak clearly; adjust `JERVIS_WAKE_WORD`; check mic. |

---

## 7. Project structure

```
alirazaaijervis/
├── index.html              # Web dashboard (single-file app)
├── assets/
│   └── owner.jpg           # Owner profile image
└── agent/
    ├── jervis_agent.py     # Windows background agent (main)
    ├── requirements.txt
    ├── .env.example
    └── start_jervis.bat
```

---

© Ali Raza. Built by Ali Raza for personal use.