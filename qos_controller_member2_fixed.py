import json
import math
import os
import socket
import time
from os_ken.base import app_manager
from os_ken.controller import ofp_event
from os_ken.controller.handler import (
    CONFIG_DISPATCHER,
    MAIN_DISPATCHER,
    set_ev_cls
)
from os_ken.ofproto import ofproto_v1_3
from os_ken.lib import hub
from os_ken.lib.packet import packet, ethernet, ipv4, udp
from os_ken.lib.packet import ether_types


class QoSController(app_manager.OSKenApp):

    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    # Traffic settings
    HIGH_PORT = 5001
    MEDIUM_PORT = 5002
    LOW_PORT = 5003

    # FIX 1: queue ids must match the queues created in topo.py (1, 2, 3).
    # Queue 0 is the Open vSwitch default queue, so it cannot be used for "high".
    HIGH_QUEUE = 1
    MEDIUM_QUEUE = 2
    LOW_QUEUE = 3

    # FIX 2: the bottleneck is s1 port 4 (s1-eth4); senders are on s1 ports 1-3.
    BOTTLENECK_DPID = 1
    BOTTLENECK_PORT = 4
    SENDER_PORTS = (1, 2, 3)

    # FIX 3: congestion = traffic arriving at s1 does not leave the bottleneck.
    # This works for 10, 8 and 6 Mbps (a fixed 8 Mbps rate threshold does not).
    # Variants (set before starting the controller):
    #   QOS_FAST=1        poll every 0.5 s, switch ON after one bad poll
    #   QOS_SEVERE=0.15   switch ON at once when loss is above 15% (any value you give)
    FAST = os.environ.get("QOS_FAST") == "1"
    SEVERE = float(os.environ.get("QOS_SEVERE", "0") or 0)

    POLL_INTERVAL = 0.5 if FAST else 1     # FIX 4: 1 s polling (was 5 s)
    LOSS_ON = 0.05             # more than 5% not getting out
    LOSS_OFF = 0.01            # less than 1% not getting out
    MIN_MBPS = 1.0             # below this the link is treated as idle
    ON_AFTER = 1 if FAST else 2            # consecutive bad polls before priority ON
    OFF_AFTER = 6 if FAST else 3           # consecutive good polls before priority OFF

    # Receiver feedback (Member 3): off unless started with QOS_APP=1
    #   QOS_APP=1                  listen for the receiver's per-second reports
    #   QOS_APP_SOCK=/tmp/x.sock   change the socket path (default below)
    # Class 1 or 2 losing more than 2% or averaging more than 30 ms switches
    # priority ON at once; while they are still hurt, priority is not switched OFF.
    APP_ON = os.environ.get("QOS_APP") == "1"
    APP_SOCK = os.environ.get("QOS_APP_SOCK", "/tmp/qos_ctrl.sock")
    APP_LOSS = 0.02
    APP_LAT_MS = 30.0
    APP_STALE = 3.0            # reports older than this are ignored

    # Cookie identifies flow rules installed by this controller
    LEARNED_COOKIE = 0x10

    def __init__(self, *args, **kwargs):
        super(QoSController, self).__init__(*args, **kwargs)

        self.mac_to_port = {}
        self.datapaths = {}

        self.prev = None           # previous (time, in_bytes, out_bytes) of s1
        self.congested = {}
        self.hits_on = 0
        self.hits_off = 0

        self.t0 = time.time()
        # same file format as the earlier controller, so analysis keeps working
        self.csv = open("policy_log.csv", "w")
        self.csv.write("epoch,seconds,in_mbps,out_mbps,loss_ratio,priority,trigger\n")

        self.app_sock = None
        self.app_report = None       # (report time, hurt?) of the latest valid report
        self.pending_trigger = ""    # what caused the latest state change

        self.monitor_thread = hub.spawn(self._monitor)

        if self.APP_ON:
            self._open_app_socket()
            hub.spawn(self._app_listener)

        self.logger.info("QoS SDN Controller initialized")

    # -------------------------------------------------
    # MONITOR SWITCH STATISTICS
    # -------------------------------------------------

    def _monitor(self):

        while True:

            # FIX 5: only the bottleneck switch (s1) needs to be polled
            dp = self.datapaths.get(self.BOTTLENECK_DPID)

            if dp is not None:

                parser = dp.ofproto_parser
                ofp = dp.ofproto

                request = parser.OFPPortStatsRequest(
                    dp,
                    0,
                    ofp.OFPP_ANY
                )

                dp.send_msg(request)

            hub.sleep(self.POLL_INTERVAL)

    # -------------------------------------------------
    # SWITCH CONNECTION
    # -------------------------------------------------

    @set_ev_cls(
        ofp_event.EventOFPSwitchFeatures,
        CONFIG_DISPATCHER
    )
    def switch_features(self, ev):

        dp = ev.msg.datapath
        parser = dp.ofproto_parser
        ofp = dp.ofproto

        self.datapaths[dp.id] = dp
        self.mac_to_port[dp.id] = {}
        self.congested[dp.id] = False

        if dp.id == self.BOTTLENECK_DPID:
            # a reconnecting switch starts from a clean state
            self.prev = None
            self.hits_on = 0
            self.hits_off = 0
            self.pending_trigger = ""

        # Table miss rule
        match = parser.OFPMatch()

        actions = [
            parser.OFPActionOutput(
                ofp.OFPP_CONTROLLER,
                ofp.OFPCML_NO_BUFFER
            )
        ]

        instructions = [
            parser.OFPInstructionActions(
                ofp.OFPIT_APPLY_ACTIONS,
                actions
            )
        ]

        flow_mod = parser.OFPFlowMod(
            datapath=dp,
            priority=0,
            match=match,
            instructions=instructions
        )

        dp.send_msg(flow_mod)

        self.logger.info(
            "Switch %s connected successfully",
            dp.id
        )

    # -------------------------------------------------
    # UDP TRAFFIC CLASSIFICATION
    # -------------------------------------------------

    def classify_traffic(self, udp_packet):
        port = udp_packet.dst_port

        if port == self.HIGH_PORT:
            return self.HIGH_QUEUE, "HIGH"

        elif port == self.MEDIUM_PORT:
            return self.MEDIUM_QUEUE, "MEDIUM"

        elif port == self.LOW_PORT:
            return self.LOW_QUEUE, "LOW"

        return None, "NORMAL"

    # -------------------------------------------------
    # PACKET HANDLING
    # -------------------------------------------------

    @set_ev_cls(
        ofp_event.EventOFPPacketIn,
        MAIN_DISPATCHER
    )
    def packet_in(self, ev):

        msg = ev.msg
        dp = msg.datapath

        parser = dp.ofproto_parser
        ofp = dp.ofproto

        in_port = msg.match["in_port"]

        pkt = packet.Packet(msg.data)

        eth = pkt.get_protocol(ethernet.ethernet)

        if eth is None:
            return

        # Ignore LLDP packets
        if eth.ethertype == ether_types.ETH_TYPE_LLDP:
            return

        src = eth.src
        dst = eth.dst

        dpid = dp.id

        # Learn source MAC address
        self.mac_to_port[dpid][src] = in_port

        # Find destination port
        out_port = self.mac_to_port[dpid].get(
            dst,
            ofp.OFPP_FLOOD
        )

        actions = []

        ip_pkt = pkt.get_protocol(ipv4.ipv4)
        udp_pkt = pkt.get_protocol(udp.udp)

        queue_id = None
        traffic_class = "NORMAL"

        # Identify UDP traffic
        if ip_pkt is not None and udp_pkt is not None:

            queue_id, traffic_class = self.classify_traffic(
                udp_pkt
            )

            self.logger.info(
                "UDP traffic detected: %s -> %s | Class: %s",
                ip_pkt.src,
                ip_pkt.dst,
                traffic_class
            )

        # FIX 6: queues exist only on the bottleneck port (s1, port 4).
        # Set the queue only there, and only while congested.
        if (
            queue_id is not None
            and self.congested.get(dpid, False)
            and dpid == self.BOTTLENECK_DPID
            and out_port == self.BOTTLENECK_PORT
        ):

            actions.append(
                parser.OFPActionSetQueue(queue_id)
            )

            self.logger.info(
                "Applying %s priority queue: %s",
                traffic_class,
                queue_id
            )

        # Forward packet
        actions.append(
            parser.OFPActionOutput(out_port)
        )

        # Install flow when destination is known
        if out_port != ofp.OFPP_FLOOD:

            match_fields = {
                "in_port": in_port,
                "eth_dst": dst
            }

            # Match individual IPv4 UDP flows
            if ip_pkt is not None and udp_pkt is not None:

                match_fields.update({
                    "eth_type": ether_types.ETH_TYPE_IP,
                    "ip_proto": 17,
                    "ipv4_src": ip_pkt.src,
                    "ipv4_dst": ip_pkt.dst,
                    "udp_src": udp_pkt.src_port,
                    "udp_dst": udp_pkt.dst_port
                })

            match = parser.OFPMatch(**match_fields)

            instructions = [
                parser.OFPInstructionActions(
                    ofp.OFPIT_APPLY_ACTIONS,
                    actions
                )
            ]

            flow_mod = parser.OFPFlowMod(
                datapath=dp,
                cookie=self.LEARNED_COOKIE,
                priority=10,
                match=match,
                instructions=instructions,
                idle_timeout=60
            )

            dp.send_msg(flow_mod)

        # Send packet to destination
        data = None

        if msg.buffer_id == ofp.OFP_NO_BUFFER:
            data = msg.data

        packet_out = parser.OFPPacketOut(
            datapath=dp,
            buffer_id=msg.buffer_id,
            in_port=in_port,
            actions=actions,
            data=data
        )

        dp.send_msg(packet_out)

    # -------------------------------------------------
    # CONGESTION DETECTION (s1 only)
    # -------------------------------------------------

    @set_ev_cls(
        ofp_event.EventOFPPortStatsReply,
        MAIN_DISPATCHER
    )
    def port_stats_reply(self, ev):

        dp = ev.msg.datapath
        dpid = dp.id

        if dpid != self.BOTTLENECK_DPID:
            return

        stats = {s.port_no: s for s in ev.msg.body}

        now = time.time()
        in_bytes = sum(
            stats[p].rx_bytes for p in self.SENDER_PORTS if p in stats
        )
        out_bytes = (
            stats[self.BOTTLENECK_PORT].tx_bytes
            if self.BOTTLENECK_PORT in stats else 0
        )

        prev, self.prev = self.prev, (now, in_bytes, out_bytes)

        if prev is None:
            return

        dt = now - prev[0]

        if dt <= 0:
            return

        in_mbps = max(in_bytes - prev[1], 0) * 8 / dt / 1e6
        out_mbps = max(out_bytes - prev[2], 0) * 8 / dt / 1e6

        loss = (in_mbps - out_mbps) / in_mbps if in_mbps > 0 else 0.0
        loss = max(loss, 0.0)      # counter timing can give a tiny negative value

        # hysteresis: several bad polls to switch ON, several good ones to switch OFF
        if in_mbps >= self.MIN_MBPS and loss > self.LOSS_ON:
            self.hits_on += 1
            self.hits_off = 0
        elif in_mbps < self.MIN_MBPS or loss < self.LOSS_OFF:
            self.hits_off += 1
            self.hits_on = 0
        else:
            self.hits_on = 0
            self.hits_off = 0

        # severe loss: do not wait for several polls
        if (self.SEVERE > 0 and in_mbps >= self.MIN_MBPS
                and loss > self.SEVERE):
            self.hits_on = max(self.hits_on, self.ON_AFTER)

        old_state = self.congested.get(dpid, False)
        new_state = old_state

        # receiver feedback: while class 1 or 2 are still hurt, do not switch OFF
        hold = self._app_hurt(now)
        if hold:
            self.hits_off = 0

        if not old_state and self.hits_on >= self.ON_AFTER:
            new_state = True
        elif old_state and self.hits_off >= self.OFF_AFTER:
            new_state = False

        if new_state != old_state:
            self._apply_state(dp, new_state, "link")

        trigger = self.pending_trigger
        self.pending_trigger = ""
        if not trigger and hold and new_state:
            trigger = "app-hold"

        state = "ON" if new_state else "OFF"
        self.logger.info(
            "QOS | t=%5.1fs in=%5.2f out=%5.2f loss=%4.1f%% priority=%s %s",
            now - self.t0, in_mbps, out_mbps, loss * 100, state, trigger
        )
        self.csv.write("%.3f,%.1f,%.3f,%.3f,%.4f,%s,%s\n" %
                       (now, now - self.t0, in_mbps, out_mbps, loss, state, trigger))
        self.csv.flush()

    # -------------------------------------------------
    # SWITCH PRIORITY ON / OFF
    # -------------------------------------------------

    def _apply_state(self, dp, new_state, trigger):

        self.congested[dp.id] = new_state
        self.pending_trigger = trigger

        if trigger == "app":
            self.hits_off = 0

        if new_state:
            self.logger.warning(
                "CONGESTION DETECTED on switch %s -> priority ON (%s)",
                dp.id, trigger
            )
        else:
            self.logger.info(
                "CONGESTION CLEARED on switch %s -> priority OFF",
                dp.id
            )

        # Delete learned flows on s1.
        # New packets return to the controller and receive
        # the updated queue actions.

        parser = dp.ofproto_parser
        ofp = dp.ofproto

        delete_flow = parser.OFPFlowMod(
            datapath=dp,
            command=ofp.OFPFC_DELETE,
            cookie=self.LEARNED_COOKIE,
            cookie_mask=0xffffffffffffffff,
            out_port=ofp.OFPP_ANY,
            out_group=ofp.OFPG_ANY,
            match=parser.OFPMatch(),
            table_id=ofp.OFPTT_ALL
        )

        dp.send_msg(delete_flow)

    # -------------------------------------------------
    # RECEIVER FEEDBACK (Socket-SDN integration)
    # -------------------------------------------------

    def _open_app_socket(self):
        # UNIX datagram socket: Mininet hosts cannot reach 127.0.0.1 of the
        # controller, but they share the file system.
        try:
            os.unlink(self.APP_SOCK)
        except OSError:
            pass
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        sock.bind(self.APP_SOCK)
        os.chmod(self.APP_SOCK, 0o777)
        sock.setblocking(False)
        self.app_sock = sock
        self.logger.info("QOS | listening for receiver reports on %s",
                         self.APP_SOCK)

    def _app_listener(self):
        # non-blocking poll, so a quiet socket can never freeze the controller
        while True:
            self._poll_app_socket()
            hub.sleep(0.2)

    def _poll_app_socket(self):
        if self.app_sock is None:
            return
        while True:
            try:
                data = self.app_sock.recv(65535)
            except OSError:            # nothing waiting (or socket closed)
                return
            self._handle_report(data)

    def _handle_report(self, data):
        """One report: {"t": epoch, "classes": {"1": {"loss","lat_ms","n","exp"}, ...}}"""
        try:
            rep = json.loads(data.decode("utf-8"))
            t = float(rep["t"])
            if not math.isfinite(t):
                raise ValueError("bad time")
            hurt = False
            for cid in ("1", "2", "3"):
                c = rep["classes"][cid]
                loss = float(c["loss"])
                lat = float(c["lat_ms"])
                int(c["n"])
                exp = int(c["exp"])
                if not (0.0 <= loss <= 1.0 and lat >= 0.0 and exp >= 0):
                    raise ValueError("out of range")
                if cid in ("1", "2") and exp > 0 and (
                        loss > self.APP_LOSS or lat > self.APP_LAT_MS):
                    hurt = True
        except (ValueError, KeyError, TypeError, AttributeError):
            self.logger.info("QOS | receiver report ignored (malformed)")
            return

        if time.time() - t > self.APP_STALE:
            self.logger.info("QOS | receiver report ignored (stale)")
            return

        self.app_report = (t, hurt)

        dp = self.datapaths.get(self.BOTTLENECK_DPID)
        if hurt and dp is not None and not self.congested.get(dp.id, False):
            self.logger.warning(
                "QOS | receiver report: class 1/2 hurt -> priority ON at once")
            self._apply_state(dp, True, "app")

    def _app_hurt(self, now):
        r = self.app_report
        return bool(self.APP_ON and r and r[1] and now - r[0] <= self.APP_STALE)
