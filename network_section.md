# Network Section (Member 1: Network and Mininet)

> Draft based on my own runs. Rewrite it in your own words before submitting, because the viva will ask about every line.

## 1. Topology
The network is built in Mininet (`topo.py`) with four hosts and two switches:

- h1, h2 and h3 are the senders (class 1, 2 and 3). They connect to switch s1 on ports s1-eth1 to s1-eth3 (100 Mbps each).
- s1 connects to s2 over the bottleneck link, port s1-eth4.
- s2 connects to the receiver h4 (100 Mbps, 5 ms delay). The 5 ms is the baseline latency in every result.
- One remote OS-Ken controller (OpenFlow 1.3) manages both switches.

Topology modes in `topo.py`: `baseline` (no controller), `osken` (controller connection test; `ryu` is kept as an alias) and `qos` (Open vSwitch queues, used for all final experiments).

## 2. Bottleneck and queues
- The bottleneck is 10 Mbps in all the runs reported here. The `bottleneck <mbps>` command at the `mininet>` prompt changes it while running (used for 8, 6 and 5 Mbps).
- The three classes together offer about 11.5 Mbps, so a 10 Mbps bottleneck is overloaded by about 13%.
- Open vSwitch shapes port s1-eth4 with a linux-htb QoS and three queues:

| Queue | Class | UDP port | Guaranteed rate | Priority (lower is served first) |
|---|---|---|---|---|
| 1 | Class 1 (voice) | 5001 | 1 Mbps | 1 |
| 2 | Class 2 (video) | 5002 | 3.5 Mbps | 2 |
| 3 | Class 3 (bulk) | 5003 | 1 Mbps | 3 |

- Each queue may borrow spare capacity up to the bottleneck rate, highest priority first.
- Queue 0 is the Open vSwitch default queue, so the classes use queues 1, 2 and 3.
- A packet reaches a queue through an OpenFlow rule that matches UDP and the destination port, then uses `set_queue` and outputs on port 4.

## 3. Controller setup
- The controller is OS-Ken (the maintained fork of Ryu). It must be started before Mininet, because the switches drop all traffic when no controller is connected.
- OS-Ken does not ship the `simple_switch_13` example app, so a small learning switch was written (`simple_switch_13.py`). It is used for the no-priority and static runs.
- Static priority: three `priority=100` rules are added to s1 with `static_rules.sh` and stay on for the whole run.
- Dynamic priority: the controller polls s1 every second, compares traffic arriving from the senders with traffic leaving port 4, switches priority ON after 2 bad polls and OFF after 3 good polls, and logs each poll to `policy_log.csv`.

## 4. Experiments I ran (10 Mbps, heavy load)
| Run | Controller | Rules | Scenario | Saved as |
|---|---|---|---|---|
| No priority | learning switch | none | `run_heavy.txt` | nopri_10 |
| Static priority | learning switch | 3 rules on for the whole run | `run_heavy.txt` | static_10 |
| Bandwidth drop, static | learning switch | static | `fail_slow.txt` (10, 5, then 10 Mbps) | static_failslow |
| Link down, static | learning switch | static | `fail_linkdown.txt` (s1-s2 down for 5 s) | static_linkdown |
| Bandwidth drop, dynamic | dynamic controller | none added by hand | `fail_slow.txt` | dyn_failslow |
| Link down, dynamic | dynamic controller | none added by hand | `fail_linkdown.txt` | dyn_linkdown |
| Live bottleneck change, dynamic | dynamic controller | none added by hand | `live_change.txt` (10, 8, 6, then 10 Mbps) | dyn_live |

## 5. Results (loss / average latency per class)
| Run | Class 1 | Class 2 | Class 3 |
|---|---|---|---|
| No priority | 28.3% / 107 ms | 14.6% / 107 ms | 12.1% / 107 ms |
| Static priority | 0.0% / 5.2 ms | 0.0% / 5.2 ms | 18.3% / 175 ms |
| Static, bandwidth drop | 0.0% / 5.2 ms | 0.0% / 5.2 ms | 38.4% / 222 ms |
| Static, link down | 16.8% / 5.2 ms | 16.8% / 5.2 ms | 31.9% / 170 ms |
| Dynamic, bandwidth drop | 1.0% / 8.9 ms | 0.5% / 9.4 ms | 38.2% / 218 ms |
| Dynamic, link down | 17.2% / 8.3 ms | 17.0% / 8.5 ms | 31.7% / 168 ms |
| Dynamic, live bottleneck change | 0.6% / 8.0 ms | 0.4% / 8.2 ms | 36.3% / 214 ms |

## 6. Observations
- **No priority:** all three classes share one queue, so they all see the same high latency, and the most important class (voice) loses the most packets.
- **Static priority:** voice and video get no loss and only the link delay, while the bulk class absorbs the overload.
- **Bandwidth drop:** with priority on, voice and video were unaffected when the bottleneck halved to 5 Mbps, and bulk traffic recovered after the link returned to 10 Mbps.
- **Link down:** all three classes dropped to 0 Mbps for the 5 s outage and recovered about 2 s after the link came back. Voice and video lost only what was sent during the outage. Priority protects against congestion, not against a link with no capacity.
- **Dynamic vs static:** the dynamic controller switched priority on about 2 s after congestion started and off a few seconds after the traffic ended. Voice and video lost slightly more than with static priority (about 1% or less in the congestion runs) and had slightly higher latency, because packets queue during the 2 s before the rules switch on.
- **Live change:** priority stayed on while the bottleneck stepped down to 8 and 6 Mbps and back, and voice and video stayed protected.

## 7. How a run is done
1. Terminal 1: start the controller (`osken-manager simple_switch_13.py` for no-priority and static runs, `osken-manager qos_controller_member2_fixed.py` for dynamic runs).
2. Terminal 2: `sudo mn -c`, then `sudo python3 topo.py qos`, then `pingall`.
3. Static runs only, Terminal 3: `./static_rules.sh`.
4. Open `xterm h4` and run `python3 receiver.py`, then start the traffic script from the `mininet>` prompt.
5. After the senders finish and the h4 lines show zeros, press Ctrl+C in h4 for the summary.
6. Terminal 3: `./save_run.sh <name>`.

## 8. Limitations
- All results here are at a 10 Mbps bottleneck with one run per condition.
- All hosts share one VM clock, so latencies are exact but not realistic across machines.
- Classification is based on UDP port numbers, so a sender using another port would not be classified.
- The experiments use a single bottleneck and three flows.
