# Run deliberately on a writable build machine, never as a read-only audit.
lassign $argv simulator simulator_bin output
if {$simulator ni {questa vcs}} {error {Select questa or vcs}}
if {![string match 2024.2* [version -short]]} {error {Vivado 2024.2 required}}
compile_simlib -simulator $simulator -simulator_exec_path $simulator_bin -directory $output -family all -language all -library all -force
