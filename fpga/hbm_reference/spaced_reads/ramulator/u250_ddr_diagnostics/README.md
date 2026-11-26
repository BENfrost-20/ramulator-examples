# U250 DDR4 replay and diagnostics

These Ferrandi recipes refer to the existing fixed-clock U250 build
and replay binaries. Run the relevant script with Bash from its
directory. The baseline recipe checks the xclbin hash and uses the
archived HACC CSVs. The peak diagnostic varies only the simulated
refresh interval. The command diagnostic uses GDB to record commands
issued by the existing Ramulator sources with debug symbols.

[Baseline comparison](../../../PROBE.md#u250-ddr4-ramulator-comparison)
and [diagnostic evidence](../../../evidence/u250-ddr-diagnostics/README.md).
