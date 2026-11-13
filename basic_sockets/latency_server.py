import socket, sys

# usage: python3 latency_server.py [port]       (default 5100)
# Port 5100 is not one of the three traffic classes (5001-5003), so the
# priority rules never match the probe.
port = int(sys.argv[1]) if len(sys.argv) > 1 else 5100

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind(("0.0.0.0", port))
sock.settimeout(1.0)

print(f"Latency echo server on port {port} - press Ctrl+C to stop")
try:
    while True:
        try:
            data, addr = sock.recvfrom(1024)
        except socket.timeout:
            continue
        sock.sendto(data, addr)
except KeyboardInterrupt:
    pass
sock.close()
