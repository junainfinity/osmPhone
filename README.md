<p align="center">
  <img src="https://img.shields.io/badge/macOS-13%2B-000000?style=flat-square&logo=apple&logoColor=white" alt="macOS 13+"/>
  <img src="https://img.shields.io/badge/Swift-6.2-F05138?style=flat-square&logo=swift&logoColor=white" alt="Swift"/>
  <img src="https://img.shields.io/badge/Python-3.11%2B-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python"/>
  <img src="https://img.shields.io/badge/Next.js-14%2B-000000?style=flat-square&logo=next.js&logoColor=white" alt="Next.js"/>
  <img src="https://img.shields.io/badge/Bluetooth-HFP-0082FC?style=flat-square&logo=bluetooth&logoColor=white" alt="Bluetooth HFP"/>
  <img src="https://img.shields.io/badge/license-MIT-green?style=flat-square" alt="MIT License"/>
</p>

<h1 align="center">osmPhone</h1>

<p align="center">
  <strong>Turn your Mac into a smart Bluetooth headset that answers calls and texts with AI.</strong>
</p>

<p align="center">
  Your MacBook or Mac Mini already pairs with every phone via Bluetooth.<br/>
  osmPhone makes it act as an HFP headset — then plugs in LLM, STT, and TTS<br/>
  so your phone's calls and texts are handled by an AI assistant.
</p>

<p align="center">
  <a href="#how-it-works">How It Works</a> ·
  <a href="#features">Features</a> ·
  <a href="#quick-start">Quick Start</a> ·
  <a href="#architecture">Architecture</a> ·
  <a href="#configuration">Configuration</a> ·
  <a href="#development">Development</a> ·
  <a href="#roadmap">Roadmap</a>
</p>

---

## How It Works

```
┌─────────────┐   Bluetooth HFP   ┌─────────────────────────────────────────┐
│             │◄─────────────────►│              YOUR MAC                    │
│  Any Phone  │   call audio +    │                                         │
│  with SIM   │   AT commands     │  ┌─────────┐  ┌──────────┐  ┌────────┐ │
│             │                   │  │ osm-bt  │──│ osm-core │──│ osm-ui │ │
│  iPhone     │                   │  │ (Swift) │  │ (Python) │  │(Next.js│ │
│  Android    │                   │  │         │  │          │  │shadcn) │ │
│  any phone  │                   │  │ HFP/SCO │  │ LLM/STT/ │  │Dialer  │ │
│             │                   │  │ pairing │  │ TTS/VAD  │  │  UI    │ │
└─────────────┘                   │  └─────────┘  └──────────┘  └────────┘ │
                                  └─────────────────────────────────────────┘
```

Your phone thinks the Mac is a **Bluetooth headset** (like a car kit). osmPhone intercepts all call audio and SMS messages, processes them through configurable AI providers, and responds — either autonomously or with your approval.

**No jailbreaking. No special hardware. No phone app needed.** Just standard Bluetooth that every phone already supports.

---

## Features

### Voice Calls
- **Answer calls with AI** — caller hears a natural voice powered by your choice of TTS
- **Real-time transcription** — see what the caller says as they speak
- **Two voice modes**:
  - `autonomous` — AI answers and converses without intervention
  - `hitl` (human-in-the-loop) — you see the transcript, edit the response, then approve
- **Make outgoing calls** from the web dialer using the phone's SIM
- **Fast path** — OpenAI Realtime API for sub-300ms voice responses

### Text Messages
- **Read incoming SMS** in a clean message thread UI
- **AI auto-reply** — LLM drafts contextual responses using conversation history
- **Manual compose** — type and send SMS directly from the Mac
- **Per-thread control** — toggle auto-reply on/off per contact

### Provider Flexibility
| Capability | Cloud Options | Local Options (Apple Silicon) |
|------------|--------------|-------------------------------|
| **LLM** | OpenAI, osmAPI (any OpenAI-compatible endpoint) | mlx-lm |
| **STT** | OpenAI Whisper | lightning-whisper-mlx (10x faster than whisper.cpp) |
| **TTS** | OpenAI TTS, ElevenLabs (75ms WebSocket) | mlx-audio |
| **Voice** | OpenAI Realtime API (end-to-end <300ms) | — |

