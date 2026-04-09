#!/usr/bin/env python3
"""HFP connect test — sends connect_hfp and logs all events for 60s."""
import socket, json, sys, time, select

SOCK = "/tmp/osmphone.sock"
ADDR = sys.argv[1] if len(sys.argv) > 1 else "78-3f-4d-5b-8d-a1"
DURATION = int(sys.argv[2]) if len(sys.argv) > 2 else 60

s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
s.connect(SOCK)
s.setblocking(False)
print(f"[client] Connected to {SOCK}")

# Send connect command
msg = json.dumps({"id": "t1", "type": "connect_hfp", "payload": {"address": ADDR}}) + "\n"
s.sendall(msg.encode())
print(f"[client] >>> connect_hfp {ADDR}")
print(f"[client] Listening for {DURATION}s...\n")

buf = b""
start = time.time()
while time.time() - start < DURATION:
    ready, _, _ = select.select([s], [], [], 1.0)
    if ready:
        try:
            chunk = s.recv(4096)
            if not chunk:
                print("[client] Server closed connection")
                break
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                if line:
                    evt = json.loads(line)
                    elapsed = time.time() - start
                    etype = evt.get("type", "?")
                    payload = evt.get("payload", {})
                    print(f"[{elapsed:6.1f}s] <<< {etype}: {json.dumps(payload)}")
        except BlockingIOError:
            pass
        except Exception as e:
            print(f"[client] Error: {e}")
            break
    # Print heartbeat every 10s
    elapsed = time.time() - start
    if int(elapsed) % 10 == 0 and int(elapsed) > 0:
        pass  # just loop

elapsed = time.time() - start
print(f"\n[client] Done after {elapsed:.1f}s")
s.close()
