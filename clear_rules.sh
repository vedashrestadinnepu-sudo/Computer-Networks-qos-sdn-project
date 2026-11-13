#!/bin/bash
# Remove the three static priority rules from s1
for p in 5001 5002 5003; do
  sudo ovs-ofctl -O OpenFlow13 --strict del-flows s1 "priority=100,udp,tp_dst=$p"
done
echo "rules left at priority 100: $(sudo ovs-ofctl -O OpenFlow13 dump-flows s1 | grep -c 'priority=100')"
