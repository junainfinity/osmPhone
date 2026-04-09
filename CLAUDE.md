# osmPhone — Claude Session Context

## RESUME POINT (after reboot on 2026-04-09)

HFP sink mode was enabled via `defaults write` right before reboot. The next step is **Phase 2 completion: real Bluetooth hardware testing**.

### What to do immediately

1. **Verify HFP sink mode is active after reboot:**
   ```bash
   defaults read com.apple.BluetoothAudioAgent EnableBluetoothSinkMode
   # Should return: 1
   ```

2. **Ask the user to turn on Bluetooth on their phone** (iPhone or Android) and make it discoverable.

3. **Start osm-bt and test real Bluetooth pairing:**
   ```bash
   cd /Users/arjun/Projects/osmPhone/osm-bt && swift run OsmBT
   ```
   Then from another terminal, connect with a Python test client to send scan_start and pair commands through the Unix socket. Or start the full stack with `make dev` and use the web UI to scan/pair.

4. **Test the full chain:**
   - Device discovery (scan_start -> device_found events)
   - Pairing (pair -> pair_confirm -> paired events)
   - HFP connection (connect_hfp -> hfp_connected with signal/battery)
   - SMS receive (send SMS to phone -> sms_received event)
   - SMS send (send_sms command -> phone sends SMS)
   - Incoming call (call phone -> incoming_call event)
   - Answer call (answer_call -> call_active + sco_opened)

5. **If pairing/HFP works**, move to Phase 3: SCO audio capture (BT-001.5).

### Project state

- **96/96 tests passing** (9 Swift + 56 Python + 31 Next.js)
- All code is committed and pushed to https://github.com/junainfinity/osmPhone
- `config.yaml` has the user's ElevenLabs key (local only, gitignored)
- TTS provider set to `elevenlabs` in config.yaml
- **Never commit API keys to GitHub** — config.yaml is gitignored, config.example.yaml has empty placeholders

### Remaining work (by phase)

**Phase 2 (1 item):** Real BT hardware test — pair phone, verify HFP connection
**Phase 3 (3 items):** BT-001.5 SCO audio capture/inject, SCO audio injection, PY-001.10 OpenAI Realtime API
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
