# QoS Traffic Management System

Three classes of UDP traffic (voice-like, video-like, bulk) cross one narrow link in
Mininet. Open vSwitch priority queues plus an OS-Ken (OpenFlow 1.3) controller protect the
important classes during congestion. The controller switches priority on and off by itself.

## Requirements
Ubuntu VM, Mininet, Open vSwitch, Python 3 and a virtual environment with:
```
python3 -m venv ~/osken-env
source ~/osken-env/bin/activate
pip install -r requirements.txt        # os-ken, matplotlib
```
Once per boot: `sudo sysctl -w net.core.wmem_max=16777216`

## Network
```
h1 (class 1) --\
h2 (class 2) ---- s1 ==== bottleneck 10 Mbps (s1-eth4) ==== s2 ---- h4 (receiver)
h3 (class 3) --/        \__ OS-Ken controller (OpenFlow 1.3, port 6653) __/
```
| Class | Behaves like | UDP port | Packet size | Rate | Priority | Queue |
|---|---|---|---|---|---|---|
| 1 | Voice | 5001 | 200 B | 0.16 Mbps | High | 1 |
| 2 | Video | 5002 | 1200 B | 3 Mbps | Medium | 2 |
| 3 | Bulk | 5003 | 1400 B | 8 Mbps | Low | 3 |

## Files
| File | Purpose | Owner |
|---|---|---|
| `topo.py` | Mininet topology, modes `baseline`, `osken` (controller test; `ryu` is kept as an alias), `qos`; `bottleneck <mbps>` command | Member 1 |
| `run_heavy.txt` | Starts the three senders together for 30 s | Member 1 |
| `fail_slow.txt`, `fail_linkdown.txt`, `live_change.txt` | Bandwidth drop, link down, live speed change | Member 1 |
| `static_rules.sh`, `clear_rules.sh`, `save_run.sh` | Add or remove the static priority rules, save a finished run | Member 1 |
| `simple_switch_13.py` | Plain learning switch (no-priority and static runs) | Member 1 |
| `qos_controller_member2_fixed.py` | Dynamic controller: congestion detection, priority on/off, receiver feedback | Member 2 |
| `qos_controller.py`, `qos_controller_fast.py` | Earlier controller versions, kept for reference | Member 2 |
| `sender.py` | UDP sender: `python3 sender.py <class 1-3> <dest IP> <seconds> <speed scale>` | Member 3 |
| `receiver.py` | Per-class throughput, latency and loss; saves `results.csv`; optional `--report` to the controller | Member 3 |
| `basic_sockets/` | UDP echo client and server, numbered-packet client, round-trip latency test | Member 3 |
| `analysis/analyze.py` | Tables, Jain's fairness index and graphs from the saved runs | Member 3 |
| `analysis/live_plot.py` | Live graph while a run is in progress (reads `live_rx.csv` and `policy_log.csv`) | Member 3 |
| `results/` | One folder per saved run (OS-Ken, 10 Mbps) | all |
| `results_ryu_build/` | Raw results of the earlier Ryu round (no priority and static at 10, 8, 6 Mbps) | all |
| `report/` | Project report (Markdown and PDF) and its figures | all |

## Run one experiment
Use three terminals (T1 controller, T2 Mininet, T3 helpers) and an xterm on h4.

1. **T1:** `source ~/osken-env/bin/activate`, then one of
   - no priority or static priority: `osken-manager simple_switch_13.py`
   - dynamic priority: `osken-manager qos_controller_member2_fixed.py`
   - dynamic with receiver feedback: `QOS_APP=1 osken-manager qos_controller_member2_fixed.py`
   - faster / severe variants: prefix `QOS_FAST=1` or `QOS_SEVERE=0.15`

   Start the controller first: switches drop all traffic when none is connected.
2. **T2:** `sudo mn -c`, then `sudo python3 topo.py qos`
3. **T2** at `mininet>`: `pingall` (0% dropped), then `bottleneck 10` (or 8, or 6)
4. **T3**, static priority only: `./static_rules.sh`
5. **T2:** `xterm h4`. In the h4 window: `python3 receiver.py`
   (with feedback: `python3 receiver.py --report unix:/tmp/qos_ctrl.sock`)
6. **T2:** `source run_heavy.txt` (or `fail_slow.txt`, `fail_linkdown.txt`, `live_change.txt`)
7. Wait until the h4 lines show zeros after the traffic, then Ctrl+C in h4 for the summary.
   Ctrl+C in T1 once `priority OFF` has appeared (dynamic runs).
8. **T3:** `./save_run.sh <name>`

