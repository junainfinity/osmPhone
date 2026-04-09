# osmPhone Architecture

> Mac as a Smart Bluetooth Headset with LLM-Powered Voice & Text

## Overview

osmPhone turns a MacBook or Mac Mini into an AI-powered Bluetooth headset. The Mac connects to any phone (iPhone or Android) via Bluetooth HFP (Hands-Free Profile), intercepts calls and texts, and processes them through configurable LLM, STT, and TTS providers.

**Requirements**: macOS 13+, any phone with active SIM, Bluetooth enabled on both devices. Apple Silicon recommended for local MLX inference.

### For New Contributors

**Start here**: Read this file top to bottom. Then read `DEV_LOG.md` for current status and gotchas. Then `TEST_PLAN.md` for what to test.

**Key insight**: The Mac acts as a **Bluetooth headset** (HFP Hands-Free unit), not as the phone. The phone is the "Audio Gateway" (AG). This means the phone thinks it's connected to a car kit. All call audio routes through the Mac, and the Mac can control calls/SMS via AT commands. Instead of a microphone, we inject AI-generated speech.

**osmAPI**: This is an OpenAI-compatible API at a custom base URL. We use the standard `openai` Python SDK with `base_url` overridden. No separate provider code needed — just set `llm.base_url` in config.yaml.

**Voice modes**: "autonomous" = LLM answers calls/texts without human approval. "hitl" (human-in-the-loop) = LLM drafts responses but user must approve in the UI before they're sent/spoken.

**Why not a single process?** IOBluetooth is ObjC/Swift only (no Python/Node bindings exist). AI SDKs are Python only. The three-process design is the simplest way to bridge these incompatible runtimes.

---

## System Architecture

Three processes communicating over local sockets:

```
+------------------+   Unix Socket    +------------------+   WebSocket    +------------------+
|    osm-bt        |<---------------->|    osm-core      |<-------------->|    osm-ui        |
|    [Swift]       | /tmp/osmphone    |    [Python]      | ws://localhost |    [Next.js]     |
|                  |    .sock         |                  |     :8765      |                  |
|  BT-001.*        |  JSON-over-\n   |  PY-001.*        |                |  UI-001.*        |
+--------+---------+                  +--------+---------+                +------------------+
         |                                     |
         | Bluetooth HFP                       | HTTPS
         | (classic BT)                        |
         v                                     v
  +--------------+                    +-------------------+
  |  ANY PHONE   |                    |  Cloud APIs       |
  |  with SIM    |                    |  OpenAI / osmAPI  |
  |              |                    |  ElevenLabs       |
  +--------------+                    +-------------------+
```

### Why Three Processes

| Process | Language | Why |
|---------|----------|-----|
| **osm-bt** | Swift | IOBluetooth framework is ObjC/Swift only. NSRunLoop, delegate callbacks, SCO audio channels have no Python/Node bindings. |
| **osm-core** | Python | Best ecosystem for AI: `openai`, `elevenlabs`, `lightning-whisper-mlx`, `mlx-audio`, `mlx-lm` SDKs are all Python-native. |
| **osm-ui** | Next.js | shadcn/ui is React-based. WebSocket provides real-time updates. |

---

## How Bluetooth HFP Works

When the Mac registers as an HFP "Hands-Free" device, the phone sees it like a car kit or Bluetooth headset. The phone becomes the "Audio Gateway" (AG).

Once paired:
- **Phone routes call audio to Mac** via SCO (Synchronous Connection-Oriented) channel
- **Mac controls phone** via AT commands over RFCOMM: answer/reject/dial calls, send/receive SMS
- **Mac sends audio back** through SCO channel -- instead of a real mic, we inject AI-generated speech

Key macOS API: `IOBluetoothHandsFreeDevice` (available since macOS 10.7)
- `acceptCall`, `endCall`, `dialNumber:` for call control
- `transferAudioToComputer`, `transferAudioToPhone` for audio routing
- `sendSMS:message:` for outbound SMS
- `incomingCallFrom:`, `incomingSMS:` delegate callbacks

---

## IPC Protocol: Unix Socket (osm-bt <-> osm-core)

Path: `/tmp/osmphone.sock`
Format: JSON-over-newline. Each message is one JSON object terminated by `\n`.

### Events (osm-bt -> osm-core)

