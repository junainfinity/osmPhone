# osmPhone Test Plan

All unit and integration tests for every component. Each test has a unique ID matching its component.

### Test Environment Notes

- **Swift tests**: Run with `cd osm-bt && swift test`. Uses XCTest framework. All tests are pure logic tests (no hardware needed).
- **Python tests**: Run with `cd osm-core && python3 -m pytest tests/ -v`. Uses pytest + pytest-asyncio. Async tests use `@pytest.mark.asyncio`.
- **Unix socket tests** use `/tmp/osm_test_*.sock` paths — NOT `tmp_path` fixtures — because macOS AF_UNIX has a 104-character path limit and pytest's temp dirs are too long.
- **Tests marked "Needs phone"** require a real Bluetooth phone paired to the Mac. These are integration tests (IT-*) and some unit tests in BT-001.3/4.
- **Mock API tests** (PY-001.4/5/6) should use `unittest.mock.patch` or `pytest-httpx` to mock HTTP calls. Don't hit real API endpoints in unit tests.
- **WS server tests** use `port=0` (random available port) to avoid conflicts.
- **Frontend tests** (UT-UI-*) are not yet implemented. Recommend: React Testing Library + mock WebSocket.

### Currently passing (29/29)
- UT-BT-001.1: 9/9 (Protocol encode/decode)
- UT-PY-001.1: 10/10 (Config loading)
- UT-PY-001.2: 4/4 (BT Bridge socket communication)
- UT-PY-001.3: 6/6 (WS Server broadcast/actions)

---

## Unit Tests

### UT-IF: Infrastructure Tests

#### UT-IF-001.1: Project Scaffolding
| Test | Description | Verification |
|------|-------------|-------------|
| UT-IF-001.1-01 | All directories exist | `ls` each expected directory returns 0 |
| UT-IF-001.1-02 | Package.swift is valid | `cd osm-bt && swift package describe` succeeds |
| UT-IF-001.1-03 | pyproject.toml is valid | `cd osm-core && python -m pip install -e . --dry-run` succeeds |
| UT-IF-001.1-04 | package.json is valid | `cd osm-ui && npm install --dry-run` succeeds |
| UT-IF-001.1-05 | All __init__.py files exist | Python imports succeed for all submodules |
| UT-IF-001.1-06 | All stub Swift files exist | `swift build` compiles without missing file errors |

#### UT-IF-001.2: Makefile
| Test | Description | Verification |
|------|-------------|-------------|
| UT-IF-001.2-01 | `make help` lists targets | Output contains build, dev, test, install |
| UT-IF-001.2-02 | `make build` completes | Exit code 0, binaries exist |
| UT-IF-001.2-03 | `make test` runs all test suites | Exit code 0 or reports failures |

#### UT-IF-001.4: Config Schema
| Test | Description | Verification |
|------|-------------|-------------|
| UT-IF-001.4-01 | config.example.yaml is valid YAML | `python -c "import yaml; yaml.safe_load(open('config.example.yaml'))"` succeeds |
| UT-IF-001.4-02 | All required keys present | Config has bluetooth, llm, stt, tts, voice_mode, audio, server sections |
| UT-IF-001.4-03 | Default values are sane | LLM provider defaults to "openai", voice_mode defaults to "hitl" |

---

### UT-BT: Bluetooth Helper Tests

#### UT-BT-001.1: Protocol
| Test | Description | Input | Expected Output |
|------|-------------|-------|-----------------|
| UT-BT-001.1-01 | Encode event to JSON | `DeviceFoundEvent(address:"AA:BB", name:"iPhone", rssi:-45)` | Valid JSON with all fields |
| UT-BT-001.1-02 | Decode command from JSON | `{"id":"cmd-1","type":"scan_start","payload":{}}` | `ScanStartCommand` struct |
| UT-BT-001.1-03 | Reject malformed JSON | `{"type":}` | Decoding error, no crash |
| UT-BT-001.1-04 | Reject unknown command type | `{"id":"x","type":"fly","payload":{}}` | Unknown command error |
| UT-BT-001.1-05 | Round-trip encode/decode | Any event struct | Encode then decode returns identical struct |

