# U280 DDR4 row-locality simulation evidence

These 12 CSVs are from the local Verilator and Ramulator smoke run at
anchor `0x1000500000`. Each case and refresh offset has 1,000 reads.
See the [probe](../../spaced_reads/u280_ddr_controller/README.md) for the
stimulus, model provenance and Ferrandi/HACC commands, and the
[summary](../../spaced_reads/u280_ddr_controller/local-smoke.tsv) for
quantiles and DRAM command counts. HACC hardware acquisition is pending.
