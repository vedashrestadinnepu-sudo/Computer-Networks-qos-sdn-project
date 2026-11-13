from os_ken.base import app_manager
from os_ken.controller import ofp_event
from os_ken.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER, DEAD_DISPATCHER, set_ev_cls
from os_ken.ofproto import ofproto_v1_3
from os_ken.lib import hub
from os_ken.lib.packet import packet, ethernet, ether_types
import time

# OS-Ken's base class (falls back to the old name if needed)
BaseApp = getattr(app_manager, "OSKenApp", None) or app_manager.RyuApp

CLASS_QUEUE = {5001: 1, 5002: 2, 5003: 3}   # UDP port -> queue
BOTTLENECK_SWITCH = 1                        # s1
BOTTLENECK_PORT = 4                          # s1-eth4
SENDER_PORTS = (1, 2, 3)                     # s1 ports facing h1, h2, h3
PRIORITY = 100
POLL_SECONDS = 0.5
LOSS_ON = 0.05
LOSS_OFF = 0.01
MIN_MBPS = 1.0
ON_AFTER = 1
OFF_AFTER = 6


class QoSController(BaseApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super(QoSController, self).__init__(*args, **kwargs)
        self.mac_to_port = {}
        self.s1 = None
        self.prev = None
        self.priority_on = False
        self.hits_on = 0
        self.hits_off = 0
        self.t0 = time.time()
        self.csv = open("policy_log.csv", "w")
        self.csv.write("epoch,seconds,in_mbps,out_mbps,loss_ratio,priority\n")
        hub.spawn(self._monitor)

    # ---------------- basic learning switch (replaces simple_switch_13) ----------------
    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def _switch_features(self, ev):
        dp = ev.msg.datapath
        ofp = dp.ofproto
        parser = dp.ofproto_parser
        match = parser.OFPMatch()
        actions = [parser.OFPActionOutput(ofp.OFPP_CONTROLLER, ofp.OFPCML_NO_BUFFER)]
        self._add_flow(dp, 0, match, actions)          # table-miss: send to controller

    def _add_flow(self, dp, priority, match, actions, buffer_id=None):
        ofp = dp.ofproto
        parser = dp.ofproto_parser
        inst = [parser.OFPInstructionActions(ofp.OFPIT_APPLY_ACTIONS, actions)]
        if buffer_id:
            mod = parser.OFPFlowMod(datapath=dp, buffer_id=buffer_id,
                                    priority=priority, match=match, instructions=inst)
        else:
            mod = parser.OFPFlowMod(datapath=dp, priority=priority,
                                    match=match, instructions=inst)
        dp.send_msg(mod)

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def _packet_in(self, ev):
        msg = ev.msg
        dp = msg.datapath
        ofp = dp.ofproto
        parser = dp.ofproto_parser
        in_port = msg.match["in_port"]

        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocols(ethernet.ethernet)[0]
        if eth.ethertype == ether_types.ETH_TYPE_LLDP:
            return
        dst, src = eth.dst, eth.src

        table = self.mac_to_port.setdefault(dp.id, {})
        table[src] = in_port
        out_port = table.get(dst, ofp.OFPP_FLOOD)
        actions = [parser.OFPActionOutput(out_port)]

        if out_port != ofp.OFPP_FLOOD:
            match = parser.OFPMatch(in_port=in_port, eth_dst=dst, eth_src=src)
            if msg.buffer_id != ofp.OFP_NO_BUFFER:
                self._add_flow(dp, 1, match, actions, msg.buffer_id)
                return
            self._add_flow(dp, 1, match, actions)

        data = msg.data if msg.buffer_id == ofp.OFP_NO_BUFFER else None
        out = parser.OFPPacketOut(datapath=dp, buffer_id=msg.buffer_id,
                                  in_port=in_port, actions=actions, data=data)
        dp.send_msg(out)
    # ------------------------------------------------------------------------------

    @set_ev_cls(ofp_event.EventOFPStateChange, [MAIN_DISPATCHER, DEAD_DISPATCHER])
    def _state_change(self, ev):
        dp = ev.datapath
        if ev.state == MAIN_DISPATCHER and dp.id == BOTTLENECK_SWITCH:
            self.s1 = dp
            self.prev = None
            self.priority_on = False
            self.logger.info("QOS | s1 connected")
        elif ev.state == DEAD_DISPATCHER and self.s1 is dp:
            self.s1 = None
            self.logger.info("QOS | s1 disconnected")

    def _monitor(self):
        while True:
            dp = self.s1
            if dp is not None:
                parser = dp.ofproto_parser
                dp.send_msg(parser.OFPPortStatsRequest(dp, 0, dp.ofproto.OFPP_ANY))
            hub.sleep(POLL_SECONDS)

    @set_ev_cls(ofp_event.EventOFPPortStatsReply, MAIN_DISPATCHER)
    def _port_stats_reply(self, ev):
        dp = ev.msg.datapath
        if dp.id != BOTTLENECK_SWITCH:
            return
        stats = {s.port_no: s for s in ev.msg.body}
        cur = {"t": time.time(),
               "in": sum(stats[p].rx_bytes for p in SENDER_PORTS if p in stats),
               "out": stats[BOTTLENECK_PORT].tx_bytes if BOTTLENECK_PORT in stats else 0}
        prev, self.prev = self.prev, cur
        if prev is None:
            return
        dt = cur["t"] - prev["t"]
        if dt <= 0:
            return
        in_mbps = (cur["in"] - prev["in"]) * 8 / dt / 1e6
        out_mbps = (cur["out"] - prev["out"]) * 8 / dt / 1e6
        self._decide(dp, in_mbps, out_mbps)

    def _decide(self, dp, in_mbps, out_mbps):
        loss = (in_mbps - out_mbps) / in_mbps if in_mbps > 0 else 0.0
        if in_mbps >= MIN_MBPS and loss > LOSS_ON:
            self.hits_on += 1
            self.hits_off = 0
        elif in_mbps < MIN_MBPS or loss < LOSS_OFF:
            self.hits_off += 1
            self.hits_on = 0
        else:
            self.hits_on = 0
            self.hits_off = 0

        if not self.priority_on and self.hits_on >= ON_AFTER:
            self._set_priority(dp, True)
        elif self.priority_on and self.hits_off >= OFF_AFTER:
            self._set_priority(dp, False)

        now = time.time()
        state = "ON" if self.priority_on else "OFF"
        self.logger.info("QOS | t=%5.1fs in=%5.2f out=%5.2f loss=%4.1f%% priority=%s",
                         now - self.t0, in_mbps, out_mbps, loss * 100, state)
        self.csv.write("%.3f,%.1f,%.3f,%.3f,%.4f,%s\n" %
                       (now, now - self.t0, in_mbps, out_mbps, loss, state))
        self.csv.flush()

    def _set_priority(self, dp, on):
        ofp = dp.ofproto
        parser = dp.ofproto_parser
        for udp_port, queue in CLASS_QUEUE.items():
            match = parser.OFPMatch(eth_type=0x0800, ip_proto=17, udp_dst=udp_port)
            if on:
                actions = [parser.OFPActionSetQueue(queue),
                           parser.OFPActionOutput(BOTTLENECK_PORT)]
                inst = [parser.OFPInstructionActions(ofp.OFPIT_APPLY_ACTIONS, actions)]
                mod = parser.OFPFlowMod(datapath=dp, priority=PRIORITY,
                                        match=match, instructions=inst)
            else:
                mod = parser.OFPFlowMod(datapath=dp, command=ofp.OFPFC_DELETE_STRICT,
                                        priority=PRIORITY, match=match,
                                        out_port=ofp.OFPP_ANY, out_group=ofp.OFPG_ANY)
            dp.send_msg(mod)
        self.priority_on = on
        self.logger.info("QOS *** priority %s", "ON" if on else "OFF")
