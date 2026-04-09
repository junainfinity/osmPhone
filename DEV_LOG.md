# osmPhone Development Log

## Handoff Context (READ THIS FIRST)

**What this project is**: A Mac app that emulates a Bluetooth headset (HFP profile) to any phone, then uses LLM/STT/TTS to handle texts and calls. Three processes: Swift (Bluetooth), Python (AI), Next.js (UI).

**Current state (2026-04-09, update 2)**: Phases 1-4 largely complete. All Python AI components, full Next.js UI, and integration wiring are done. 96/96 tests passing. Remaining: real Bluetooth hardware testing, SCO audio capture, and OpenAI Realtime API.

### What's working (96/96 tests pass)
- **Swift** (9 tests): Protocol encode/decode, all BT wrappers compile
- **Python** (56 tests): Config, BT bridge, WS server, LLM engine, STT engine, TTS engine, VAD, resampler, audio pipeline, SMS handler, conversation store
- **Next.js** (31 tests): WS provider, layout, dialer, active call, incoming call, messages, settings, device pairing
- **main.py fully wired**: BT events -> WS broadcasts, WS actions -> BT commands, audio pipeline + SMS handler instantiated

### What's NOT working / not yet tested
- **No real Bluetooth testing yet**. BT-001.3/4/5/6 compile but need a paired phone.
- **SCOAudioBridge (BT-001.5) is a stub**. CoreAudio capture/injection pipeline TODO.
- **STT local engine (WhisperLocalEngine)** returns placeholder text. Needs `lightning-whisper-mlx`.
- **TTS local engine (LocalTTSEngine)** returns silence. Needs `mlx-audio`.
- **LLM local engine** delegates to OpenAI-compatible endpoint (works with ollama/vllm).
- **PY-001.10 OpenAI Realtime API** not started.
- **Provider hot-switching** (changing STT/TTS mid-session) not implemented in main.py.

### Environment quirks
- Dev machine has **Python 3.9.6** (Xcode default). Tests pass on 3.9.
- **macOS HFP sink mode is probably disabled**. Run `scripts/enable-hfp-sink.sh` and reboot before Bluetooth testing.
- Unix socket tests use `/tmp/osm_test_*.sock` (not `tmp_path`) because macOS AF_UNIX has a 104-char path limit.

### Gotchas discovered during development
1. `IOBluetoothHandsFreeIndicatorBattChg` — NOT `Battery` or `BatteryCharge`. Found by grepping SDK headers.
2. Delegate methods take `IOBluetoothHandsFree!` (base class), not `IOBluetoothHandsFreeDevice!`. Mismatching the type silently fails.
3. `sendATCommand` was renamed to `send(atCommand:)` in a recent SDK.
4. Swift 6 enforces memory exclusivity — `sockaddr_un.sun_path` needs `withUnsafeMutableBytes`.
5. `websockets` 14.x deprecated `WebSocketServerProtocol` — tests pass but emit warnings.
6. **VAD interface mismatch** (fixed): Pipeline needs streaming `process()` method, not just batch `is_speech()`. Added in fix pass.
7. **WS broadcast_sync** (fixed): Pipeline calls sync `broadcast_sync()` from sync methods. Added fire-and-forget wrapper using `loop.create_task()`.
8. **SMS handler broadcast signature** (fixed): Was passing single dict, now uses `(event_type, data)` two-arg call.
9. **OpenAI client requires API key even for tests**: Use `"sk-placeholder"` as fallback to avoid init errors.
10. **store.py was at wrong path** (fixed): Moved to `sms/conversation.py` per spec, kept re-export shim.

### What to tackle next (priority order)
1. **Real Bluetooth testing**: Pair a phone, verify HFP connection and call control work
2. **BT-001.5 SCOAudioBridge**: Implement CoreAudio AudioUnit capture/injection
3. **PY-001.10**: OpenAI Realtime API fast path
4. **Real STT/TTS**: Replace local stubs with lightning-whisper-mlx and mlx-audio
5. **Provider hot-switching**: Implement `update_settings` handler in main.py

---

## How to Use This Log

