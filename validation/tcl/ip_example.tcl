# IP-example/model availability smoke ONLY; not benchmark performance validation.
lassign $argv part xci simulator output libraries
if {![string match 2024.2* [version -short]]} {error {Vivado 2024.2 required}}
if {$simulator ni {questa vcs}} {error {Questa/VCS required for detailed HBM}}
create_project -force ip_smoke $output/project -part $part
import_ip -files $xci
set ips [get_ips]
if {[llength $ips]!=1} {error {Supply exactly one configured controller XCI}}
generate_target all $ips
open_example_project -force -dir $output/example $ips
set_property target_simulator [expr {$simulator eq "questa" ? "Questa" : "VCS"}] [current_project]
export_simulation -simulator $simulator -of_objects [get_filesets sim_1] -directory $output/export -lib_map_path $libraries -force
close_project
