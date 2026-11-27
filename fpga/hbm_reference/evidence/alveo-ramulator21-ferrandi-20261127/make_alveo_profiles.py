"""Generate native profiles for the matched Alveo fixed-address campaign."""
from copy import deepcopy
from math import ceil
from pathlib import Path
import sys

import yaml
from ramulator.dram.ddr4 import DDR4
from ramulator.dram.hbm2 import HBM2

HERE = Path(__file__).resolve().parent
PROBE = HERE.parents[1] / "spaced_reads/ramulator"
sys.path.insert(0, str(PROBE / "ramulator21"))
from make_profiles import ProfileDumper


def traced(profile):
    for controller in profile["memory_system"]["controllers"]:
        controller["controller_plugins"] = [{"impl": "CmdTraceRecorder", "path": "commands.csv"}]
    return profile


def hbm2_1800_dram():
    original = HBM2.timing_presets["HBM2_2000Mbps"]
    period_ps = 1111
    preset = "U280_experimental_1800"
    # Use the same timing conversion and turnaround assumption as the U55C comparison.
    timing = {
        **{name: ceil(value * original["tCK_ps"] / period_ps)
           for name, value in original.items() if name.startswith("n")},
        "rate": 1800,
        "tCK_ps": period_ps,
    }
    HBM2.timing_presets[preset] = timing
    turnaround = timing["nCL"] + timing["nBL"] - timing["nCWL"]
    turnaround += ceil((0.3 * period_ps + 3500 + 106) / period_ps)
    return HBM2(org_preset="HBM2_2Gb", timing_preset=preset, nRTW=turnaround).to_config()


def main():
    templates = Path(sys.argv[1])
    out = HERE / "profiles"
    native_hbm = traced(yaml.safe_load((templates / "alveo-u280.yaml").read_text()))
    hbm_match = deepcopy(native_hbm)
    dram = hbm2_1800_dram()
    for controller in hbm_match["memory_system"]["controllers"]:
        if controller["dram"]["org"] != dram["org"]:
            raise ValueError("The U280 HBM2 template and matched-rate geometry differ.")
        controller["dram"] = dram

    native_ddr = traced(yaml.safe_load((templates / "alveo-u250.yaml").read_text()))
    ddr_match = deepcopy(native_ddr)
    legacy = yaml.safe_load((PROBE / "ddr4_xci_2022_2.yaml").read_text())["MemorySystem"]["DRAM"]
    org = legacy["org"]
    timing = dict(legacy["timing"])
    preset = timing.pop("preset")
    controller = ddr_match["memory_system"]["controllers"][0]
    controller["dram"] = DDR4(org_preset=org["preset"], timing_preset=preset,
                               rank=org["rank"], channel_width=org["channel_width"], **timing).to_config()
    ddr_match["memory_system"]["controllers"] = [controller]

    profiles = {
        "u280-hbm2-matched-1800": hbm_match,
        "u280-hbm2-bambu-2000": native_hbm,
        "ddr4-xci-matched-2400": ddr_match,
        "u250-ddr4-bambu-2400": native_ddr,
    }
    for name, profile in profiles.items():
        (out / f"{name}.yaml").write_text(yaml.dump(profile, Dumper=ProfileDumper, sort_keys=False))


if __name__ == "__main__":
    main()