1. Read `ARCHITECTURE.md` to understand the full system design, protocols, and data flows
2. Read `TEST_PLAN.md` for the test cases you must pass
3. Find a component below with status `NOT_STARTED` whose **all dependencies** have status `COMPLETE`
4. Change its status to `IN_PROGRESS` and fill in "Developed By" with your AI name/session
5. Implement the component following the spec in `ARCHITECTURE.md`
6. Write and run unit tests from `TEST_PLAN.md` for that component
7. Update status to `COMPLETE`, fill in "Tested By", and add notes
8. If integration tests are now runnable (all deps complete), run them and log results below
9. If you hit a blocker, set status to `BLOCKED` and explain in Notes

**Status values**: `NOT_STARTED` | `IN_PROGRESS` | `COMPLETE` | `BLOCKED`

---

## Component Status

### IF-001: Infrastructure & Scaffolding

| ID | Component | Status | Dependencies | Developed By | Tested By | Notes |
|----|-----------|--------|--------------|-------------|-----------|-------|
| IF-001.1 | Project scaffolding | COMPLETE | None | Claude Opus 4.6 | Claude Opus 4.6 | All dirs, Package.swift, pyproject.toml, __init__.py stubs |
| IF-001.2 | Makefile | COMPLETE | IF-001.1 | Claude Opus 4.6 | Claude Opus 4.6 | build/dev/install/test/clean targets |
| IF-001.3 | Install script | COMPLETE | IF-001.1 | Claude Opus 4.6 | - | scripts/install.sh (not run - would install deps) |
| IF-001.4 | Config schema | COMPLETE | IF-001.1 | Claude Opus 4.6 | Claude Opus 4.6 | 10/10 Python tests pass for YAML loading |
| IF-001.5 | BT setup script | COMPLETE | None | Claude Opus 4.6 | - | scripts/enable-hfp-sink.sh (not run - modifies system) |
| IF-001.6 | Launch script | COMPLETE | IF-001.2 | Claude Opus 4.6 | - | scripts/launch.sh |

### BT-001: osm-bt (Swift Bluetooth Helper)

| ID | Component | Status | Dependencies | Developed By | Tested By | Notes |
|----|-----------|--------|--------------|-------------|-----------|-------|
| BT-001.1 | Protocol | COMPLETE | None | Claude Opus 4.6 | Claude Opus 4.6 | 9/9 XCTest pass. All event/command types, encode/decode, round-trip |
| BT-001.2 | SocketServer | COMPLETE | BT-001.1 | Claude Opus 4.6 | Claude Opus 4.6 | Compiles. Needs integration test with Python client |
| BT-001.3 | BluetoothManager | COMPLETE | BT-001.1, BT-001.2 | Claude Opus 4.6 | - | Compiles. Needs real BT device for testing |
| BT-001.4 | HandsFreeController | COMPLETE | BT-001.1, BT-001.2, BT-001.3 | Claude Opus 4.6 | - | Compiles. Needs paired phone for testing |
| BT-001.5 | SCOAudioBridge | IN_PROGRESS | BT-001.4 | Claude Opus 4.6 | - | Stub with CoreAudio discovery. TODO: AudioUnit capture/inject |
| BT-001.6 | SMSController | COMPLETE | BT-001.4 | Claude Opus 4.6 | - | Thin wrapper over HFP sendSMS. Needs phone for testing |
| BT-001.7 | Main entry (Swift) | COMPLETE | All BT-001.* | Claude Opus 4.6 | Claude Opus 4.6 | Compiles, wires all components, signal handling |

### PY-001: osm-core (Python Backend)