| type | payload | description |
|------|---------|-------------|
| `device_found` | `{address, name, rssi}` | Discovered a BT device during scan |
| `scan_complete` | `{}` | Device scan finished |
| `paired` | `{address, name}` | Successfully paired with device |
| `pair_failed` | `{address, error}` | Pairing failed |
| `pair_confirm` | `{address, name, numeric_value}` | Pairing requires user confirmation of numeric code |
| `hfp_connected` | `{address, signal, battery, service}` | HFP service-level connection established |
| `hfp_disconnected` | `{address, reason}` | HFP connection lost |
| `incoming_call` | `{from, name}` | Phone is ringing, incoming call |
| `call_active` | `{from}` | Call answered, audio active |
| `call_ended` | `{reason}` | Call ended (reasons: `local_hangup`, `remote_hangup`, `rejected`, `missed`) |
| `sco_opened` | `{codec, sample_rate}` | SCO audio channel opened |
| `sco_closed` | `{}` | SCO audio channel closed |
| `sco_audio` | `{codec, sample_rate, data}` | PCM audio frame (base64 encoded). Sent continuously during active call. |
| `sms_received` | `{from, body, timestamp}` | Incoming SMS |
| `sms_sent` | `{to, body, status}` | Outbound SMS delivery status |
| `signal_update` | `{level}` | Phone signal strength changed (0-5) |
| `battery_update` | `{level}` | Phone battery level changed (0-100) |
| `error` | `{code, message}` | Error occurred |

### Commands (osm-core -> osm-bt)

| type | payload | description |
|------|---------|-------------|
| `scan_start` | `{}` | Begin device discovery |
| `scan_stop` | `{}` | Stop device discovery |
| `pair` | `{address}` | Initiate pairing with device |
| `pair_confirm` | `{address, confirmed}` | Confirm/deny numeric pairing |
| `connect_hfp` | `{address}` | Connect HFP to paired device |
| `disconnect_hfp` | `{}` | Disconnect HFP |
| `answer_call` | `{}` | Answer incoming call |
| `reject_call` | `{}` | Reject incoming call |
| `end_call` | `{}` | Hang up active call |
| `dial` | `{number}` | Dial a phone number |
| `send_sms` | `{to, body}` | Send SMS via phone |
| `inject_audio` | `{sample_rate, data}` | Inject PCM audio into SCO output (base64) |
| `transfer_audio` | `{target}` | Transfer audio to `computer` or `phone` |
| `send_dtmf` | `{digit}` | Send DTMF tone during call |

### Message Envelope

Every message has an `id` field for request-response correlation:

```json
{"id": "cmd-001", "type": "scan_start", "payload": {}}
{"id": "evt-001", "type": "device_found", "payload": {"address": "AA:BB:CC:DD:EE:FF", "name": "iPhone 15", "rssi": -45}}
```

---

## WebSocket Protocol (osm-core <-> osm-ui)

URL: `ws://localhost:8765`
Format: JSON messages.

### Server -> Client (events)

| type | data | description |
|------|------|-------------|
| `bt_status` | `{connected, device, address, signal, battery}` | BT connection status update |
| `device_found` | `{address, name, rssi}` | Discovered device during scan |
| `scan_complete` | `{}` | Scan finished |
| `pair_confirm` | `{address, name, numeric_value}` | Needs user to confirm pairing code |
| `incoming_call` | `{from, name}` | Incoming call |
| `call_active` | `{from, duration}` | Call active |
| `call_ended` | `{}` | Call ended |
| `transcript` | `{speaker, text}` | Real-time call transcript. `speaker` is `caller` or `assistant` |
| `llm_response` | `{text, approved}` | LLM generated response. In HITL mode, `approved=false` until user approves |
| `sms_received` | `{from, body, timestamp}` | Incoming SMS |
| `sms_sent` | `{to, body, timestamp}` | Outgoing SMS |
| `llm_sms_draft` | `{to, body}` | LLM drafted SMS reply (HITL mode, awaiting approval) |
| `settings_updated` | `{...settings}` | Settings changed confirmation |
| `error` | `{message}` | Error notification |

### Client -> Server (actions)

