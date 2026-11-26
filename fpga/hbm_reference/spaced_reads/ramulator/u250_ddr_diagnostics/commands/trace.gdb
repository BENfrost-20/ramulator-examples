set pagination off
set confirm off
set breakpoint pending on
set disable-randomization off
python
import gdb
trace = open("ddr4-commands.tsv", "w")
trace.write("tick\tcommand\n")

class CommandTrace(gdb.Breakpoint):
    def stop(self):
        names = {0: "ACT", 1: "PRE", 2: "PREA", 3: "RD", 5: "RDA", 7: "REFab"}
        command = int(gdb.parse_and_eval("command"))
        if command in names:
            tick = int(gdb.parse_and_eval("this->m_clk"))
            trace.write(f"{tick}\t{names[command]}\n")
        return False

CommandTrace("Ramulator::DDR4::issue_command", internal=True)
end
run
python trace.close()