| ID | Component | Status | Dependencies | Developed By | Tested By | Notes |
|----|-----------|--------|--------------|-------------|-----------|-------|
| PY-001.1 | Config | COMPLETE | IF-001.4 | Claude Opus 4.6 | Claude Opus 4.6 | 10/10 tests pass. YAML load, defaults, env override |
| PY-001.2 | BT Bridge | COMPLETE | BT-001.2 | Claude Opus 4.6 | Claude Opus 4.6 | 4/4 tests pass. Connect, send, receive, multi-event |
| PY-001.3 | WS Server | COMPLETE | None | Claude Opus 4.6 | Claude Opus 4.6 | 6/6 tests pass. Start, connect, broadcast, actions, multi-client |
| PY-001.4 | LLM Engine | COMPLETE | PY-001.1 | Antigravity | Antigravity | OpenAI/osmAPI compatible factory implemented, verified 6/6 tests |
| PY-001.5 | STT Engine | COMPLETE | PY-001.1 | Antigravity | Antigravity | Whisper/OpenAI wrapper implemented, verified 4/4 tests |
| PY-001.6 | TTS Engine | COMPLETE | PY-001.1 | Antigravity | Antigravity | OpenAI/ElevenLabs wrapper implemented, verified 4/4 tests |
| PY-001.7 | VAD | COMPLETE | None | Antigravity | Antigravity | Simple energy-based VAD implemented, verified 4/4 tests |
| PY-001.8 | Audio Resampler | COMPLETE | None | Antigravity | Antigravity | Linear interpolation resampler implemented, verified 4/4 tests |
| PY-001.9 | Audio Pipeline | COMPLETE | PY-001.2, PY-001.4, PY-001.5, PY-001.6, PY-001.7, PY-001.8 | Antigravity | Antigravity | Real-time orchestration mapping VAD->STT->LLM->TTS in autonomous and hitl states. All unit tests passed |
| PY-001.10 | Realtime API | NOT_STARTED | PY-001.1, PY-001.2 | | | OpenAI Realtime fast path |
| PY-001.11 | SMS Handler | COMPLETE | PY-001.2, PY-001.4 | Antigravity | Antigravity | Orchestrator linking store, LLM, BT. verified 4/4 tests |
| PY-001.12 | Conversation Store | COMPLETE | None | Antigravity | Antigravity | SQLite history completed, passed 5/5 tests |
| PY-001.13 | Main entry (Python) | COMPLETE | All PY-001.* | Claude Opus 4.6 | Claude Opus 4.6 | Full wiring: BT events->WS, WS actions->BT, pipeline+SMS handler instantiated |

### UI-001: osm-ui (Next.js Frontend)

| ID | Component | Status | Dependencies | Developed By | Tested By | Notes |
|----|-----------|--------|--------------|-------------|-----------|-------|
| UI-001.1 | Project Setup | COMPLETE | IF-001.1 | Antigravity | Antigravity | Next.js app scaffolded, dependencies installed, shadcn inited |
| UI-001.2 | WS Provider | COMPLETE | UI-001.1 | Antigravity | Antigravity | React Context + hooks setup for backend WS sync. 4/4 tests pass. |
| UI-001.3 | Layout & Nav | COMPLETE | UI-001.2 | Antigravity | Antigravity | Root layout, bottom tabs navigation, and dynamic connection status bars. 3/3 tests pass. |
| UI-001.4 | Device Pairing | COMPLETE | UI-001.2 | Antigravity | Antigravity | Settings page BT scanner with PIN pair modals |
| UI-001.5 | Dialer | COMPLETE | UI-001.2 | Antigravity | Antigravity | T9 Root Keypad view with HFP dialer hooks |
| UI-001.6 | Active Call | COMPLETE | UI-001.2, UI-001.5 | Antigravity | Antigravity | Global active call slide-up with real-time text logs & HITL controls |
| UI-001.7 | Incoming Call | COMPLETE | UI-001.2 | Antigravity | Antigravity | Globa UI incoming call overlay and dispatch triggers |
| UI-001.8 | Message Threads | COMPLETE | UI-001.2 | Antigravity | Antigravity | SMS thread list view built routing to individual contact spaces |
| UI-001.9 | Message Thread | COMPLETE | UI-001.2 | Antigravity | Antigravity | Individual Conversation text bubble views w/ typing interceptors |
| UI-001.10 | Settings | COMPLETE | UI-001.2 | Antigravity | Antigravity | Provider config logic and inputs bound natively to Next.js routes |

---

## Implementation Order (Recommended)

Work in this order to minimize blocking:

