#!/bin/bash
for pair in "5001 1" "5002 2" "5003 3"; do
  set -- $pair
  sudo ovs-ofctl -O OpenFlow13 add-flow s1 "priority=100,udp,tp_dst=$1,actions=set_queue:$2,output:4"
done
echo "--- rules on s1 ---"
sudo ovs-ofctl -O OpenFlow13 dump-flows s1 | grep "priority=100"
