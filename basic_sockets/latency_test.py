import socket, struct, sys, time

# usage: python3 latency_test.py [server IP] [port] [probes]
# defaults: receiver h4 (10.0.0.4), port 5100, 100 probes
ip     = sys.argv[1] if len(sys.argv) > 1 else "10.0.0.4"
port   = int(sys.argv[2]) if len(sys.argv) > 2 else 5100
probes = int(sys.argv[3]) if len(sys.argv) > 3 else 100

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.settimeout(1.0)               # a lost probe is counted, not waited for

rtts = []
lost = 0
print(f"Starting latency test to {ip}:{port} ({probes} probes)...")
for i in range(1, probes + 1):
    send = time.time()
    sock.sendto(struct.pack("!Id", i, send), (ip, port))
    try:
        data, _ = sock.recvfrom(1024)
        seq, _ts = struct.unpack("!Id", data[:12])
        if seq == i:
            rtts.append((time.time() - send) * 1000)
        else:
            lost += 1                      # reply to an older probe
    except socket.timeout:
        lost += 1
    time.sleep(0.05)
sock.close()

print("Probes sent:", probes, "| lost:", lost)
if rtts:
    rtts_sorted = sorted(rtts)
    p95 = rtts_sorted[min(len(rtts_sorted) - 1, int(0.95 * len(rtts_sorted)))]
    jitter = (sum(abs(a - b) for a, b in zip(rtts, rtts[1:])) / (len(rtts) - 1)
              if len(rtts) > 1 else 0.0)
    print(f"Round-trip time: min {min(rtts):.2f} ms | avg {sum(rtts) / len(rtts):.2f} ms | "
          f"max {max(rtts):.2f} ms | 95th percentile {p95:.2f} ms | jitter {jitter:.2f} ms")
else:
    print("No replies received")
