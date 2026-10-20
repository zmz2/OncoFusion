#!/usr/bin/env python3
"""Loopback relay so the demo page needs no token typing: injects the bearer on each request.

Usage: python scripts/demo_relay.py --listen 127.0.0.1:18181 --upstream 127.0.0.1:18180 \
           --token-file ~/.config/oncofusion-demo-token
The token never enters the browser, the repository, or the logs; server-side auth stays enabled.
"""
import argparse
import os
import socket
import threading

BLANK = b"\r\n\r\n"


def pump(src, dst):
    try:
        while True:
            data = src.recv(65536)
            if not data:
                break
            dst.sendall(data)
    except OSError:
        pass


def handle(client, upstream_addr, token):
    upstream = None
    try:
        # Connect fast or give up, then block on reads: a single 20 s socket timeout also applies
        # to recv, which killed every SSE stream that stayed quiet during a long model call.
        upstream = socket.create_connection(upstream_addr, timeout=20)
        upstream.settimeout(None)
        buf = b""
        while BLANK not in buf:
            chunk = client.recv(65536)
            if not chunk:
                return
            buf += chunk
        head, rest = buf.split(BLANK, 1)
        lines = head.split(b"\r\n")
        kept = [line for line in lines[1:] if not line.lower().startswith(b"connection:")]
        request = [lines[0], b"Connection: close"] + kept
        if not any(line.lower().startswith(b"authorization:") for line in request):
            request.insert(1, b"Authorization: Bearer " + token.encode())
        upstream.sendall(b"\r\n".join(request) + BLANK + rest)
        threads = [threading.Thread(target=pump, args=(client, upstream), daemon=True),
                   threading.Thread(target=pump, args=(upstream, client), daemon=True)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
    except OSError:
        pass
    finally:
        for sock in filter(None, (client, upstream)):
            try:
                sock.close()
            except OSError:
                pass


def endpoint(value):
    host, _, port = value.rpartition(":")
    return host or "127.0.0.1", int(port)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--listen", default="127.0.0.1:18181")
    parser.add_argument("--upstream", default="127.0.0.1:18180")
    parser.add_argument("--token-file", default=os.path.expanduser("~/.config/oncofusion-demo-token"))
    args = parser.parse_args()
    token = Path_read(args.token_file)
    listen, upstream = endpoint(args.listen), endpoint(args.upstream)
    server = socket.socket()
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(listen)
    server.listen(128)
    print(f"demo relay http://{listen[0]}:{listen[1]} -> {upstream[0]}:{upstream[1]}", flush=True)
    while True:
        conn, _ = server.accept()
        threading.Thread(target=handle, args=(conn, upstream, token), daemon=True).start()


def Path_read(path):
    with open(os.path.expanduser(path)) as handle:
        return handle.read().strip()


main()