```
Phase 1 (foundation, no phone needed):
  IF-001.1 -> IF-001.4 -> IF-001.2 -> IF-001.3 -> IF-001.5 -> IF-001.6

Phase 2 (IPC layer, no phone needed):
  BT-001.1 -> BT-001.2 (test with mock client)
  PY-001.1 -> PY-001.2 (test against BT-001.2)
  PY-001.3 (test standalone)
  UI-001.1 -> UI-001.2 -> UI-001.3 (test in browser)

Phase 3 (Bluetooth, needs phone):
  BT-001.3 -> BT-001.4 -> BT-001.7 (minimal main)
  BT-001.6 + PY-001.11 + PY-001.12 (SMS pipeline)

Phase 4 (voice, needs phone):
  PY-001.7 -> PY-001.8 -> PY-001.5 -> PY-001.6
  BT-001.5 -> PY-001.9 (voice loop)
  PY-001.10 (Realtime API fast path)

Phase 5 (UI, parallel with Phase 3-4):
  UI-001.4 -> UI-001.5 -> UI-001.6 -> UI-001.7
  UI-001.8 -> UI-001.9
  UI-001.10
  PY-001.4 (multi-provider)

Phase 6 (integration):
  PY-001.13 + BT-001.7 (full main entries)
  End-to-end testing
```

---

## Integration Test Results

_Filled in as integration tests are run. See TEST_PLAN.md for test definitions._

| Test ID | Description | Date | Result | Tested By | Notes |
|---------|-------------|------|--------|-----------|-------|
| | | | | | |

---

## Change Log

_Record significant architectural decisions, changes, or discoveries here._

| Date | Component | Change | Reason | By |
|------|-----------|--------|--------|-----|
| 2026-04-09 | BT-001.4 | Fixed `IOBluetoothHandsFreeIndicatorBattChg` constant name | Header says `BattChg` not `Battery` or `BatteryCharge` | Claude Opus 4.6 |
| 2026-04-09 | BT-001.4 | Fixed delegate method signatures to use `IOBluetoothHandsFree!` | Protocol requires base class type, not `IOBluetoothHandsFreeDevice!` | Claude Opus 4.6 |
| 2026-04-09 | BT-001.4 | Fixed `sendATCommand` -> `send(atCommand:)` | Renamed in recent SDK | Claude Opus 4.6 |
| 2026-04-09 | BT-001.2 | Fixed `sockaddr_un.sun_path` overlapping access | Swift 6 exclusivity enforcement | Claude Opus 4.6 |
| 2026-04-09 | PY-001.7 | Added streaming `process()` method to SimpleVAD | Pipeline needs per-frame VAD, not batch-only | Claude Opus 4.6 |
| 2026-04-09 | PY-001.3 | Added `broadcast_sync()` to WSServer | Pipeline calls sync broadcast from sync methods | Claude Opus 4.6 |
| 2026-04-09 | PY-001.9 | Fixed `broadcast_sync` call signature to `(event_type, data)` | Was passing single dict, mismatched WSServer API | Claude Opus 4.6 |
| 2026-04-09 | PY-001.9 | Changed `bt_bridge.inject_audio` to `bt_bridge.send_command("inject_audio")` | inject_audio is not a method on BTBridge | Claude Opus 4.6 |
| 2026-04-09 | PY-001.11 | Fixed handler signature to `(event_id, payload)` + broadcast 2-arg call | Matched bt_bridge handler signature and WSServer API | Claude Opus 4.6 |
| 2026-04-09 | PY-001.11 | Fixed `self.self_llm_generate` typo -> `self.llm_engine.generate` | Typo causing AttributeError | Claude Opus 4.6 |
| 2026-04-09 | PY-001.4 | Added separate LocalLLMEngine class | "local" provider was aliased to OpenAI, now has distinct class | Claude Opus 4.6 |
| 2026-04-09 | PY-001.5 | Replaced mock STT with real OpenAI Whisper API implementation | Was returning hardcoded "mock local transcription" | Claude Opus 4.6 |
| 2026-04-09 | PY-001.6 | Replaced mock TTS with real OpenAI/ElevenLabs API implementations | Was returning fake bytes, not valid PCM | Claude Opus 4.6 |
| 2026-04-09 | PY-001.12 | Moved store.py -> sms/conversation.py per spec | ARCHITECTURE.md specifies sms/conversation.py location | Claude Opus 4.6 |
| 2026-04-09 | PY-001.13 | Wired main.py with full component integration | Was skeleton with `pass` stubs, now fully operational | Claude Opus 4.6 |
| 2026-04-09 | UI-001.4 | Fixed pairing test selectors to match actual UI text | Test said "Scan Devices" but button says "Scan" | Claude Opus 4.6 |
