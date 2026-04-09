#!/usr/bin/env python3
"""Full flow: scan → pair → connect HFP. Watches events throughout."""
import socket, json, time, select, sys

SOCK = "/tmp/osmphone.sock"
TARGET = sys.argv[1] if len(sys.argv) > 1 else None

s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
s.connect(SOCK)
s.setblocking(False)
print(f"[+] Connected to {SOCK}\n")

def send_cmd(cmd_type, payload=None):
    msg = json.dumps({"id": f"t-{int(time.time()*1000)}", "type": cmd_type, "payload": payload or {}}) + "\n"
    s.sendall(msg.encode())
    print(f">>> {cmd_type} {json.dumps(payload) if payload else ''}")

def read_events(duration, stop_on=None):
    buf = b""
    start = time.time()
    events = []
    while time.time() - start < duration:
        ready, _, _ = select.select([s], [], [], 0.5)
        if ready:
            try:
                chunk = s.recv(8192)
                if not chunk:
                    print("[-] Server closed")
                    return events
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    if line:
                        evt = json.loads(line)
                        elapsed = time.time() - start
                        etype = evt.get("type", "?")
                        payload = evt.get("payload", {})
                        ts = f"[{elapsed:5.1f}s]"
                        if etype == "device_found":
                            name = payload.get("name", "?")
                            addr = payload.get("address", "?")
                            rssi = payload.get("rssi", 0)
                            print(f"  {ts} FOUND: {name} ({addr}) RSSI={rssi}")
                        else:
                            print(f"  {ts} <<< {etype}: {json.dumps(payload)}")
                        events.append(evt)
                        if stop_on and etype == stop_on:
                            return events
            except BlockingIOError:
                pass
    return events

# Step 1: Scan for devices
print("=== STEP 1: Scanning for devices (15s) ===")
send_cmd("scan_start")
events = read_events(15, stop_on="scan_complete")

# Find iPhone
iphone = None
for e in events:
    if e.get("type") == "device_found":
        p = e.get("payload", {})
        name = p.get("name", "")
        addr = p.get("address", "")
        if TARGET and addr == TARGET:
            iphone = p
        elif "iPhone" in name:
            iphone = p

if not iphone:
    print("[-] iPhone not found in scan!")
    if TARGET:
        print(f"    Using target address anyway: {TARGET}")
        iphone = {"address": TARGET, "name": "target"}
    else:
        s.close()
        sys.exit(1)

addr = iphone["address"]
print(f"\n[+] Target: {iphone['name']} ({addr})\n")

# Step 2: Pair
print(f"=== STEP 2: Pairing with {addr} ===")
print("    >>> Check your iPhone for a pairing prompt! <<<")
send_cmd("pair", {"address": addr})
events = read_events(30, stop_on="paired")

paired = any(e.get("type") == "paired" for e in events)
if not paired:
    pair_failed = [e for e in events if e.get("type") == "pair_failed"]
    if pair_failed:
        print(f"[-] Pairing failed: {pair_failed[0].get('payload', {})}")
    else:
        print("[-] Pairing timed out (30s). Check iPhone for prompt.")
    # Try connecting anyway in case already paired
    print("[*] Attempting HFP connect anyway...\n")

# Step 3: Connect HFP
print(f"=== STEP 3: Connecting HFP to {addr} ===")
send_cmd("connect_hfp", {"address": addr})
print("    Waiting up to 90s (with auto-reconnect)...\n")
events = read_events(90)

hfp_connected = any(e.get("type") == "hfp_connected" for e in events)
hfp_disconnected = [e for e in events if e.get("type") == "hfp_disconnected"]
reconnecting = [e for e in events if e.get("type") == "hfp_reconnecting"]

print(f"\n=== RESULTS ===")
print(f"  HFP Connected: {'YES' if hfp_connected else 'NO'}")
print(f"  Disconnects: {len(hfp_disconnected)}")
print(f"  Reconnect attempts: {len(reconnecting)}")
if hfp_disconnected:
    for d in hfp_disconnected:
        print(f"  Disconnect reason: {d.get('payload', {}).get('reason', '?')}")

s.close()
