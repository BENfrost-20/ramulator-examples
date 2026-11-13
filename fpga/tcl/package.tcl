# vivado 2024.2 -mode batch -source package.tcl -tclargs PREPARED PART PERIOD_NS
lassign $argv prepared part period
if {[llength $argv]!=3 || ![string match 2024.2* [version -short]]} {error {Requires Vivado 2024.2 and PREPARED PART PERIOD_NS}}
set prepared [file normalize $prepared]
source $prepared/sources.tcl
create_project -force kernel $prepared/package-project -part $part
add_files $rtl_files
set_property top fpga_kernel [current_fileset]
update_compile_order -fileset sources_1
# Target-part synthesis, no unrelated-device smoke substitution.
synth_design -top fpga_kernel -part $part -mode out_of_context
create_clock -period $period -name ap_clk [get_ports ap_clk]
report_utilization -file $prepared/ooc-utilization.rpt
report_timing_summary -file $prepared/ooc-timing.rpt
write_checkpoint -force $prepared/ooc.dcp
close_design
ipx::package_project -root_dir $prepared/ip -vendor ramulator.examples -library user -taxonomy /UserIP -import_files -force
set core [ipx::current_core]
set_property name fpga_kernel $core
set_property sdx_kernel true $core
set_property sdx_kernel_type rtl $core
set_property ipi_drc {ignore_freq_hz true} $core
set_property vitis_drc {ctrl_protocol user_managed} $core
foreach bus [ipx::get_bus_interfaces -of_objects $core -filter {BUS_TYPE_VLNV =~ "*aximm*"}] {
 ipx::associate_bus_interfaces -busif [get_property NAME $bus] -clock ap_clk $core
}
set reset [ipx::get_bus_interfaces ap_rst_n -of_objects $core]
if {[llength $reset]!=1} {error {Missing inferred active-low reset}}
set control_bus [ipx::get_bus_interfaces s_axi_control -of_objects $core]
if {[llength $control_bus]!=1} {error {Missing inferred AXI-Lite interface}}
set_property name S_AXI_CONTROL $control_bus
set mm [ipx::get_memory_maps S_AXI_CONTROL -of_objects $core]
if {![llength $mm]} {set mm [ipx::add_memory_map S_AXI_CONTROL $core]}
set bus [ipx::get_bus_interfaces S_AXI_CONTROL -of_objects $core]
if {[llength $bus]!=1} {error {Missing inferred AXI-Lite control interface}}
set_property slave_memory_map_ref S_AXI_CONTROL $bus
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
package_xo -force -xo_path $prepared/fpga_kernel.xo -kernel_name fpga_kernel -ip_directory $prepared/ip -ctrl_protocol user_managed
close_project
