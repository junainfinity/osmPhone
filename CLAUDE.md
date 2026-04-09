# osmPhone — Claude Session Context

## RESUME POINT (2026-04-09, session 3)

### Bluetooth status

HFP sink mode is ON. Real Bluetooth tested with iPhone 17 Pro:
- **Scanning**: Works (finds iPhone, TV, other devices)
- **Pairing**: Works but fragile — keys get out of sync if Mac BT name changes or devices are forgotten. Auto-confirm enabled in delegate callback.
- **HFP connect**: Works — gets battery=5/5, signal=1/5, `hfp_connected` event fires. But **SLC drops after ~5 seconds**. `supportedFeatures` set to 0xFF (all features). Needs investigation.
- **OsmBT runs as .app bundle** (`osm-bt/OsmBT.app`) with Info.plist for TCC Bluetooth permission. Do NOT run the binary directly — it will crash.

### What to do next

1. **Fix HFP SLC stability** — the #1 blocker. iPhone disconnects after 5s. Investigate:
   - AT command negotiation logs (add AT command logging)
   - SDP service record (is HFP HF UUID 0x111E registered?)
   - Feature negotiation mismatch (compare with what car stereos advertise)
   - Try `IOBluetoothHandsFreeAudioGateway` as alternative approach

2. **BT-001.5 SCOAudioBridge** — implement CoreAudio capture/injection (blocked on stable HFP)

3. **End-to-end voice test** — once HFP + SCO work, test with Realtime API pipeline

### Project state

- **106 tests passing** (9 Swift + 66 Python + 31 Next.js)
- **PY-001.10 OpenAI Realtime API: COMPLETE** — `audio/realtime.py`, 10/10 tests, config-gated
- All code committed and pushed to https://github.com/junainfinity/osmPhone
- `config.yaml` has the user's ElevenLabs key (local only, gitignored)
- **Never commit API keys to GitHub** — config.yaml is gitignored

### Remaining work (by phase)

**Phase 2 (1 item):** Fix HFP SLC stability (drops after 5s)
**Phase 3 (2 items):** BT-001.5 SCO audio capture/inject, SCO audio injection
**Phase 5 (4 items):** Provider hot-switching, local MLX inference, auto-answer greetings, call screening

### Key files

- `DEV_LOG.md` — full component status tracker
- `ARCHITECTURE.md` — system design, IPC protocol specs
- `TEST_PLAN.md` — all test cases
- `config.yaml` — local config with real API keys (NEVER commit)
- `config.example.yaml` — committed template with empty placeholders

### Important rules

- **NEVER commit config.yaml or any file containing API keys**
- config.yaml is in .gitignore — verify with `git check-ignore config.yaml` before any commit
- Always run `git diff --cached` before committing to check for leaked secrets
