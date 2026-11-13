import socket, struct, time, sys

class_id = int(sys.argv[1])      # 1, 2 or 3
dest_ip  = sys.argv[2]           # the receiver's IP

CLASSES = {
    1: {"port": 5001, "size": 200,  "pps": 100},
    2: {"port": 5002, "size": 1200, "pps": 312},
    3: {"port": 5003, "size": 1400, "pps": 714},
}
cfg = CLASSES[class_id]

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)   # DGRAM = UDP
sock.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 8 * 1024 * 1024)
seq       = 0
duration = int(sys.argv[3]) if len(sys.argv) > 3 else 10
scale    = float(sys.argv[4]) if len(sys.argv) > 4 else 1.0
interval = 1.0 / (cfg["pps"] * scale)
end_time = time.time() + duration
next_send = time.time()

while time.time() < end_time:
    header = struct.pack("!BId", class_id, seq, time.time())
    packet = header + b"x" * (cfg["size"] - len(header))
    sock.sendto(packet, (dest_ip, cfg["port"]))
    seq += 1

    next_send += interval
    delay = next_send - time.time()
    if delay > 0:
        time.sleep(delay)

print(f"class {class_id}: sent {seq} packets")
