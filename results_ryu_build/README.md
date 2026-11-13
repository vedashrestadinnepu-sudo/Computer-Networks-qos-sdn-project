# Results from the earlier Ryu build

Raw results of the first measurement round, taken when the controller was still Ryu
(no-priority and static-priority runs at 10, 8 and 6 Mbps, plus the two failure tests with
static priority). The static-priority rules are plain `ovs-ofctl` rules and the no-priority
runs use a learning switch, so these runs do not depend on which controller framework was used.

The final measurements at 10 Mbps, including the dynamic controller, are in `../results/`
(OS-Ken). The 8 and 6 Mbps figures in the report come from this folder.

View them with: `python3 analysis/analyze.py results_ryu_build`
(the graphs are written to `analysis/out/`, so run it before regenerating the OS-Ken graphs).
