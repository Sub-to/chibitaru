#!/usr/bin/env python3
"""qemu の monitor ソケットにコマンドを 1 つ投げる。"""
import socket
import sys
import time

sock_path, command = sys.argv[1], sys.argv[2]
s = socket.socket(socket.AF_UNIX)
s.connect(sock_path)
s.settimeout(6)
time.sleep(0.4)
try:
    s.recv(65536)          # 起動時の挨拶を捨てる
except OSError:
    pass
s.sendall((command + "\n").encode())
time.sleep(1.5)
try:
    print(s.recv(65536).decode(errors="replace").strip()[:300])
except OSError:
    pass