### Web UI
- **Phone dialer** with T9 keypad
- **Message threads** with bubble-style conversation view
- **Settings panel** for provider switching, API keys, voice mode
- **Status bar** showing Bluetooth connection, signal strength, battery level
- Built with **shadcn/ui** + **Tailwind CSS** — minimal, clean, fast

---

## Quick Start

### Prerequisites

| Requirement | Details |
|-------------|---------|
| **Mac** | MacBook or Mac Mini, macOS 13+ (Ventura). Apple Silicon recommended for local inference. |
| **Phone** | Any phone with an active SIM — iPhone, Android, anything with Bluetooth. |
| **Bluetooth** | Enabled on both devices. No dongle needed. |

### Install

```bash
git clone https://github.com/junainfinity/osmPhone.git
cd osmPhone

# Install all dependencies (Homebrew, Python, Node, BlackHole audio driver)
./scripts/install.sh

# Enable Bluetooth HFP sink mode (one-time, requires reboot)
./scripts/enable-hfp-sink.sh

# Configure your API keys
cp config.example.yaml config.yaml
# Edit config.yaml with your OpenAI/ElevenLabs keys
```

### Run

```bash
# Start everything
make dev

# Or run each component separately:
make dev-bt     # Swift Bluetooth helper
make dev-core   # Python AI backend
make dev-ui     # Next.js frontend at http://localhost:3000
```

### Connect

1. Open `http://localhost:3000` in your browser
2. Go to **Settings** → **Scan for Devices**
3. Select your phone and pair
4. Start making and receiving calls/texts through the web UI

---

## Architecture

osmPhone is three processes communicating over local sockets:

| Process | Language | Role | Communication |
|---------|----------|------|---------------|
| **osm-bt** | Swift | Bluetooth HFP via `IOBluetooth.framework` — device pairing, call control, SCO audio, SMS | Unix socket (`/tmp/osmphone.sock`) |
| **osm-core** | Python | AI orchestration — LLM, STT, TTS, VAD, audio pipeline, conversation history | Unix socket ↔ WebSocket |
| **osm-ui** | Next.js | Web UI — dialer, messages, settings, real-time status | WebSocket (`ws://localhost:8765`) |

**Why three processes?** IOBluetooth is Swift/ObjC only. AI SDKs (openai, elevenlabs, mlx) are Python only. The web UI is React. Each runtime gets its own process, connected by lightweight socket protocols.

### Voice Call Data Flow

```
Caller speaks → Phone routes audio via Bluetooth SCO
  → osm-bt captures PCM → sends to osm-core
  → VAD detects speech boundaries
  → STT converts speech to text
  → LLM generates response
  → TTS synthesizes voice
  → osm-bt injects audio back into SCO
  → Caller hears AI response
```

### IPC Protocol

JSON-over-newline on Unix socket. Every message:
```json
{"id": "evt-001", "type": "incoming_call", "payload": {"from": "+1234567890", "name": "John"}}
```

Full protocol spec with all event/command types: [`ARCHITECTURE.md`](ARCHITECTURE.md)

---

## Configuration

All settings in `config.yaml`. See [`config.example.yaml`](config.example.yaml) for documented defaults.

```yaml
llm:
  provider: "openai"           # openai | osmapi | local
  model: "gpt-4o-mini"
  base_url: ""                 # set for osmAPI (OpenAI-compatible endpoint)

stt:
  provider: "local"            # local (lightning-whisper-mlx) | openai

tts:
  provider: "elevenlabs"       # local (mlx-audio) | openai | elevenlabs
  voice: "nova"

voice_mode:
  default: "hitl"              # hitl (human-in-the-loop) | autonomous
```

Environment variables override YAML:
- `OPENAI_API_KEY` → `llm.api_key`
- `ELEVENLABS_API_KEY` → `tts.elevenlabs_api_key`
- `OSM_API_BASE_URL` → `llm.base_url`

---

## Development

### Multi-AI Development Workflow

osmPhone is designed for **parallel development by multiple AI agents or human developers**. Every component has a unique ID, explicit dependencies, and test cases.

| File | Purpose |
|------|---------|
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | Full system design, protocol specs, component index |
| [`DEV_LOG.md`](DEV_LOG.md) | Component status tracker — pick up any `NOT_STARTED` component |
| [`TEST_PLAN.md`](TEST_PLAN.md) | Unit + integration tests for every component |

