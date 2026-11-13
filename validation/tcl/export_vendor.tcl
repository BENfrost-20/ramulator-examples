# Support code for a reviewed, already integrated memory-reference project.
# This does NOT pretend the unmodified vendor traffic-generator example is DUT validation.
lassign $argv project simulator libraries output top runtime prepared logger
if {![string match 2024.2* [version -short]]} {error {Vivado 2024.2 required}}
if {$simulator ni {questa vcs}} {error {Detailed HBM requires Questa/VCS}}
open_project $project
set_property target_simulator [expr {$simulator eq "questa" ? "Questa" : "VCS"}] [current_project]
# The workload must contain the exact hardware integration copy.
source $prepared/sources.tcl
foreach rtl $rtl_files {
 if {![llength [get_files -all -quiet $rtl]]} {error "Prepared workload RTL not present in project: $rtl"}
}
add_files -fileset sim_1 [list $logger $output/bind_monitors.sv]
set_property top $top [get_filesets sim_1]
set_property xsim.simulate.runtime $runtime [get_filesets sim_1]
set_property ${simulator}.simulate.runtime $runtime [get_filesets sim_1]
# Licensed encrypted libraries must have been built for this exact release.
set_property compxlib.${simulator}_compiled_library_dir $libraries [current_project]
update_compile_order -fileset sim_1
report_ip_status -file $output/ip-status.rpt
# Supported output products and simulator scripts retain all IP init/config files.
generate_target simulation [get_ips]
export_simulation -simulator $simulator -of_objects [get_filesets sim_1] -directory $output/export -lib_map_path $libraries -force
close_project
