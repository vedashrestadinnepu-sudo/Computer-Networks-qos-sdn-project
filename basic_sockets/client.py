import socket, sys

# usage: python3 client.py [server IP] [port]     (default 127.0.0.1 5000)
ip   = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1"
port = int(sys.argv[2]) if len(sys.argv) > 2 else 5000

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.settimeout(2.0)               # never wait forever for the reply

message = input("Enter message: ")
sock.sendto(message.encode(), (ip, port))

try:
    data, server = sock.recvfrom(1024)
    print("Server:", data.decode())
except socket.timeout:
    print(f"No reply from {ip}:{port} within 2 s")
finally:
    sock.close()
