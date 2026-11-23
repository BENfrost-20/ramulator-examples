# Vivado 2024.2: PREPARED PART PERIOD_NS [THREADS]. No device programming.
lassign $argv prepared part period threads
if {[llength $argv] ni {3 4} || ![string match 2024.2* [version -short]]} {
 error {Requires Vivado 2024.2 and PREPARED PART PERIOD_NS [THREADS]}
}
if {$threads eq {}} {set threads 8}
if {![string is integer -strict $threads] || $threads < 1 || $threads > 8} {
 error {THREADS must be an integer from 1 to 8}
}
if {![string is double -strict $period] || $period <= 0} {error {PERIOD_NS must be positive}}
set_param general.maxThreads $threads
set prepared [file normalize $prepared]
source $prepared/sources.tcl
set stamp [clock microseconds]
create_project kernel $prepared/package-project-$stamp -part $part
add_files $rtl_files
set_property top fpga_kernel [current_fileset]
# Apply the kernel clock before synthesis so it participates in optimization.
set constraint $prepared/kernel-clock.xdc
set handle [open $constraint w]
puts $handle [format {create_clock -period %.12g -name ap_clk [get_ports ap_clk]} $period]
close $handle
add_files -fileset constrs_1 $constraint
set_property USED_IN {synthesis implementation out_of_context} [get_files $constraint]
update_compile_order -fileset sources_1
synth_design -top fpga_kernel -part $part -mode out_of_context
report_utilization -file $prepared/ooc-utilization.rpt
report_timing_summary -file $prepared/ooc-timing.rpt
write_checkpoint -force $prepared/ooc.dcp
close_design

# Each packaging attempt gets fresh metadata; previous attempts remain intact.
set ip_dir $prepared/ip-$stamp
ipx::package_project -root_dir $ip_dir -vendor ramulator.examples -library user -taxonomy /UserIP -import_files
set core [ipx::current_core]
set_property name fpga_kernel $core
set_property description {Bambu RTL kernel with user-managed AXI-Lite control} $core
set_property sdx_kernel true $core
set_property sdx_kernel_type rtl $core
set_property ipi_drc {ignore_freq_hz true} $core
set_property vitis_drc {ctrl_protocol user_managed} $core
set reset [ipx::get_bus_interfaces ap_rst_n -of_objects $core]
if {[llength $reset]!=1} {error {Missing inferred active-low reset}}
set control_bus [ipx::get_bus_interfaces s_axi_control -of_objects $core]
if {[llength $control_bus]!=1} {error {Missing inferred AXI-Lite interface}}
set_property name S_AXI_CONTROL $control_bus
set control_bus [ipx::get_bus_interfaces S_AXI_CONTROL -of_objects $core]

# Rename the existing map rather than adding a case-variant duplicate.
# Equal map and bus names also give scalar kernel.xml arguments the right port.
set mm [ipx::get_memory_maps -of_objects $core]
if {![llength $mm]} {set mm [ipx::add_memory_map S_AXI_CONTROL $core]}
if {[llength $mm]!=1} {error {Expected exactly one control memory map}}
set_property name S_AXI_CONTROL $mm
set mm [ipx::get_memory_maps S_AXI_CONTROL -of_objects $core]
set_property slave_memory_map_ref S_AXI_CONTROL $control_bus

set axi_names {}
foreach bus [ipx::get_bus_interfaces -of_objects $core -filter {BUS_TYPE_VLNV =~ "*aximm*"}] {
 lappend axi_names [get_property NAME $bus]
}
set clk [ipx::get_bus_interfaces ap_clk -of_objects $core]
if {[llength $clk]!=1} {error {Missing kernel clock interface}}
set parameter [ipx::get_bus_parameters ASSOCIATED_BUSIF -of_objects $clk]
if {![llength $parameter]} {set parameter [ipx::add_bus_parameter ASSOCIATED_BUSIF $clk]}
set_property value [join $axi_names :] $parameter
# Do not fix FREQ_HZ in the IP: the Alveo clock is selected during v++ linking.
if {[llength [ipx::get_bus_parameters FREQ_HZ -of_objects $clk]]} {
 ipx::remove_bus_parameter FREQ_HZ $clk
}
set ab [ipx::get_address_blocks reg0 -of_objects $mm]
if {![llength $ab]} {set ab [ipx::add_address_block reg0 $mm]}
set_property range 256 $ab
set_property width 32 $ab
set_property usage register $ab
source $prepared/registers.tcl
ipx::create_xgui_files $core
ipx::update_checksums $core
ipx::check_integrity -kernel -xrt $core
ipx::save_core $core
set xo_attempt $prepared/fpga_kernel-$stamp.xo
package_xo -xo_path $xo_attempt -kernel_name fpga_kernel \
 -ip_directory $ip_dir -ctrl_protocol user_managed -output_kernel_xml $prepared/kernel.xml
close_project
file rename -force $xo_attempt $prepared/fpga_kernel.xo