#### UT-BT-001.2: SocketServer
| Test | Description | Input | Expected Output |
|------|-------------|-------|-----------------|
| UT-BT-001.2-01 | Server starts and listens | Start server | Socket file exists at /tmp/osmphone_test.sock |
| UT-BT-001.2-02 | Client connects | Connect TCP client | Server reports 1 connected client |
| UT-BT-001.2-03 | Server receives command | Client sends JSON line | Server delegate receives parsed command |
| UT-BT-001.2-04 | Server sends event | Call `sendEvent()` | Client receives JSON line |
| UT-BT-001.2-05 | Multiple messages in sequence | Send 3 JSON lines | All 3 parsed correctly |
| UT-BT-001.2-06 | Partial read handling | Send half a JSON line, then rest | Complete message parsed after second read |
| UT-BT-001.2-07 | Client disconnect cleanup | Client closes socket | Server reports 0 clients, no crash |
| UT-BT-001.2-08 | Server shutdown cleanup | Call `stop()` | Socket file removed |

#### UT-BT-001.3: BluetoothManager
| Test | Description | Verification |
|------|-------------|-------------|
| UT-BT-001.3-01 | Start scan creates inquiry | `IOBluetoothDeviceInquiry` initialized |
| UT-BT-001.3-02 | Stop scan stops inquiry | Inquiry delegate reports stopped |
| UT-BT-001.3-03 | Device found emits event | Mock delegate, check event sent via socket |
| UT-BT-001.3-04 | Pair initiation | `IOBluetoothDevicePair` created with address |
| _Note: Full BT tests require a real phone. These test the code structure only._ |

#### UT-BT-001.4: HandsFreeController
| Test | Description | Verification |
|------|-------------|-------------|
| UT-BT-001.4-01 | Connect creates HF device | `IOBluetoothHandsFreeDevice` initialized |
| UT-BT-001.4-02 | Answer call dispatches | `acceptCall` called on HF device |
| UT-BT-001.4-03 | Dial number dispatches | `dialNumber:` called with correct number |
| UT-BT-001.4-04 | End call dispatches | `endCall` called on HF device |
| UT-BT-001.4-05 | Transfer audio dispatches | `transferAudioToComputer` called |
| _Note: Requires paired phone for real testing._ |

#### UT-BT-001.5: SCOAudioBridge
| Test | Description | Verification |
|------|-------------|-------------|
| UT-BT-001.5-01 | Audio frame encoding | Raw PCM -> base64 -> JSON event is valid |
| UT-BT-001.5-02 | Audio frame decoding | base64 JSON command -> raw PCM bytes correct |
| UT-BT-001.5-03 | Sample rate in event | Event contains correct sample_rate field |

#### UT-BT-001.6: SMSController
| Test | Description | Verification |
|------|-------------|-------------|
| UT-BT-001.6-01 | Send SMS command parsed | Command payload has `to` and `body` fields |
| UT-BT-001.6-02 | SMS received event formatted | Event has `from`, `body`, `timestamp` |
| UT-BT-001.6-03 | Long message handling | Messages >160 chars flagged or split |

---

### UT-PY: Python Backend Tests

#### UT-PY-001.1: Config
| Test | Description | Input | Expected Output |
|------|-------------|-------|-----------------|
| UT-PY-001.1-01 | Load valid config | Valid YAML file | Config dataclass with all fields |
| UT-PY-001.1-02 | Missing file raises error | Non-existent path | FileNotFoundError |
| UT-PY-001.1-03 | Missing required key raises | YAML without `llm` section | ValidationError |
| UT-PY-001.1-04 | Default values applied | Minimal YAML | Defaults filled (voice_mode="hitl", ws_port=8765) |
| UT-PY-001.1-05 | osmAPI config uses base_url | `llm.provider: "osmapi"`, `llm.base_url: "http://..."` | Config.llm.base_url set correctly |

