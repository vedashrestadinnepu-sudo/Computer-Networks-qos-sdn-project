import socket, struct, time, threading, csv, json, sys

# usage:  python3 receiver.py                       measure only (as before)
#         python3 receiver.py --report unix:/tmp/qos_ctrl.sock
#                                                   also send loss and latency per
#                                                   class to the controller every second

PORTS  = [5001, 5002, 5003]
HEADER = struct.Struct("!BId")
records = []
lock    = threading.Lock()
running = True

# ---------- optional feedback to the controller ----------
report_sock = None
report_path = None
if "--report" in sys.argv:
    i = sys.argv.index("--report")
    target = sys.argv[i + 1] if i + 1 < len(sys.argv) else ""
    if target.startswith("unix:") and len(target) > 5:
        report_path = target[5:]
        # UNIX datagram socket: Mininet hosts cannot reach the controller's
        # 127.0.0.1, but they share the file system
        report_sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        report_sock.setblocking(False)
    else:
        print("--report needs unix:/path/to/socket ; reporting is off")

def send_report(report):
    if report_sock is None:
        return
    try:
        report_sock.sendto(json.dumps(report).encode(), report_path)
    except OSError:
        pass            # controller not listening: keep measuring, drop the report

def listen(port):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", port))
    sock.settimeout(0.5)
    while running:
        try:
            data, addr = sock.recvfrom(2048)
        except socket.timeout:
            continue
        recv_ts = time.time()
        if len(data) < HEADER.size:
            continue
        class_id, seq, send_ts = HEADER.unpack(data[:HEADER.size])
        with lock:
            records.append((class_id, seq, send_ts, recv_ts, len(data)))
    sock.close()

threads = [threading.Thread(target=listen, args=(p,)) for p in PORTS]
for t in threads:
    t.start()
print("Receiver listening on ports", PORTS, "- press Ctrl+C to stop")
if report_sock is not None:
    print("Reporting to the controller on", report_path)

last = 0
top_seq = {1: -1, 2: -1, 3: -1}      # highest sequence number seen per class

# one row per second for the live graph (analysis/live_plot.py)
live = open("live_rx.csv", "w")
live.write("epoch,c1_mbps,c1_ms,c1_loss,c2_mbps,c2_ms,c2_loss,c3_mbps,c3_ms,c3_loss\n")
try:
    while True:
        time.sleep(1)
        with lock:
            new = records[last:]
            last = len(records)
        line = []
        report = {"t": time.time(), "classes": {}}
        live_row = ["%.3f" % report["t"]]
        for c in (1, 2, 3):
            rows = [r for r in new if r[0] == c]
            mbps = sum(r[4] for r in rows) * 8 / 1e6
            lat  = (sum(r[3] - r[2] for r in rows) / len(rows) * 1000) if rows else 0
            line.append(f"C{c}: {mbps:5.2f} Mbps {lat:6.1f} ms")

            # loss in this second = packets the sender numbered but did not arrive
            expected = 0
            if rows:
                top = max(r[1] for r in rows)
                expected = max(top - top_seq[c], 0)
                top_seq[c] = max(top_seq[c], top)
            got = len(rows)
            loss = max(0.0, (expected - got) / expected) if expected > 0 else 0.0
            report["classes"][str(c)] = {"loss": round(min(loss, 1.0), 4),
                                         "lat_ms": round(lat, 2),
                                         "n": got, "exp": expected}
        for c in (1, 2, 3):
            r = report["classes"][str(c)]
            mbps_c = sum(x[4] for x in new if x[0] == c) * 8 / 1e6
            live_row += ["%.3f" % mbps_c, "%.1f" % r["lat_ms"], "%.4f" % r["loss"]]
        live.write(",".join(live_row) + "\n")
        live.flush()
        print(" | ".join(line))
        send_report(report)
except KeyboardInterrupt:
    pass

running = False
live.close()
for t in threads:
    t.join()

with open("results.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["class_id", "seq", "send_ts", "recv_ts", "size"])
    w.writerows(records)

print("\n--- Summary ---")
for c in (1, 2, 3):
    rows = [r for r in records if r[0] == c]
    if not rows:
        print(f"Class {c}: nothing received")
        continue
    got      = len(rows)
    expected = max(r[1] for r in rows) + 1
    loss     = (expected - got) / expected * 100
    lat      = sum(r[3] - r[2] for r in rows) / got * 1000
    print(f"Class {c}: received {got}/{expected}, loss {loss:.1f}%, avg latency {lat:.1f} ms")
