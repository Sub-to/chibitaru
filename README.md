# 🔵 Chibitaru — USB Security Agent

> *"Just plug in, and your guardian awakens."*

**Chibitaru** is a portable, fully offline AI security system that fits on a USB drive.  
Inspired by the **Nagashino battle's rotating volley tactic** (1575), it deploys **3 AI agents in rotation** to detect threats — majority vote prevents false alarms.

---

## ✨ Features

- 🔵 **Aoko (Blue Triple Star)** — 3 local AI agents (Qwen2.5-1.5B) watching in parallel
- 🦠 **ClamAV** — Virus scanning with offline DB (3.6M+ signatures)
- 👁️ **Kuramaru** — Obsidian vault quality guardian
- 👹 **Onimaru** — File integrity monitor
- 🖥 **Dashboard** — One-screen view of weather, news, conflict & earthquake alerts, and FX rates ([details](dashboard/README.md)) — free, no API keys, logs to your Obsidian vault
- 💻 **Cross-platform** — macOS / Linux / Windows 11

---

## 🚀 Quick Start

### macOS / Linux
```bash
bash /path/to/chibitaru/start.sh
```

### Windows 11
```
Double-click start.bat
```

---

## 🏗️ Architecture

```
USB Drive
├── aoko/               ← AI security agents
│   ├── conductor.py    ← Majority-vote orchestrator
│   ├── monitor.py      ← OS event collector
│   ├── response.py     ← Action executor
│   ├── launch.sh       ← macOS/Linux launcher
│   └── launch_win.bat  ← Windows launcher
│
├── bin/
│   ├── llama-server        ← macOS ARM binary
│   ├── linux-x64/          ← Linux x64 binaries + .so
│   └── win-x64/            ← Windows x64 binaries + .dll
│
├── dashboard/          ← 🖥 One-screen dashboard (stdlib only)
│   ├── server.py       ← Local server + source diagnostics (--check)
│   ├── providers.py    ← Weather / quake / FX / news
│   ├── obsidian.py     ← Vault logger (graph-view links)
│   └── static/         ← UI (no CDN, works offline)
│
├── scan/clamdb/        ← Place CVD files here
├── install/            ← Agent installers
├── start.sh            ← macOS/Linux menu
└── start.bat           ← Windows menu
```

---

## 🤖 How the Blue Triple Star Works

```
Threat detected
      ↓
Agent A (File/Process)  ─┐
Agent B (Network)        ├─→ Majority vote (2/3) → Final level
Agent C (AI Injection)  ─┘
      ↓
SAFE     → Log only
LOW      → Notification
MEDIUM   → Alert (suggest network disconnect)
HIGH     → Auto-isolate vault + alert
CRITICAL → Ask human to decide  ← Human always makes final call
```

---

## 📦 Setup

### 1. AI Model
Download **Qwen2.5-1.5B-Instruct-Q4_K_M.gguf** (~940MB):  
https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF  
Place at: `aoko/model/Qwen2.5-1.5B-Instruct-Q4_K_M.gguf`

### 2. ClamAV Database
```bash
freshclam --datadir=./scan/clamdb
```
Or download manually from https://www.clamav.net/downloads  
Files needed: `main.cvd`, `daily.cvd`, `bytecode.cvd`

### 3. llama-server (pre-built binaries included in `bin/`)
Or install via: `brew install llama.cpp` (macOS) / apt / releases page

### 4. Launch
```bash
bash start.sh     # macOS / Linux
start.bat         # Windows
```

---

## 💻 OS Support

| OS | llama-server | Notification | Network cut |
|----|-------------|-------------|------------|
| macOS (ARM/Intel) ✅ | `bin/llama-server` | osascript | networksetup |
| Linux x64 (CachyOS/Arch) ✅ | `bin/linux-x64/` | notify-send | nmcli |
| Windows 11 x64 ✅ (tested 2026-05-14) | `bin/win-x64/` | PowerShell Toast | netsh |

---

## 🔧 Tech Stack (all free & open source)

| Tool | Purpose | License |
|------|---------|---------|
| [llama.cpp](https://github.com/ggml-org/llama.cpp) | Local LLM inference | MIT |
| [Qwen2.5-1.5B](https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF) | AI model | Apache 2.0 |
| [ClamAV](https://www.clamav.net/) | Virus scanning | GPL v2 |
| Python 3.x | Glue code | PSF |

**Zero cloud. Zero subscription. Zero data sent externally.**

---

## ⚠️ Notes

- **Human always makes the final call** on CRITICAL events
- All AI inference runs 100% locally — no external connections ever

---

## 💬 Why?

> In today's world, proactive digital defense is essential. This AI-powered tool is designed to detect threats at an early stage. By alerting the user the moment a risk is sensed, it buys critical time to disconnect from the network or take other security measures. I built this to help people take control of their own digital safety.
>
> But a 1.5B parameter AI fits on a USB drive 

---

## 📄 License

MIT — use freely, modify freely, share freely.

---
*Chibitaru v1.1 — Made with ❤️ and Nagashino tactics*
