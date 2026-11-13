#!/bin/bash
# usage: ./save_run.sh <run_name>   e.g. ./save_run.sh static_8
name="$1"
if [ -z "$name" ]; then echo "usage: $0 <run_name>"; exit 1; fi
mkdir -p "results/$name"
for f in results.csv live_rx.csv s1.log s2.log s3.log; do
  [ -f "$f" ] && mv "$f" "results/$name/"      # moved, so old files never mix into the next run
done
# only dynamic runs have a controller log; no-priority and static runs must not get a stale one
case "$name" in
  dyn*) [ -f policy_log.csv ] && cp policy_log.csv "results/$name/" ;;
esac
echo "saved to results/$name:"; ls "results/$name"
# refresh the final tables and graphs from all saved runs
if [ -f analysis/analyze.py ]; then
  python3 analysis/analyze.py > /dev/null 2>&1 && echo "graphs updated in analysis/out/" \
    || echo "(graphs not updated: run 'python3 analysis/analyze.py' inside the osken-env)"
fi
