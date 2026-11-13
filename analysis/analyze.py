#!/usr/bin/env python3
"""
Analysis of the saved runs (Member 3).

usage (from the project folder):
    python3 analysis/analyze.py            # reads results/<run>/...
    python3 analysis/analyze.py my_results # another results folder

Each run folder holds results.csv (class_id, seq, send_ts, recv_ts, size),
s1.log, s2.log, s3.log (packets sent per class) and, for dynamic runs,
policy_log.csv. For every run it computes, per class:
    loss        = (sent - received) / sent         (sent comes from s*.log)
    latency     = average of (recv_ts - send_ts)
    throughput  = received bits / time between first and last packet
and Jain's fairness index on each class's delivered share (received / sent).

Output goes to analysis/out/: summary.csv, summary.md, and graphs
(graphs need matplotlib: pip install matplotlib).
"""
import csv
import os
import re
import sys
from collections import OrderedDict, defaultdict

RESULTS = sys.argv[1] if len(sys.argv) > 1 else "results"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
CLASSES = (1, 2, 3)
CLASS_NAMES = {1: "Class 1 (voice)", 2: "Class 2 (video)", 3: "Class 3 (bulk)"}

LABELS = OrderedDict([
    ("nopri", "No priority"),
    ("static", "Static priority"),
    ("dyn", "Dynamic (default)"),
    ("dynfast", "Dynamic (fast)"),
    ("dynsevere", "Dynamic (severe)"),
    ("dynapp", "Dynamic + receiver feedback"),
])
SCENARIOS = OrderedDict([
    ("failslow", "Bandwidth drop (10 to 5 Mbps)"),
    ("linkdown", "Link down (5 s)"),
    ("live", "Live bottleneck change"),
])


# ---------------------------------------------------------------- loading