| action | data | description |
|--------|------|-------------|
| `scan_devices` | `{}` | Start BT device scan |
| `pair_device` | `{address}` | Pair with device |
| `confirm_pair` | `{address, confirmed}` | Confirm/deny pairing code |
| `connect` | `{address}` | Connect HFP to paired device |
| `disconnect` | `{}` | Disconnect HFP |
| `dial` | `{number}` | Make outgoing call |
| `answer_call` | `{}` | Answer incoming call |
| `reject_call` | `{}` | Reject incoming call |
| `end_call` | `{}` | Hang up |
| `send_sms` | `{to, body}` | Send SMS |
| `approve_response` | `{text}` | Approve (optionally edited) LLM voice response (HITL) |
| `approve_sms` | `{to, body}` | Approve (optionally edited) LLM SMS reply (HITL) |
| `set_voice_mode` | `{mode}` | `autonomous` or `hitl` (human-in-the-loop) |
| `update_settings` | `{...partial_settings}` | Update configuration |

---

## Data Flows

### Text Message Flow (SMS)

```
Phone receives SMS
  -> Phone AG sends AT notification (+CMT/+CMTI) over RFCOMM
  -> osm-bt: IOBluetoothHandsFreeDevice delegate `handsFree:incomingSMS:` fires
  -> osm-bt: Sends {"type":"sms_received"} event over Unix socket
  -> osm-core bt_bridge: Receives event
  -> osm-core sms_handler: Loads conversation history for this contact
  -> osm-core sms_handler: Constructs prompt [system_prompt + history + new message]
  -> osm-core llm_engine: Calls configured LLM (OpenAI / osmAPI / local)
  -> [Autonomous mode]: osm-core sends {"type":"send_sms"} command back to osm-bt
  -> [HITL mode]: osm-core sends {"type":"llm_sms_draft"} to frontend, waits for approval
  -> osm-bt: Calls [handsFreeDevice sendSMS:to message:body]
  -> Phone sends SMS via cellular
  -> Frontend updated with both messages via WebSocket
```

### Voice Call Flow

```
Incoming call:
  Phone rings -> AG sends RING + +CLIP over RFCOMM
  -> osm-bt delegate `handsFree:incomingCallFrom:` fires
  -> osm-bt sends {"type":"incoming_call"} event
  -> osm-core forwards to frontend via WebSocket
  -> Frontend shows incoming call UI

User answers (or auto-answer):
  -> Frontend sends {"action":"answer_call"}
  -> osm-core -> osm-bt: [handsFreeDevice acceptCall]
  -> osm-bt: [handsFreeDevice transferAudioToComputer]
  -> SCO channel opens, delegate fires
  -> osm-bt starts streaming PCM audio frames to osm-core

Voice AI loop (continuous during call):
  -> osm-core audio_pipeline receives PCM frames
  -> VAD detects speech segments (when caller is talking)
  -> When caller finishes speaking:
     -> STT converts speech segment to text
        - Local: lightning-whisper-mlx
        - Cloud: OpenAI Whisper API
     -> Transcript sent to frontend via WebSocket
     -> LLM generates response text
     -> [Autonomous]: immediately run TTS
     -> [HITL]: send to frontend, wait for approval
     -> TTS converts response to PCM audio
        - Local: mlx-audio
        - Cloud: ElevenLabs WebSocket / OpenAI TTS
     -> PCM sent to osm-bt via {"type":"inject_audio"}
     -> osm-bt writes PCM into SCO output
     -> Caller hears AI-generated voice

Fast path (OpenAI Realtime API):
  -> Raw PCM streamed directly to OpenAI Realtime WebSocket
  -> OpenAI handles STT + LLM + TTS in single pipeline (<300ms)
  -> Returns audio chunks, injected into SCO output
  -> Bypasses separate STT/LLM/TTS entirely
```

---

## Component Index

### IF-001: Infrastructure & Scaffolding

| ID | Component | Files | Description | Deps |
|----|-----------|-------|-------------|------|
| IF-001.1 | Project scaffolding | all dirs, manifests | Create directories, package files, __init__.py stubs | None |
| IF-001.2 | Makefile | `Makefile` | `make build`, `make dev`, `make install`, `make test` | IF-001.1 |
| IF-001.3 | Install script | `scripts/install.sh` | Installs Homebrew, Python, Node, BlackHole deps | IF-001.1 |
| IF-001.4 | Config schema | `config.example.yaml` | All settings documented with defaults | IF-001.1 |
| IF-001.5 | BT setup script | `scripts/enable-hfp-sink.sh` | Enables HFP sink mode on macOS 12+ | None |
| IF-001.6 | Launch script | `scripts/launch.sh` | Starts all 3 processes, handles cleanup | IF-001.2 |

### BT-001: osm-bt (Swift Bluetooth Helper)

