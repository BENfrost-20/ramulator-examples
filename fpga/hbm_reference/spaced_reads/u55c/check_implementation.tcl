# Examine routed target design separately from OOC. Fail timing/unrouted designs.
lassign $argv checkpoint output
open_checkpoint $checkpoint
report_route_status -file $output/route-status.rpt
report_timing_summary -delay_type min_max -report_unconstrained -file $output/implementation-timing.rpt
report_drc -file $output/implementation-drc.rpt
set paths [get_timing_paths -delay_type max -max_paths 1]
if {![llength $paths]} {error {No constrained timing paths}}
if {[get_property SLACK [lindex $paths 0]] < 0} {error {Target implementation failed setup timing}}
set hold [get_timing_paths -delay_type min -max_paths 1]
if {![llength $hold] || [get_property SLACK [lindex $hold 0]] < 0} {error {Target implementation failed hold timing}}
if {[llength [get_nets -hier -filter {ROUTE_STATUS == UNROUTED}]]} {error {Unrouted nets remain}}
close_design
