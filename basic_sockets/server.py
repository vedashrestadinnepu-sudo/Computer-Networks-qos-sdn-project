import socket, sys, time

# usage: python3 server.py [port]       (default 5000)
# Echoes text messages. Numbered packets ("<n>|padding") are counted, and a
# summary (received, lost, throughput) is printed on Ctrl+C.
port = int(sys.argv[1]) if len(sys.argv) > 1 else 5000

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind(("0.0.0.0", port))
sock.settimeout(1.0)               # so Ctrl+C always stops it cleanly

print(f"UDP server listening on port {port} - press Ctrl+C for the summary")

numbers = set()
total_bytes = 0
first = last = None
try:
    while True:
        try:
            data, addr = sock.recvfrom(65535)
        except socket.timeout:
            continue
        now = time.time()
        head = data.split(b"|", 1)[0]
        if head.isdigit():                       # numbered traffic packet
            numbers.add(int(head))
            total_bytes += len(data)
            first = first or now
            last = now
            if int(head) % 100 == 0:
                print("Received packet:", int(head))
        else:                                    # plain text: echo it back
            sock.sendto(data, addr)
            print("Echoed:", data.decode(errors="replace"))
except KeyboardInterrupt:
    pass

print("\n--- Summary ---")
if numbers:
    expected = max(numbers)
    lost = expected - len(numbers)
    span = (last - first) if last and first and last > first else 0
    rate = total_bytes * 8 / span / 1e6 if span else 0.0
    print(f"Received {len(numbers)} of {expected} packets, lost {lost} "
          f"({lost / expected * 100:.1f}%)")
    print(f"Throughput: {rate:.3f} Mbps")
else:
    print("No numbered packets received")
sock.close()