### Run names used for the saved results
`nopri_<mbps>`, `static_<mbps>`, `dyn_<mbps>`, `dynfast_<mbps>`, `dynsevere_<mbps>`,
`dynapp_<mbps>` (receiver feedback on), and for the scenarios `static_failslow`,
`static_linkdown`, `dyn_failslow`, `dyn_linkdown`, `dyn_live`.
`analysis/analyze.py` groups the runs by these names, so keep them.

## Dynamic controller
- Every second it reads s1's port counters: traffic arriving from the senders (ports 1-3)
  against traffic leaving the bottleneck (port 4).
- More than 5% not getting out for 2 polls in a row switches priority ON; less than 1% (or
  almost no traffic) for 3 polls in a row switches it OFF. `QOS_FAST=1` polls every 0.5 s and
  switches ON after one bad poll; `QOS_SEVERE=0.15` switches ON at once above 15% loss.
- Priority = three OpenFlow rules (UDP destination port to `set_queue` 1, 2, 3) on s1's
  bottleneck port.
- Every poll is appended to `policy_log.csv`
  (`epoch,seconds,in_mbps,out_mbps,loss_ratio,priority,trigger`).
  `trigger` shows what caused a change: `link` (counters), `app` (receiver report) or
  `app-hold` (receiver report kept priority on).

## Receiver feedback (receiver and controller working together)
`receiver.py --report unix:/tmp/qos_ctrl.sock` sends one small JSON datagram per second:
```
{"t": 1794372731.6, "classes": {"1": {"loss": 0.0, "lat_ms": 5.2, "n": 100, "exp": 100}, "2": {...}, "3": {...}}}
```
With `QOS_APP=1` the controller listens on that socket:
- class 1 or 2 losing more than 2% or averaging more than 30 ms switches priority ON at once;
- while those classes are still hurt, priority is not switched OFF;
- reports older than 3 s and malformed reports are ignored;
- if the controller is not listening, the receiver keeps measuring and drops the reports.

A UNIX datagram socket is used because Mininet hosts have their own network namespace and
cannot reach the controller's 127.0.0.1, but they share the file system.

## Basic socket tools (`basic_sockets/`)
Run the servers in the h4 window (`mininet> xterm h4`, then run them from the project folder)
and the clients from the `mininet>` prompt:
```
h4 window:   python3 basic_sockets/server.py                   # echo + packet summary on Ctrl+C
mininet>     h1 python3 basic_sockets/udp_client.py            # 1000 numbered packets to 10.0.0.4
mininet>     h1 python3 basic_sockets/client.py 10.0.0.4 5000  # type a message, the server echoes it

h4 window:   python3 basic_sockets/latency_server.py           # echo server on port 5100
mininet>     h1 python3 basic_sockets/latency_test.py          # round-trip time to 10.0.0.4:5100
```
The latency probe uses port 5100, which is not one of the three traffic classes, so the
priority rules do not match it. Stop a server with Ctrl+C in its window.

## Analysis
```
python3 analysis/analyze.py                  # tables and graphs from results/ -> analysis/out/
python3 analysis/live_plot.py                # live graph during a run (own terminal, see below)
```
`./save_run.sh <name>` also refreshes the graphs in `analysis/out/` after every saved run.

**Live graph:** start the controller and the receiver, then in another terminal (OS-Ken
environment active, project folder) run `python3 analysis/live_plot.py` and start the traffic.
It shows per-class throughput and latency from `live_rx.csv` (written by `receiver.py`) and the
controller's traffic in/out with priority ON shaded green, from `policy_log.csv`. Without a
desktop window use `python3 analysis/live_plot.py --save` (rewrites `live.png` every second);
`--once` draws a final snapshot.
Jain's fairness index is computed on each class's delivered share (received / sent), so
classes that offer different rates are compared fairly.

## Troubleshooting
- `pingall` shows 100% loss: the controller is not running. Start it first, then Mininet.
- No `Switch ... connected` lines or dynamic runs never switch ON: restart the controller,
  then `sudo mn -c`, then Mininet.
- `Permission denied` on the `.sh` files: `chmod +x *.sh`.
- Summary shows far fewer packets than the senders sent: Ctrl+C in h4 was pressed too early.
- `ImportError ... simple_switch_13 from os_ken.app`: OS-Ken has no example apps, use the
  `simple_switch_13.py` in this folder.

## Report
The full project report is in `report/` (`QoS_Traffic_Management_System_Report.md` and the PDF).
It covers the architecture, the OS-Ken controller, the measurements and the comparison.
The project started with a Ryu controller and was moved to OS-Ken: the priority logic is the
same, only the package name (`ryu` to `os_ken`) and the launcher (`osken-manager`) change.

## Team
- Member 1: network and Mininet
- Member 2: SDN controller and QoS
- Member 3: UDP sockets, testing and analysis