def read_csv(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def sent_counts(folder, rows_by_class):
    """Packets each sender reports sending; falls back to highest sequence + 1."""
    sent = {}
    for c in CLASSES:
        path = os.path.join(folder, "s%d.log" % c)
        if os.path.exists(path):
            m = re.search(r"sent\s+(\d+)\s+packets", open(path).read())
            if m:
                sent[c] = int(m.group(1))
                continue
        rows = rows_by_class.get(c)
        sent[c] = (max(r[0] for r in rows) + 1) if rows else 0      # r[0] is the sequence number
    return sent


def jain(values):
    values = [v for v in values if v is not None]
    if not values or sum(v * v for v in values) == 0:
        return 0.0
    return sum(values) ** 2 / (len(values) * sum(v * v for v in values))


def load_run(folder):
    path = os.path.join(folder, "results.csv")
    if not os.path.exists(path):
        return None
    rows_by_class = defaultdict(list)
    for r in read_csv(path):
        try:
            rows_by_class[int(r["class_id"])].append(
                (int(r["seq"]), float(r["send_ts"]), float(r["recv_ts"]), int(r["size"])))
        except (KeyError, ValueError):
            continue                      # skip a damaged line
    if not rows_by_class:
        return None

    sent = sent_counts(folder, rows_by_class)
    stats, shares = {}, []
    t0 = min(r[1] for rows in rows_by_class.values() for r in rows)
    series = {}
    for c in CLASSES:
        rows = rows_by_class.get(c, [])
        got = len(rows)
        if got:
            lat = sum(r[2] - r[1] for r in rows) / got * 1000
            span = max(r[2] for r in rows) - min(r[2] for r in rows)
            tput = sum(r[3] for r in rows) * 8 / span / 1e6 if span > 0 else 0.0
        else:
            lat = tput = 0.0
        loss = max(0.0, (sent[c] - got) / sent[c] * 100) if sent[c] else 0.0
        stats[c] = dict(sent=sent[c], recv=got, loss=loss, lat=lat, tput=tput)
        shares.append(got / sent[c] if sent[c] else 0.0)
        per_sec = defaultdict(float)
        for r in rows:
            per_sec[int(r[2] - t0)] += r[3] * 8 / 1e6
        series[c] = per_sec

    policy = []
    ppath = os.path.join(folder, "policy_log.csv")
    if os.path.exists(ppath):
        try:
            policy = read_csv(ppath)
        except Exception:
            policy = []
    return dict(stats=stats, jain=jain(shares), series=series, policy=policy)


def load_all():
    runs = OrderedDict()
    if not os.path.isdir(RESULTS):
        sys.exit("No '%s' folder here. Run this from the project folder." % RESULTS)
    for name in sorted(os.listdir(RESULTS)):
        folder = os.path.join(RESULTS, name)
        if os.path.isdir(folder):
            run = load_run(folder)
            if run:
                runs[name] = run
            else:
                print("skipped %s (no usable results.csv)" % name)
    return runs


# ---------------------------------------------------------------- tables

def write_tables(runs):
    os.makedirs(OUT, exist_ok=True)
    head = ["run", "c1_sent", "c1_recv", "c1_loss_pct", "c1_lat_ms", "c1_tput_mbps",
            "c2_sent", "c2_recv", "c2_loss_pct", "c2_lat_ms", "c2_tput_mbps",
            "c3_sent", "c3_recv", "c3_loss_pct", "c3_lat_ms", "c3_tput_mbps", "jain"]
    with open(os.path.join(OUT, "summary.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(head)
        for name, run in runs.items():
            row = [name]
            for c in CLASSES:
                s = run["stats"][c]
                row += [s["sent"], s["recv"], "%.1f" % s["loss"], "%.1f" % s["lat"],
                        "%.2f" % s["tput"]]
            row.append("%.2f" % run["jain"])
            w.writerow(row)

    lines = ["| Run | Class 1 loss / latency | Class 2 loss / latency | "
             "Class 3 loss / latency | Jain's index |", "|---|---|---|---|---|"]
    for name, run in runs.items():
        cells = ["%.1f%% / %.1f ms" % (run["stats"][c]["loss"], run["stats"][c]["lat"])
                 for c in CLASSES]
        lines.append("| %s | %s | %.2f |" % (name, " | ".join(cells), run["jain"]))
    table = "\n".join(lines)
    open(os.path.join(OUT, "summary.md"), "w").write(table + "\n")

    print("\n" + table + "\n")
    print("Throughput per class (average over the packets received, Mbps):")
    for name, run in runs.items():
        print("  %-18s %s" % (name, "  ".join(
            "C%d %5.2f" % (c, run["stats"][c]["tput"]) for c in CLASSES)))


# ---------------------------------------------------------------- graphs

def heavy_groups(runs):
    """nopri_10, static_10, dyn_10 ... grouped by bottleneck speed."""
    groups = defaultdict(OrderedDict)
    for key in LABELS:
        for name, run in runs.items():
            m = re.fullmatch(r"%s_(\d+)" % key, name)
            if m:
                groups[int(m.group(1))][name] = (LABELS[key], run)
    return {b: g for b, g in groups.items() if len(g) >= 2}


def scenario_groups(runs):
    groups = defaultdict(OrderedDict)
    for key in SCENARIOS:
        for mode, label in (("static", "Static priority"), ("dyn", "Dynamic")):
            name = "%s_%s" % (mode, key)
            if name in runs:
                groups[key][name] = (label, runs[name])
    return {k: g for k, g in groups.items() if g}


def bar_figure(plt, group, title, path):
    import numpy as np
    metrics = [("loss", "Packet loss (%)"), ("lat", "Average latency (ms)"),
               ("tput", "Throughput (Mbps)")]
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.8))
    names = list(group)
    width = 0.8 / len(names)
    x = np.arange(len(CLASSES))
    for ax, (key, ylabel) in zip(axes, metrics):
        for i, name in enumerate(names):
            label, run = group[name]
            vals = [run["stats"][c][key] for c in CLASSES]
            ax.bar(x + (i - (len(names) - 1) / 2) * width, vals, width, label=label)
        ax.set_xticks(x)
        ax.set_xticklabels([CLASS_NAMES[c] for c in CLASSES], fontsize=8)
        ax.set_ylabel(ylabel)
        ax.grid(axis="y", linestyle="--", alpha=0.6)
    axes[0].legend(fontsize=8)
    fig.suptitle(title)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def timeline_figure(plt, name, run, path):
    fig, ax = plt.subplots(figsize=(9, 4))
    for c in CLASSES:
        sec = run["series"][c]
        if sec:
            xs = list(range(0, max(sec) + 1))
            ax.plot(xs, [sec.get(x, 0.0) for x in xs], label=CLASS_NAMES[c])
    ax.set_xlabel("Time since first packet (s)")
    ax.set_ylabel("Received throughput (Mbps)")
    ax.set_title("Throughput per class: %s" % name)
    ax.grid(linestyle="--", alpha=0.6)
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def policy_figure(plt, name, run, path):
    rows = run["policy"]
    try:
        xs = [float(r["seconds"]) for r in rows]
        ins = [float(r["in_mbps"]) for r in rows]
        outs = [float(r["out_mbps"]) for r in rows]
        on = [r["priority"] == "ON" for r in rows]
    except (KeyError, ValueError):
        return False
    if len(xs) < 2:
        return False
    fig, ax = plt.subplots(figsize=(9, 4))
    ax.plot(xs, ins, label="Traffic in (senders)")
    ax.plot(xs, outs, label="Traffic out (bottleneck)")
    for i in range(len(xs) - 1):
        if on[i]:
            ax.axvspan(xs[i], xs[i + 1], color="green", alpha=0.15)
    for r in rows:                                     # mark what switched priority ON
        if r.get("trigger") in ("link", "app"):
            ax.annotate("%s trigger" % r["trigger"], (float(r["seconds"]), 0),
                        fontsize=7, rotation=90, va="bottom")
    ax.set_xlabel("Controller time (s)")
    ax.set_ylabel("Mbps")
    ax.set_title("Controller view (green = priority ON): %s" % name)
    ax.grid(linestyle="--", alpha=0.6)
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return True


def write_graphs(runs):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("\nmatplotlib is not installed, so no graphs were drawn "
              "(pip install matplotlib).")
        return
    made = []
    for bottleneck, group in sorted(heavy_groups(runs).items()):
        path = os.path.join(OUT, "compare_%dmbps.png" % bottleneck)
        bar_figure(plt, group, "Heavy load, %d Mbps bottleneck" % bottleneck, path)
        made.append(path)
    for key, group in scenario_groups(runs).items():
        path = os.path.join(OUT, "scenario_%s.png" % key)
        bar_figure(plt, group, SCENARIOS[key], path)
        made.append(path)
    for name, run in runs.items():
        path = os.path.join(OUT, "timeline_%s.png" % name)
        timeline_figure(plt, name, run, path)
        made.append(path)
        if run["policy"]:
            path = os.path.join(OUT, "policy_%s.png" % name)
            if policy_figure(plt, name, run, path):
                made.append(path)
    print("\nGraphs written to %s:" % OUT)
    for p in made:
        print("  " + os.path.basename(p))


def main():
    runs = load_all()
    if not runs:
        sys.exit("No runs found in '%s'." % RESULTS)
    print("Found %d runs: %s" % (len(runs), ", ".join(runs)))
    write_tables(runs)
    write_graphs(runs)
    print("\nTables: %s and %s" % (os.path.join(OUT, "summary.csv"),
                                   os.path.join(OUT, "summary.md")))


if __name__ == "__main__":
    main()
