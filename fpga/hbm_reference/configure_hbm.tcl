open_project ./project/hbm_reference.xpr
set ip [get_ips hbm_reference]

set settings [list CONFIG.USER_SAXI_00 true]
for {set i 1} {$i < 32} {incr i} {
  lappend settings [format CONFIG.USER_SAXI_%02d $i] false
}
set_property -dict $settings $ip

generate_target all $ip
open_example_project -dir ./example $ip
set_property target_simulator VCS [current_project]

puts "EXAMPLE_PROJECT: [get_property DIRECTORY [current_project]]"
close_project
