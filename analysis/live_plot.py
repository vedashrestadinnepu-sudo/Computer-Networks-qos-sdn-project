#!/usr/bin/env python3
"""
Live graph while an experiment is running (Member 3).

Reads the two files written during a run, in the project folder:
    live_rx.csv      written by receiver.py   (per-class throughput, latency, loss, every second)
    policy_log.csv   written by the controller (traffic in/out of the bottleneck, priority ON/OFF)

usage (own terminal, normal user, OS-Ken environment active, from the project folder):
    python3 analysis/live_plot.py             # live window (needs a desktop)
    python3 analysis/live_plot.py --save      # no window: rewrites live.png every second
    python3 analysis/live_plot.py --once      # draw once and exit (final snapshot of the last run)

Start it after the controller and the receiver are running, then start the traffic.
Close the window or press Ctrl+C to stop.
"""
import argparse
import csv
import os
import sys
import time

ap = argparse.ArgumentParser()
ap.add_argument("--rx", default="live_rx.csv")
ap.add_argument("--policy", default="policy_log.csv")
ap.add_argument("--every", type=float, default=1.0, help="refresh interval in seconds")
ap.add_argument("--save", nargs="?", const="live.png", default=None,
                help="write a PNG instead of opening a window (default live.png)")
ap.add_argument("--once", action="store_true", help="draw once and exit")
args = ap.parse_args()

import matplotlib
window = args.save is None and not args.once and bool(os.environ.get("DISPLAY"))
if window:
    try:
        import tkinter          # noqa: F401  (needed for the live window)
        matplotlib.use("TkAgg")
    except ImportError:
        print("No tkinter (sudo apt install python3-tk): writing live.png instead.")
        window = False
if not window:
    matplotlib.use("Agg")
import matplotlib.pyplot as plt

CLASS_NAMES = {1: "Class 1 (voice)", 2: "Class 2 (video)", 3: "Class 3 (bulk)"}


def read(path):
    try:
        with open(path, newline="") as f:
            return list(csv.DictReader(f))
    except (FileNotFoundError, OSError):
        return []


def col(rows, name):
    out = []
    for r in rows:
        try:
            out.append(float(r[name]))
        except (KeyError, ValueError, TypeError):
            out.append(float("nan"))
    return out


def draw(fig, axes):
    rx = read(args.rx)
    pol = read(args.policy)
    for ax in axes:
        ax.clear()

    starts = [float(r["epoch"]) for rows in (rx, pol) for r in rows[:1] if r.get("epoch")]
    t0 = min(starts) if starts else 0.0
    rx_t = [x - t0 for x in col(rx, "epoch")]
    pol_t = [x - t0 for x in col(pol, "epoch")]
    pol_on = [r.get("priority") == "ON" for r in pol]

    ax1, ax2, ax3 = axes
    for c in (1, 2, 3):
        ax1.plot(rx_t, col(rx, "c%d_mbps" % c), label=CLASS_NAMES[c])
        ax2.plot(rx_t, col(rx, "c%d_ms" % c), label=CLASS_NAMES[c])
    ax3.plot(pol_t, col(pol, "in_mbps"), label="Traffic in (senders)")
    ax3.plot(pol_t, col(pol, "out_mbps"), label="Traffic out (bottleneck)")

    for ax in axes:                         # green = priority ON
        for i in range(len(pol_t) - 1):
            if pol_on[i]:
                ax.axvspan(pol_t[i], pol_t[i + 1], color="green", alpha=0.12)
        ax.grid(linestyle="--", alpha=0.5)

    ax1.set_ylabel("Received (Mbps)")
    ax2.set_ylabel("Latency (ms)")
    ax3.set_ylabel("Bottleneck (Mbps)")
    ax3.set_xlabel("Time (s)")
    ax1.legend(fontsize=8, loc="upper left")
    ax3.legend(fontsize=8, loc="upper left")
    state = "waiting for data..." if not (rx or pol) else (
        "priority " + ("ON" if pol_on and pol_on[-1] else "OFF") if pol else "no controller log")
    fig.suptitle("Live QoS run, " + state + " (green = priority ON)")
    fig.tight_layout()


def main():
    fig, axes = plt.subplots(3, 1, figsize=(9, 8), sharex=True)
    if window:
        plt.ion()
        plt.show(block=False)
    try:
        while True:
            draw(fig, axes)
            if args.once:
                fig.savefig(args.save or "live.png", dpi=130)
                print("wrote", args.save or "live.png")
                return
            if window:
                if not plt.fignum_exists(fig.number):
                    return
                plt.pause(args.every)
            else:
                fig.savefig(args.save or "live.png", dpi=110)
                time.sleep(args.every)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
