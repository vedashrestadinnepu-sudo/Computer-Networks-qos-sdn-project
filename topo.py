#!/usr/bin/env python3
import sys, subprocess
from mininet.net import Mininet
from mininet.node import OVSSwitch, RemoteController
from mininet.link import TCLink
from mininet.cli import CLI
from mininet.log import setLogLevel, info

# usage: sudo -E python3 topo.py [baseline | osken | qos]   ('ryu' still works as an alias of 'osken')
MODE = sys.argv[1] if len(sys.argv) > 1 else "baseline"
BOTTLENECK_MBPS = 10
BOTTLENECK_IF = "s1-eth4"      # s1's port towards s2

# queue values (agree these with Member 2). rates in bits/sec, lower prio number = served first
QUEUES = {1: dict(min=1000000, prio=1),    # high   (class 1, port 5001)
          2: dict(min=3500000, prio=2),    # medium (class 2, port 5002)
          3: dict(min=1000000, prio=3)}    # low    (class 3, port 5003)

def create_queues(rate_bps):
    subprocess.run(f"ovs-vsctl clear Port {BOTTLENECK_IF} qos", shell=True)
    subprocess.run("ovs-vsctl -- --all destroy QoS -- --all destroy Queue", shell=True)
    cmd = (f"ovs-vsctl set port {BOTTLENECK_IF} qos=@q -- --id=@q create qos "
           f"type=linux-htb other-config:max-rate={rate_bps} "
           "queues:1=@q1 queues:2=@q2 queues:3=@q3")
    for qid, c in QUEUES.items():
        cmd += (f" -- --id=@q{qid} create queue other-config:min-rate={c['min']} "
                f"other-config:max-rate={rate_bps} other-config:priority={c['prio']}")
    subprocess.run(cmd, shell=True, check=True)

class QoSCLI(CLI):
    def do_bottleneck(self, line):
        "bottleneck <mbps> : change the bottleneck speed while running"
        mbps = float(line.split()[0])
        if MODE == "qos":
            create_queues(int(mbps * 1000000))
        else:
            subprocess.run(f"tc class change dev {BOTTLENECK_IF} parent 5:0 "
                           f"classid 5:1 htb rate {mbps}mbit burst 15k", shell=True)
        info(f"*** bottleneck set to {mbps} Mbps\n")

def run():
    net = Mininet(switch=OVSSwitch, link=TCLink, controller=None)
    use_ctrl = MODE in ("osken", "ryu", "qos")

    h1 = net.addHost("h1", ip="10.0.0.1/24")   # class 1 sender
    h2 = net.addHost("h2", ip="10.0.0.2/24")   # class 2 sender
    h3 = net.addHost("h3", ip="10.0.0.3/24")   # class 3 sender
    h4 = net.addHost("h4", ip="10.0.0.4/24")   # receiver

    kw = dict(protocols="OpenFlow13") if use_ctrl else dict(failMode="standalone")
    s1 = net.addSwitch("s1", **kw)
    s2 = net.addSwitch("s2", **kw)

    net.addLink(h1, s1, bw=100)                # s1-eth1
    net.addLink(h2, s1, bw=100)                # s1-eth2
    net.addLink(h3, s1, bw=100)                # s1-eth3
    # the narrow bridge (s1-eth4). In qos mode Open vSwitch shapes it, otherwise tc does
    bn = {} if MODE == "qos" else dict(bw=BOTTLENECK_MBPS, max_queue_size=100)
    net.addLink(s1, s2, **bn)
    net.addLink(s2, h4, bw=100, delay="5ms")

    if use_ctrl:
        net.addController("c0", controller=RemoteController, ip="127.0.0.1", port=6653)

    net.start()
    if MODE == "qos":
        subprocess.run(f"ip link set {BOTTLENECK_IF} txqueuelen 100", shell=True)
        create_queues(BOTTLENECK_MBPS * 1000000)
    info(f"*** mode: {MODE}\n")
    QoSCLI(net)
    net.stop()

if __name__ == "__main__":
    setLogLevel("info")
    run()