#### UT-PY-001.2: BT Bridge
| Test | Description | Input | Expected Output |
|------|-------------|-------|-----------------|
| UT-PY-001.2-01 | Connect to mock server | Start mock Unix socket server | Bridge connected, no errors |
| UT-PY-001.2-02 | Send command | `bridge.send_command("scan_start", {})` | Mock server receives JSON line |
| UT-PY-001.2-03 | Receive event | Mock server sends JSON line | Bridge event handler called with parsed data |
| UT-PY-001.2-04 | Reconnect on disconnect | Kill mock server, restart | Bridge reconnects within 5s |
| UT-PY-001.2-05 | Multiple events dispatched | 3 events sent | All 3 handlers called in order |

#### UT-PY-001.3: WS Server
| Test | Description | Input | Expected Output |
|------|-------------|-------|-----------------|
| UT-PY-001.3-01 | Server starts | `start()` | Listening on ws://localhost:8765 |
| UT-PY-001.3-02 | Client connects | WebSocket connect | Server reports 1 client |
| UT-PY-001.3-03 | Broadcast event | `broadcast({"type":"bt_status",...})` | All connected clients receive message |
| UT-PY-001.3-04 | Client action dispatched | Client sends `{"action":"dial",...}` | Action handler called |
| UT-PY-001.3-05 | Multiple clients | 3 clients connect | All 3 receive broadcasts |
| UT-PY-001.3-06 | Client disconnect | Client closes | Server reports N-1 clients, no crash |

#### UT-PY-001.4: LLM Engine
| Test | Description | Input | Expected Output |
|------|-------------|-------|-----------------|
| UT-PY-001.4-01 | OpenAI provider generate | messages + system_prompt | String response (mock API) |
| UT-PY-001.4-02 | OpenAI provider stream | messages + system_prompt | AsyncIterator yielding tokens (mock) |
| UT-PY-001.4-03 | osmAPI uses custom base_url | Config with osm base_url | openai client created with that base_url |
| UT-PY-001.4-04 | Provider factory | `create_engine("openai", config)` | OpenAIProvider instance |
| UT-PY-001.4-05 | Invalid provider raises | `create_engine("invalid", config)` | ValueError |
| UT-PY-001.4-06 | API error handling | Mock 500 response | Raises LLMError with details |

#### UT-PY-001.5: STT Engine
| Test | Description | Input | Expected Output |
|------|-------------|-------|-----------------|
| UT-PY-001.5-01 | Local Whisper transcribe | PCM numpy array (16kHz, sine wave) | String (may be empty for non-speech) |
| UT-PY-001.5-02 | OpenAI STT transcribe | PCM audio bytes (mock API) | Transcription string |
| UT-PY-001.5-03 | Provider factory | `create_engine("local", config)` | WhisperLocalEngine instance |
| UT-PY-001.5-04 | Empty audio returns empty | Zero-length PCM | Empty string, no crash |

#### UT-PY-001.6: TTS Engine
| Test | Description | Input | Expected Output |
|------|-------------|-------|-----------------|
| UT-PY-001.6-01 | OpenAI TTS synthesize | "Hello world" | PCM bytes > 0 length (mock) |
| UT-PY-001.6-02 | ElevenLabs stream | "Hello world" | AsyncIterator yielding PCM chunks (mock) |
| UT-PY-001.6-03 | Provider factory | `create_engine("elevenlabs", config)` | ElevenLabsEngine instance |
| UT-PY-001.6-04 | Empty text returns empty | "" | Empty bytes, no crash |

#### UT-PY-001.7: VAD
| Test | Description | Input | Expected Output |
|------|-------------|-------|-----------------|
| UT-PY-001.7-01 | Silence detected | 1s of zeros at 16kHz | `is_speech = False` |
| UT-PY-001.7-02 | Speech detected | 1s of 440Hz sine at 16kHz | `is_speech = True` |
| UT-PY-001.7-03 | Segment boundaries | Speech-silence-speech pattern | Two speech segments returned |
| UT-PY-001.7-04 | Minimum duration filter | 50ms speech blip | Filtered out (below threshold) |

