#!/usr/bin/env python3
"""Compare the instrumented U55C trace with the retained AMD VCS run."""
import argparse
import json
from pathlib import Path


REFERENCE = Path(__file__).resolve().parent
KERNEL_MHZ = 100
ORIGINAL_U55C = {"core_cycles": 63, "drain_cycles": 64}
HANDSHAKES = {"AR", "R", "AW", "W", "B"}
VALID_EVENTS = {event + "_VALID" for event in HANDSHAKES}


def read_rows(path):
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    if not rows or any(row["n"] != 1 or row["repetition"] != 0 for row in rows):
        raise ValueError("Expected n=1, repetition 0: " + str(path))
    return rows


def load(result_path, trace_path, expected_events):
    result, = read_rows(result_path)
    if result["case"] != "memory_probe_single" or result["functional_status"] != "pass":
        raise ValueError("Expected a successful memory_probe_single result")
    rows = read_rows(trace_path)
    cycles = {row["event"]: row["cycles_from_start"] for row in rows}
    if set(cycles) != expected_events or len(cycles) != len(rows):
        raise ValueError("Unexpected or duplicate events: " + str(trace_path))
    return result, cycles


def intervals(c):
    write = max(c["AW"], c["W"])
    if not (c["START"] <= c["AR"] <= c["R"] <= min(c["AW"], c["W"])
            <= write <= c["B"] <= c["DONE"] < c["DRAIN"]):
        raise ValueError("Unexpected one-word probe event ordering")
    return {
        "start_to_ar": c["AR"] - c["START"],
        "ar_to_r": c["R"] - c["AR"],
        "r_to_later_aw_w": write - c["R"],
        "later_aw_w_to_b": c["B"] - write,
        "b_to_done": c["DONE"] - c["B"],
        "done_to_drain": c["DRAIN"] - c["DONE"],
    }


def compare(run):
    if (run / "input-1-0.bin").read_bytes() != bytes.fromhex("03000000"):
        raise ValueError("Board input differs from the VCS probe")
    board_result, board_events = load(run / "board-results.jsonl", run / "board-axi.jsonl",
                                      HANDSHAKES | VALID_EVENTS | {"START", "DONE", "DRAIN"})
    vcs_result, vcs_events = load(REFERENCE / "vcs-reference-results.jsonl",
                                  REFERENCE / "vcs-reference-axi.jsonl", HANDSHAKES)
    vcs_events.update(START=0, DONE=vcs_result["core_cycles"], DRAIN=vcs_result["drain_cycles"])
    if (board_events["START"], board_events["DONE"], board_events["DRAIN"]) != (
            0, board_result["core_cycles"], board_result["drain_cycles"]):
        raise ValueError("Board event timestamps disagree with the wrapper counters")
    board, vcs = intervals(board_events), intervals(vcs_events)
    delta = {key: vcs[key] - board[key] for key in vcs}
    stalls = {event: board_events[event] - board_events[event + "_VALID"]
              for event in ("AR", "R", "AW", "W", "B")}
    if any(value < 0 for value in stalls.values()):
        raise ValueError("A handshake precedes VALID")
    board_counters = {key: board_result[key] for key in ORIGINAL_U55C}
    vcs_counters = {key: vcs_result[key] for key in ORIGINAL_U55C}
    calibration = {key: board_counters[key] - ORIGINAL_U55C[key] for key in ORIGINAL_U55C}
    total = {key: vcs_counters[key] - board_counters[key] for key in ORIGINAL_U55C}
    assert sum(delta.values()) == total["drain_cycles"]
    assert sum(delta.values()) - delta["done_to_drain"] == total["core_cycles"]
    return {
        "case": "memory_probe_single", "n": 1, "kernel_clock_mhz": KERNEL_MHZ,
        "board_counters": board_counters, "vcs_counters": vcs_counters,
        "original_u55c_counters": ORIGINAL_U55C, "instrumented_minus_original": calibration,
        "instrumented_matches_original": not any(calibration.values()),
        "vcs_minus_instrumented_board_cycles": total,
        "board_intervals_cycles": board, "vcs_intervals_cycles": vcs,
        "vcs_minus_board_intervals_cycles": delta, "board_valid_to_handshake_cycles": stalls,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    args = parser.parse_args()
    print(json.dumps(compare(args.run), indent=2))


if __name__ == "__main__":
    try:
        main()
    except (OSError, KeyError, ValueError) as err:
        raise SystemExit(f"STOP: {err}")
