#!/usr/bin/env python3
"""Quick test client for osm-bt. Connects to the Unix socket and sends commands."""
import socket
import json
import sys
import time
import threading

SOCK_PATH = "/tmp/osmphone.sock"
cmd_id = 0

def send(sock, cmd_type, payload=None):
    global cmd_id
    cmd_id += 1
    msg = {"id": f"test-{cmd_id}", "type": cmd_type, "payload": payload or {}}
    data = json.dumps(msg) + "\n"
    sock.sendall(data.encode())
    print(f">>> {cmd_type} {payload or ''}")

def reader(sock):
    buf = b""
    while True:
        try:
            chunk = sock.recv(4096)
            if not chunk:
                print("--- Connection closed ---")
                break
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                evt = json.loads(line)
                etype = evt.get("type", "?")
                payload = evt.get("payload", {})
                print(f"<<< {etype}: {json.dumps(payload, indent=2)}")
        except Exception as e:
            print(f"Reader error: {e}")
            break

def main():
    # Wait for socket
    for i in range(10):
        if __import__("os").path.exists(SOCK_PATH):
            break
        print(f"Waiting for socket... ({i+1}/10)")
        time.sleep(1)

    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.connect(SOCK_PATH)
    print(f"Connected to {SOCK_PATH}")

    t = threading.Thread(target=reader, args=(sock,), daemon=True)
    t.start()

    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        if cmd == "scan":
            send(sock, "scan_start")
            time.sleep(12)
        elif cmd == "pair":
            addr = sys.argv[2] if len(sys.argv) > 2 else input("Address: ")
            send(sock, "pair", {"address": addr})
            time.sleep(10)
        elif cmd == "connect":
            addr = sys.argv[2] if len(sys.argv) > 2 else input("Address: ")
            send(sock, "connect_hfp", {"address": addr})
            time.sleep(60)  # Wait long enough for reconnect attempts
        elif cmd == "list":
            send(sock, "list_paired")
            time.sleep(3)
        elif cmd == "disconnect":
            send(sock, "disconnect_hfp")
            time.sleep(2)
        else:
            print(f"Unknown command: {cmd}")
            print("Usage: bt_test_client.py [scan|pair <addr>|connect <addr>|list|disconnect]")
    else:
        # Interactive mode
        print("\nCommands: scan, list, pair <addr>, connect <addr>, disconnect, quit")
        while True:
            try:
                line = input("\n> ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not line:
                continue
            parts = line.split()
            cmd = parts[0]
            if cmd == "quit":
                break
            elif cmd == "scan":
                send(sock, "scan_start")
            elif cmd == "list":
                send(sock, "list_paired")
            elif cmd == "pair" and len(parts) > 1:
                send(sock, "pair", {"address": parts[1]})
            elif cmd == "connect" and len(parts) > 1:
                send(sock, "connect_hfp", {"address": parts[1]})
            elif cmd == "disconnect":
                send(sock, "disconnect_hfp")
            else:
                print(f"Unknown: {line}")

    sock.close()

if __name__ == "__main__":
    main()