#### UT-PY-001.8: Audio Resampler
| Test | Description | Input | Expected Output |
|------|-------------|-------|-----------------|
| UT-PY-001.8-01 | 8kHz to 16kHz | 1000 samples at 8kHz | 2000 samples at 16kHz |
| UT-PY-001.8-02 | 16kHz to 8kHz | 2000 samples at 16kHz | 1000 samples at 8kHz |
| UT-PY-001.8-03 | Same rate no-op | 16kHz to 16kHz | Same array returned |
| UT-PY-001.8-04 | Preserves amplitude | Sine wave resample | Peak amplitude within 5% |

#### UT-PY-001.9: Audio Pipeline
| Test | Description | Verification |
|------|-------------|-------------|
| UT-PY-001.9-01 | Pipeline state machine | States: IDLE->LISTENING->PROCESSING->SPEAKING->LISTENING |
| UT-PY-001.9-02 | VAD triggers STT | Feed speech audio -> STT called |
| UT-PY-001.9-03 | STT triggers LLM | Transcription produced -> LLM called |
| UT-PY-001.9-04 | LLM triggers TTS (auto) | In autonomous mode: TTS called immediately |
| UT-PY-001.9-05 | LLM waits for approval (HITL) | In HITL mode: TTS NOT called until approve_response received |
| UT-PY-001.9-06 | TTS output injected | TTS produces audio -> inject_audio command sent |

#### UT-PY-001.10: Realtime API
| Test | Description | Verification |
|------|-------------|-------------|
| UT-PY-001.10-01 | WebSocket connection | Mock OpenAI Realtime server -> connected |
| UT-PY-001.10-02 | Audio sent | PCM frames forwarded to WebSocket |
| UT-PY-001.10-03 | Audio received | Response audio chunks received and forwarded to inject |

#### UT-PY-001.11: SMS Handler
| Test | Description | Input | Expected Output |
|------|-------------|-------|-----------------|
| UT-PY-001.11-01 | Incoming SMS triggers LLM | sms_received event | LLM called with message + history |
| UT-PY-001.11-02 | Auto-reply (autonomous) | voice_mode=autonomous | send_sms command sent with LLM response |
| UT-PY-001.11-03 | Draft only (HITL) | voice_mode=hitl | llm_sms_draft sent to frontend, no send_sms |
| UT-PY-001.11-04 | Conversation history | 3 messages in thread | LLM prompt includes all 3 |

#### UT-PY-001.12: Conversation Store
| Test | Description | Input | Expected Output |
|------|-------------|-------|-----------------|
| UT-PY-001.12-01 | Create DB | First call | SQLite file created with schema |
| UT-PY-001.12-02 | Add message | `add_message("+1234", "incoming", "Hi")` | Row inserted |
| UT-PY-001.12-03 | Get history | `get_history("+1234", limit=10)` | List of messages in order |
| UT-PY-001.12-04 | Get all threads | `get_all_threads()` | List with last message per contact |
| UT-PY-001.12-05 | Empty thread | `get_history("+9999")` | Empty list, no error |

---

### UT-UI: Frontend Tests

#### UT-UI-001.1: Project Setup
| Test | Description | Verification |
|------|-------------|-------------|
| UT-UI-001.1-01 | npm install succeeds | Exit code 0, node_modules exists |
| UT-UI-001.1-02 | next build succeeds | Exit code 0 |
| UT-UI-001.1-03 | shadcn configured | components.json exists, `npx shadcn-ui add button` works |

#### UT-UI-001.2: WS Provider
| Test | Description | Verification |
|------|-------------|-------------|
| UT-UI-001.2-01 | Connects to WS server | Mock WS server receives connection |
| UT-UI-001.2-02 | Reconnects on disconnect | Kill server -> restart -> client reconnects |
| UT-UI-001.2-03 | Events distributed | Server sends event -> useWebSocket hook receives it |
| UT-UI-001.2-04 | Actions sent | Hook `sendAction()` -> server receives JSON |

