import socket, sys, time

# usage: python3 udp_client.py [server IP] [packets] [packet size] [interval s]
# defaults: receiver h4 (10.0.0.4), 1000 packets, 1024 bytes, 0.01 s apart
ip       = sys.argv[1] if len(sys.argv) > 1 else "10.0.0.4"
count    = int(sys.argv[2]) if len(sys.argv) > 2 else 1000
size     = int(sys.argv[3]) if len(sys.argv) > 3 else 1024
interval = float(sys.argv[4]) if len(sys.argv) > 4 else 0.01
PORT = 5000

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

print(f"Sending {count} packets of {size} bytes to {ip}:{PORT} ...")
start = time.time()
for i in range(1, count + 1):
    head = f"{i}|".encode()
    packet = head + b"x" * max(size - len(head), 0)     # padded to the stated size
    sock.sendto(packet, (ip, PORT))
    time.sleep(interval)
duration = time.time() - start

sent_bytes = count * size
print("UDP traffic completed")
print("Packets sent:", count)
print("Time:", round(duration, 3), "seconds")
print("Throughput:", round(sent_bytes * 8 / duration / 1e6, 3), "Mbps")
sock.close()
