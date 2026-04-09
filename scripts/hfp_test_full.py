#!/usr/bin/env python3
"""Full HFP test — verify IPC, list devices, then connect."""
import socket, json, time, select, sys

SOCK = "/tmp/osmphone.sock"
ADDR = sys.argv[1] if len(sys.argv) > 1 else "78-3f-4d-5b-8d-a1"

s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
s.connect(SOCK)
s.setblocking(False)
print(f"[+] Connected to {SOCK}")

def send_cmd(cmd_type, payload=None):
    msg = json.dumps({"id": f"t-{int(time.time())}", "type": cmd_type, "payload": payload or {}}) + "\n"
    s.sendall(msg.encode())
    print(f"[+] >>> {cmd_type} {payload or ''}")

def read_events(duration):
    buf = b""
    start = time.time()
    events = []
    while time.time() - start < duration:
        ready, _, _ = select.select([s], [], [], 0.5)
        if ready:
            try:
                chunk = s.recv(8192)
                if not chunk:
                    print("[-] Server closed connection")
                    return events
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    if line:
                        evt = json.loads(line)
                        elapsed = time.time() - start
                        etype = evt.get("type", "?")
                        payload = evt.get("payload", {})
                        print(f"  [{elapsed:5.1f}s] <<< {etype}: {json.dumps(payload)}")
                        events.append(evt)
            except BlockingIOError:
                pass
    return events

# Step 1: Verify IPC with list_paired
print("\n=== Step 1: List paired devices (verify IPC) ===")
send_cmd("list_paired")
events = read_events(5)
if not events:
    print("[-] NO RESPONSE to list_paired! IPC may be broken.")
    s.close()
    sys.exit(1)
print(f"[+] Got {len(events)} events. IPC works.\n")

# Step 2: Connect HFP
print(f"=== Step 2: Connect HFP to {ADDR} ===")
send_cmd("connect_hfp", {"address": ADDR})
print("[+] Waiting up to 90s for HFP events (connect, reconnect, disconnect)...")
events = read_events(90)

if not events:
    print("[-] NO HFP events received in 90s!")
else:
    hfp_events = [e for e in events if e.get("type", "").startswith("hfp")]
    print(f"\n[+] Total events: {len(events)}, HFP events: {len(hfp_events)}")

print("\n=== Done ===")
s.close()