#### UT-UI-001.3: Layout & Nav
| Test | Description | Verification |
|------|-------------|-------------|
| UT-UI-001.3-01 | Renders without crash | Page loads, no console errors |
| UT-UI-001.3-02 | Tab navigation works | Click "Messages" tab -> messages page shown |
| UT-UI-001.3-03 | Status bar shows BT state | bt_status event -> status bar updates |

#### UT-UI-001.4: Device Pairing
| Test | Description | Verification |
|------|-------------|-------------|
| UT-UI-001.4-01 | Scan button sends action | Click -> `scan_devices` action sent |
| UT-UI-001.4-02 | Devices listed | device_found events -> devices shown in list |
| UT-UI-001.4-03 | Pair button sends action | Click device -> `pair_device` action sent |
| UT-UI-001.4-04 | Pairing confirm dialog | pair_confirm event -> numeric code shown |

#### UT-UI-001.5: Dialer
| Test | Description | Verification |
|------|-------------|-------------|
| UT-UI-001.5-01 | Keypad renders 0-9, *, # | All 12 keys visible |
| UT-UI-001.5-02 | Number builds on keypress | Press 1,2,3 -> display shows "123" |
| UT-UI-001.5-03 | Dial button sends action | Press dial -> `dial` action with number |
| UT-UI-001.5-04 | Backspace removes digit | Press backspace -> last digit removed |

#### UT-UI-001.6: Active Call
| Test | Description | Verification |
|------|-------------|-------------|
| UT-UI-001.6-01 | Shows during call | call_active event -> active call UI visible |
| UT-UI-001.6-02 | Transcript updates | transcript events -> text appears in view |
| UT-UI-001.6-03 | Voice mode toggle | Click toggle -> set_voice_mode action sent |
| UT-UI-001.6-04 | HITL approve button | llm_response event (approved=false) -> edit + send button shown |
| UT-UI-001.6-05 | Hangup sends action | Click hangup -> end_call action sent |

#### UT-UI-001.7: Incoming Call
| Test | Description | Verification |
|------|-------------|-------------|
| UT-UI-001.7-01 | Overlay shows | incoming_call event -> overlay visible |
| UT-UI-001.7-02 | Caller ID displayed | Event has `from` -> number shown |
| UT-UI-001.7-03 | Answer sends action | Click answer -> answer_call action |
| UT-UI-001.7-04 | Reject sends action | Click reject -> reject_call action |

#### UT-UI-001.8: Message Threads
| Test | Description | Verification |
|------|-------------|-------------|
| UT-UI-001.8-01 | Threads listed | Mock conversation data -> threads shown |
| UT-UI-001.8-02 | Last message preview | Each thread shows last message snippet |
| UT-UI-001.8-03 | Click opens thread | Click thread -> navigates to /messages/[threadId] |

#### UT-UI-001.9: Message Thread
| Test | Description | Verification |
|------|-------------|-------------|
| UT-UI-001.9-01 | Messages shown as bubbles | Incoming left, outgoing right |
| UT-UI-001.9-02 | LLM messages marked | AI-generated messages have indicator |
| UT-UI-001.9-03 | Compose and send | Type message, click send -> send_sms action |
| UT-UI-001.9-04 | New messages appear | sms_received event -> new bubble added |

#### UT-UI-001.10: Settings
| Test | Description | Verification |
|------|-------------|-------------|
| UT-UI-001.10-01 | Provider dropdowns render | LLM, STT, TTS selectors visible |
| UT-UI-001.10-02 | Change provider sends action | Select "elevenlabs" -> update_settings action |
| UT-UI-001.10-03 | API key input | Type key -> stored (not sent as plaintext in WS) |
| UT-UI-001.10-04 | Voice mode default | Toggle -> update_settings with voice_mode |

---

## Integration Tests

### IT-001: IPC Layer (osm-bt <-> osm-core)

