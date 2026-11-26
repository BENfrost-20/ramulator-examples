# U250 DDR4 diagnostic evidence

The [command counts](commands/command-summary.tsv) come from the four
issued-command traces in `commands/`. Their latency CSVs match the four
U250 XCI baseline CSVs byte for byte. The 2× and 4× refresh-interval
sensitivity runs are in `peaks/` with their [summary](peaks/diagnostic-summary.tsv).
These sensitivity profiles are simulations. The XCI profile records the
timing of the hardware configuration.

[Replay and diagnostic recipes](../../spaced_reads/ramulator/u250_ddr_diagnostics/README.md).
