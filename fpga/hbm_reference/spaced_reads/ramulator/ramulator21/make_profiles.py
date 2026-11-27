"""Generate two native U55C profiles with command logging."""
from math import ceil
from pathlib import Path
import sys

import yaml
from ramulator.dram.hbm2 import HBM2


class ProfileDumper(yaml.SafeDumper):
    def represent_list(self, values):
        flow = not any(isinstance(value, (list, dict)) for value in values)
        return self.represent_sequence("tag:yaml.org,2002:seq", values, flow_style=flow)


ProfileDumper.add_representer(list, ProfileDumper.represent_list)


def main():
    template, out = map(Path, sys.argv[1:])
    base = HBM2.timing_presets["HBM2_2000Mbps"]
    period_ps = 1111
    # Retain the 2.1 2000 MT/s preset's minimum times, rounded up to the slower CK.
    HBM2.timing_presets["U55C_experimental_1800"] = {
        **{key: ceil(value * base["tCK_ps"] / period_ps)
           for key, value in base.items() if key.startswith("n")},
        "rate": 1800,
        "tCK_ps": period_ps,
    }
    for label, preset in (("bambu-2000", None), ("matched-rate-1800", "U55C_experimental_1800")):
        profile = yaml.safe_load(template.read_text())
        controllers = profile["memory_system"]["controllers"]
        assert len(controllers) == 16 and all(item["dram"]["impl"] == "HBM2" for item in controllers)
        dram = None
        if preset:
            timing = HBM2.timing_presets[preset]
            # Apply the standard's turnaround equation with the conservative
            # 1600 MT/s bin's 106 ps tDQSQ; upstream has no value for 1800.
            turnaround = timing["nCL"] + timing["nBL"] - timing["nCWL"]
            turnaround += ceil((0.3 * period_ps + 3500 + 106) / period_ps)
            dram = HBM2(org_preset="HBM2_4Gb", timing_preset=preset, nRTW=turnaround).to_config()
            assert all(item["dram"]["org"] == dram["org"] for item in controllers)
        for item in controllers:
            if dram is not None:
                item["dram"] = dram
            item["controller_plugins"] = [{"impl": "CmdTraceRecorder", "path": "commands.csv"}]
        (out / f"{label}.yaml").write_text(yaml.dump(profile, Dumper=ProfileDumper, sort_keys=False))


if __name__ == "__main__":
    main()