| Test ID | Description | Components | Setup | Steps | Expected Result |
|---------|-------------|------------|-------|-------|-----------------|
| IT-001.1 | Socket handshake | BT-001.2, PY-001.2 | Start osm-bt, then osm-core | 1. osm-bt starts socket server 2. osm-core connects | Both report connected |
| IT-001.2 | Command round-trip | BT-001.2, PY-001.2 | Both running | 1. Python sends scan_start 2. Swift receives, sends device_found | Python receives device_found event |
| IT-001.3 | Rapid message burst | BT-001.2, PY-001.2 | Both running | Send 100 messages in 1 second | All 100 received and parsed |
| IT-001.4 | Reconnection | BT-001.2, PY-001.2 | Both running | 1. Kill osm-bt 2. Restart osm-bt | Python reconnects within 5s |

### IT-002: WebSocket Layer (osm-core <-> osm-ui)

| Test ID | Description | Components | Setup | Steps | Expected Result |
|---------|-------------|------------|-------|-------|-----------------|
| IT-002.1 | Frontend connects | PY-001.3, UI-001.2 | Start osm-core, open UI | UI loads | WS connected indicator shown |
| IT-002.2 | Event forwarding | PY-001.3, UI-001.2 | Both running | BT bridge emits bt_status | Frontend status bar updates |
| IT-002.3 | Action handling | PY-001.3, UI-001.2 | Both running | Click dial in UI | Python action handler called |

### IT-003: SMS End-to-End

| Test ID | Description | Components | Setup | Steps | Expected Result |
|---------|-------------|------------|-------|-------|-----------------|
| IT-003.1 | Receive SMS | BT-001.6, PY-001.11, PY-001.12, UI-001.9 | Full stack running, phone paired | Send SMS to phone from another phone | SMS appears in UI message thread |
| IT-003.2 | LLM auto-reply | BT-001.6, PY-001.11, PY-001.4, UI-001.9 | Autonomous mode, phone paired | Send SMS to phone | LLM response sent back as SMS |
| IT-003.3 | HITL SMS reply | BT-001.6, PY-001.11, PY-001.4, UI-001.9 | HITL mode | Send SMS to phone | Draft shown in UI, only sent after approval |
| IT-003.4 | Manual SMS send | BT-001.6, PY-001.2, UI-001.9 | Phone paired | Type message in UI compose bar, send | SMS sent from phone |

### IT-004: Voice Call End-to-End

| Test ID | Description | Components | Setup | Steps | Expected Result |
|---------|-------------|------------|-------|-------|-----------------|
| IT-004.1 | Receive call | BT-001.4, PY-001.2, UI-001.7 | Phone paired | Call the phone from another phone | Incoming call UI shown with caller ID |
| IT-004.2 | Answer + audio | BT-001.4, BT-001.5, PY-001.9 | Phone paired | Answer call in UI | Caller's voice captured, STT transcript shown |
| IT-004.3 | Voice AI loop (auto) | Full voice stack | Autonomous mode | Caller speaks | AI responds with voice via SCO |
| IT-004.4 | Voice AI loop (HITL) | Full voice stack | HITL mode | Caller speaks | Transcript shown, user approves, then AI speaks |
| IT-004.5 | Outgoing call | BT-001.4, UI-001.5 | Phone paired | Dial number in UI | Phone places call |
| IT-004.6 | Hangup | BT-001.4, UI-001.6 | Active call | Click hangup | Call ended on both sides |

### IT-005: Full System

| Test ID | Description | Steps | Expected Result |
|---------|-------------|-------|-----------------|
| IT-005.1 | Cold start | Run `make dev` | All 3 processes start, UI loads, no errors |
| IT-005.2 | Pair + connect | Scan, pair, connect phone | Status bar shows connected, signal, battery |
| IT-005.3 | Concurrent SMS + call | Receive SMS during active call | Both handled independently |
| IT-005.4 | Provider hot-switch | Change TTS provider in settings during idle | Next voice call uses new provider |
| IT-005.5 | Graceful shutdown | Ctrl+C on launch script | All processes exit cleanly, socket removed |