**To contribute**: Read `DEV_LOG.md`, find a component with all dependencies complete, implement it, run the tests, update the log.

### Testing

```bash
make test          # all tests
make test-bt       # Swift (9 tests — protocol encoding)
make test-core     # Python (20 tests — config, socket bridge, WebSocket)
make test-ui       # Next.js (not yet implemented)
```

### Project Structure

```
osmPhone/
├── ARCHITECTURE.md          # System design & protocol specs
├── DEV_LOG.md               # Component development tracker
├── TEST_PLAN.md             # All test cases
├── config.example.yaml      # Configuration reference
├── Makefile                 # Build orchestration
├── osm-bt/                  # Swift — Bluetooth HFP helper
│   ├── Package.swift
│   ├── Sources/OsmBT/       # 7 source files
│   └── Tests/OsmBTTests/    # Protocol unit tests
├── osm-core/                # Python — AI backend
│   ├── pyproject.toml
│   ├── osm_core/            # config, bt_bridge, ws_server, llm/, stt/, tts/, audio/, sms/
│   └── tests/               # pytest async tests
├── osm-ui/                  # Next.js — Web frontend (scaffold)
│   ├── app/                 # dialer, messages, settings pages
│   ├── components/          # shadcn UI components
│   └── lib/                 # WebSocket client, types
└── scripts/                 # install, launch, BT setup
```

---

## Roadmap

### Phase 1 — Foundation ✅
- [x] IPC protocol and socket communication layer
- [x] Configuration system with multi-provider support
- [x] WebSocket server for frontend
- [x] Swift Bluetooth HFP wrapper (compiles, needs hardware testing)
- [x] Full documentation and test plan

### Phase 2 — Bluetooth & SMS (in progress)
- [ ] Real device pairing and HFP connection
- [x] SMS send/receive orchestration (Python layer)
- [x] LLM-powered auto-reply for texts
- [x] Conversation history (SQLite)

### Phase 3 — Voice Calls
- [ ] SCO audio capture via CoreAudio
- [x] Voice activity detection (VAD)
- [x] STT → LLM → TTS pipeline engine implementation
- [x] Audio resampling engine
- [ ] Audio injection back into SCO channel
- [ ] OpenAI Realtime API fast path

### Phase 4 — Web UI
- [x] Next.js + shadcn framework bootstrap
- [x] Next.js dialer interface
- [x] Real-time call transcript view
- [ ] Message thread interface
- [ ] Settings and provider switching

### Phase 5 — Polish
- [ ] Multi-provider hot-switching
- [ ] Local MLX inference (fully offline mode)
- [ ] Auto-answer with custom greetings
- [ ] Call screening and spam detection

---

## How Bluetooth HFP Works

When your Mac registers as an HFP "Hands-Free" device, the phone sees it exactly like a car infotainment system or Bluetooth headset. The phone becomes the "Audio Gateway" (AG).

| What happens | How |
|-------------|-----|
| Phone routes call audio to Mac | SCO (Synchronous Connection-Oriented) channel |
| Mac controls the phone | AT commands over RFCOMM serial channel |
| Mac sends audio back to caller | PCM injection into SCO output |
| Mac receives/sends SMS | AT+CMGS / AT+CMGR commands via HFP |

The key macOS API is `IOBluetoothHandsFreeDevice` (available since macOS 10.7). osmPhone wraps this in a clean Swift interface with JSON IPC, making the Bluetooth layer accessible from Python.

---

## Known Limitations

- **macOS 12+ disables HFP sink mode by default** — must run `scripts/enable-hfp-sink.sh` and reboot
- **SMS over HFP limited to 160 characters** — some phones silently truncate
- **SMS compatibility varies by phone model** — HFP AT commands are standard but not every AG implements them identically
- **SCO audio is 8kHz CVSD** (phone-quality) — this is a Bluetooth limitation, not ours
- **IOBluetooth documentation is sparse** — we've reverse-engineered constants from SDK headers

---

## License

MIT

---

<p align="center">
  <sub>Built with Swift, Python, Next.js, and too many hours reading IOBluetooth headers.</sub>
</p>