| ID | Component | Files | Description | Deps |
|----|-----------|-------|-------------|------|
| BT-001.1 | Protocol | `Protocol.swift` | Codable structs for all IPC messages | None |
| BT-001.2 | SocketServer | `SocketServer.swift` | Unix domain socket, JSON-over-newline | BT-001.1 |
| BT-001.3 | BluetoothManager | `BluetoothManager.swift` | Discovery + pairing via IOBluetooth | BT-001.1, BT-001.2 |
| BT-001.4 | HandsFreeController | `HandsFreeController.swift` | IOBluetoothHandsFreeDevice wrapper, call control | BT-001.1-3 |
| BT-001.5 | SCOAudioBridge | `SCOAudioBridge.swift` | SCO audio capture + injection | BT-001.4 |
| BT-001.6 | SMSController | `SMSController.swift` | SMS via HFP AT commands | BT-001.4 |
| BT-001.7 | Main entry | `main.swift` | Wires everything, RunLoop, signal handling | All BT-001.* |

### PY-001: osm-core (Python Backend)

| ID | Component | Files | Description | Deps |
|----|-----------|-------|-------------|------|
| PY-001.1 | Config | `config.py` | YAML config loader, dataclass validation | IF-001.4 |
| PY-001.2 | BT Bridge | `bt_bridge.py` | Async Unix socket client to osm-bt | BT-001.2 |
| PY-001.3 | WS Server | `ws_server.py` | WebSocket server for frontend | None |
| PY-001.4 | LLM Engine | `llm/engine.py`, `llm/openai_provider.py`, `llm/local_provider.py` | LLM abstraction, OpenAI/osmAPI/local MLX | PY-001.1 |
| PY-001.5 | STT Engine | `stt/engine.py`, `stt/whisper_local.py`, `stt/openai_stt.py` | STT abstraction, local Whisper/cloud | PY-001.1 |
| PY-001.6 | TTS Engine | `tts/engine.py`, `tts/mlx_tts.py`, `tts/openai_tts.py`, `tts/elevenlabs_tts.py` | TTS abstraction, local/cloud | PY-001.1 |
| PY-001.7 | VAD | `audio/vad.py` | Voice activity detection | None |
| PY-001.8 | Audio Resampler | `audio/resampler.py` | Sample rate conversion | None |
| PY-001.9 | Audio Pipeline | `audio/pipeline.py` | Real-time STT->LLM->TTS orchestration | PY-001.2,4-8 |
| PY-001.10 | Realtime API | `audio/realtime_api.py` | OpenAI Realtime API integration | PY-001.1-2 |
| PY-001.11 | SMS Handler | `sms/handler.py` | SMS receive -> LLM -> respond | PY-001.2, PY-001.4 |
| PY-001.12 | Conversation Store | `sms/conversation.py` | SQLite conversation history | None |
| PY-001.13 | Main Entry | `main.py` | Starts all services, wires handlers | All PY-001.* |

### UI-001: osm-ui (Next.js Frontend)

| ID | Component | Files | Description | Deps |
|----|-----------|-------|-------------|------|
| UI-001.1 | Project Setup | `package.json`, configs | Next.js + shadcn + Tailwind | IF-001.1 |
| UI-001.2 | WS Provider | `WebSocketProvider.tsx`, `ws-client.ts`, `types.ts` | React context for WebSocket | UI-001.1 |
| UI-001.3 | Layout & Nav | `layout.tsx`, `StatusBar.tsx` | Root layout, tabs, status bar | UI-001.2 |
| UI-001.4 | Device Pairing | `DeviceList.tsx` | Scan, pair, connect UI | UI-001.2 |
| UI-001.5 | Dialer | `Keypad.tsx`, `CallControls.tsx` | Phone keypad + call buttons | UI-001.2 |
| UI-001.6 | Active Call | `ActiveCall.tsx`, `VoiceModeToggle.tsx` | Transcript + HITL controls | UI-001.2,5 |
| UI-001.7 | Incoming Call | `IncomingCall.tsx` | Incoming call overlay | UI-001.2 |
| UI-001.8 | Message Threads | `ThreadList.tsx` | SMS conversation list | UI-001.2 |
| UI-001.9 | Message Thread | `MessageBubble.tsx`, `ComposeBar.tsx` | Individual thread view | UI-001.2 |
| UI-001.10 | Settings | `ProviderConfig.tsx`, `ConnectionStatus.tsx` | Provider config UI | UI-001.2 |

---

## Technology Stack

| Layer | Technology | Version | Purpose |
|-------|-----------|---------|---------|
| BT Helper | Swift + IOBluetooth.framework | Swift 6.2, macOS 13+ | Bluetooth HFP/SCO/AT |
| BT Build | Swift Package Manager | 6.2 | Build system |
| Backend | Python + asyncio | 3.11+ | AI pipeline orchestration |
| LLM (cloud) | openai SDK | 1.x | OpenAI + osmAPI (via base_url) |
| LLM (local) | mlx-lm | latest | Local LLM on Apple Silicon |
| STT (local) | lightning-whisper-mlx | latest | 10x faster than whisper.cpp |
| STT (cloud) | openai SDK (Whisper) | 1.x | Cloud STT |
| TTS (local) | mlx-audio | latest | Local TTS on Apple Silicon |
| TTS (cloud) | elevenlabs SDK | latest | 75ms latency WebSocket TTS |
| TTS (cloud alt) | openai SDK | 1.x | OpenAI TTS |
| Audio routing | BlackHole | 2ch | Virtual audio loopback |
| VAD | silero-vad | latest | Speech/silence detection |
| WS Server | websockets | 14.x | Python WebSocket |
| Frontend | Next.js | 14+ | React framework |
| UI Library | shadcn/ui | latest | Component library |
| Styling | Tailwind CSS | 3.x | Utility CSS |
| Config | PyYAML | 6.x | YAML parsing |
| DB | sqlite3 | stdlib | Conversation persistence |
| Audio math | numpy | latest | PCM buffer ops |

---

## Configuration

See `config.example.yaml` for all settings. Key sections:

- `bluetooth`: device address, auto-connect, auto-answer
- `llm`: provider (openai/osmapi/local), model, base_url, api_key, system_prompt
- `stt`: provider (local/openai), model, language
- `tts`: provider (local/openai/elevenlabs), voice, speed
- `voice_mode`: `autonomous` or `hitl`
- `audio`: sample_rate, vad_threshold, comfort_noise
- `server`: ws_port, socket_path

---

## Key Risks & Mitigations

| Risk | Severity | Mitigation |
|------|----------|------------|
| macOS 12+ disables HFP sink mode | HIGH | `defaults write com.apple.BluetoothAudioAgent "EnableBluetoothSinkMode" -bool true` + reboot. Fallback: raw RFCOMM with manual AT. |
| SCO audio not directly accessible | HIGH | Use BlackHole aggregate device. SCO creates a CoreAudio device selectable as I/O. |
| Voice pipeline latency (2-5s) | MEDIUM | OpenAI Realtime API (<300ms). Local: stream all stages. Comfort tones. |
| SMS compatibility varies by phone | MEDIUM | HFP AT primary. MAP/OBEX fallback for richer access. |
| IOBluetooth documentation sparse | MEDIUM | Reference Phone Amego behavior. Use header dumps. Test iteratively. |

---

## Practical Notes for Developers

### Running the project
```bash
# First time setup
./scripts/install.sh           # installs brew deps, pip, npm packages
./scripts/enable-hfp-sink.sh   # enables BT HFP sink mode (requires reboot!)
cp config.example.yaml config.yaml  # add your API keys

# Development (each in a separate terminal)
make dev-bt    # starts Swift BT helper
make dev-core  # starts Python backend
make dev-ui    # starts Next.js dev server

# Or all at once:
make dev       # runs scripts/launch.sh
```

### Testing
```bash
make test-bt    # Swift XCTests (Protocol encoding/decoding)
make test-core  # Python pytest (config, bt_bridge, ws_server)
make test-ui    # Next.js tests (nothing yet)
```

### Finding IOBluetooth API constants
The IOBluetooth headers are sparse. To find constants:
```bash
# Grep SDK headers directly
grep -r "IOBluetoothHandsFree" /Applications/Xcode.app/Contents/Developer/Platforms/MacOSX.platform/Developer/SDKs/MacOSX.sdk/System/Library/Frameworks/IOBluetooth.framework/Headers/
```

### Debugging Bluetooth
- `system_profiler SPBluetoothDataType` — shows paired devices and profiles
- `defaults read com.apple.BluetoothAudioAgent` — shows audio agent config
- `log stream --predicate 'subsystem == "com.apple.bluetooth"'` — live BT logs
