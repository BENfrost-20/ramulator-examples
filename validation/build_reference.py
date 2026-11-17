"""Generate a standalone memory_probe_single -> AMD HBM reference system.

No preassembled project is needed. A reviewed one-port HBM XCI supplies the
vendor configuration; this generator supplies DUT, muxed loader/checker, AXI4
width/CDC/AXI3 conversion, clocks/resets, readiness and passive measurements.
Emission is tool-independent. --build deliberately invokes vendor tools on an
authorized build machine; it was NOT run on the read-only server.
"""
import argparse
import json
import math
from pathlib import Path
import re
import shutil
import sys

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from fpga.prepare import AXI,CONTROL,digest,ports
from fpga.run import run,tool,write,board


def tcl_quote(value):
    s=str(value)
    if any(c in s for c in '{}\n\r'):raise ValueError('Unsupported Tcl configuration character')
    return '{'+s+'}'


def control_tasks(text):
    """Extract the two owned AXI-Lite tasks, preserving their lifetime qualifier."""
    blocks=[]
    for name in ('wr','rd'):
        pattern=(r'^[ \t]*task[ \t]+(?:automatic[ \t]+)?'+name+
                 r'[ \t]*\(.*?^[ \t]*endtask\b[^\n]*')
        matches=re.findall(pattern,text,flags=re.M|re.S)
        if len(matches)!=1:
            raise ValueError('Expected exactly one owned control task '+name+'; inspect control_tb.sv')
        blocks.append(matches[0])
    return '\n\n'.join(blocks)


def validate(info,c):
    if info['case']!='memory_probe_single' or info['axi_ports']!=['m_axi_0']:
        raise ValueError('Concrete vendor slice implements memory_probe_single only; no case substitution')
    if c['backend']!='amd_hbm_axi3':raise ValueError('Vendor backend not implemented: '+c['backend'])
    _,profile=board(c['board'])
    if profile['memory_kind']!='HBM':raise ValueError('HBM backend cannot serve a DDR/non-AMD board')
    for name in ('kernel_mhz','memory_mhz','apb_mhz','reference_mhz','capacity_bytes','physical_base','native_addr_width','native_id_width'):
        if isinstance(c.get(name),bool) or not isinstance(c.get(name),(int,float)) or not math.isfinite(c[name]) or c[name]<=0:raise ValueError('Set verified model field '+name)
    for name in ('capacity_bytes','physical_base','native_addr_width','native_id_width','native_data_width','reset_cycles','max_kernel_cycles'):
        if not isinstance(c.get(name),int) or isinstance(c[name],bool) or c[name]<=0:raise ValueError('Positive integer model field required: '+name)
    if c['native_data_width']!=256:raise ValueError('This HBM backend requires its verified 256-bit native interface')
    if info.get('generation') and info['generation']['board']!=c['board']:raise ValueError('Model board differs from generated DUT')
    if c['native_addr_width']>64 or c['native_id_width']>16:raise ValueError('Unsupported native AXI widths')
    if c['physical_base']<256 or c['physical_base']+513*4+256>c['capacity_bytes'] or c['capacity_bytes']>2**c['native_addr_width']:
        raise ValueError('Probe/guards outside configured native address aperture')
    if c['initialization']['mode']!='ip_autonomous_apb_idle':raise ValueError('Unsupported initialization; supply a reviewed sequencer backend rather than skipping readiness')
    if not c['initialization'].get('ready_pins') or not c['initialization'].get('evidence'):raise ValueError('IP readiness/auto-initialization evidence required')
    if info.get('generation') and abs(1000/info['generation']['period_ns']-c['kernel_mhz'])>0.001:raise ValueError('Kernel clock differs from generated DUT')
    if c['simulator'] not in ('questa','vcs'):raise ValueError('Detailed HBM requires Questa/VCS')
    return profile


def emit_tcl(prepared,out,c,profile):
    lines=[f'set prepared {tcl_quote(prepared)}',f'set out {tcl_quote(out)}',f'set part {tcl_quote(profile["part"])}',
           f'set controller_xci {tcl_quote(Path(c["xci"]).expanduser().resolve())}',
           f'set native_width {int(c["native_data_width"])}',f'set native_addr {int(c["native_addr_width"])}',
           f'set native_id {int(c["native_id_width"])}',f'set controller_bus {tcl_quote(c["controller_axi"])}',
           f'set simulator {tcl_quote(c["simulator"])}',f'set libraries {tcl_quote(Path(c["compiled_libraries"]).expanduser().resolve())}',
           'if {![string match 2024.2* [version -short]]} {error {Vivado 2024.2 required}}',
           'create_project -force reference $out/project -part $part',
           'import_ip -files $controller_xci', 'set templates [get_ips]',
           'if {[llength $templates]!=1} {error {Supply exactly one one-port configured HBM XCI}}',
           'set template [lindex $templates 0]',
           'if {[get_property IS_LOCKED $template]} {error {XCI is locked/incompatible; no automatic IP upgrade}}',
           'create_bd_design memory_reference',
           'set controller [create_bd_cell -type ip -vlnv [get_property IPDEF $template] hbm]',
           '# Copy the configured HBM USER parameters, never another board profile.',
           'set copied [open $out/controller-configuration.txt w]',
           'foreach property [list_property $template] {',
           ' if {[string match CONFIG.USER_* $property]} {',
           '  if {[lsearch -exact [list_property $controller] $property]<0} {error "Controller property changed: $property"}',
           '  set value [get_property $property $template];set_property $property $value $controller;puts $copied "$property=$value"',
           ' }','}','close $copied',
           'set endpoint [get_bd_intf_pins hbm/$controller_bus]',
           'foreach {property expected} [list PROTOCOL AXI3 DATA_WIDTH $native_width ADDR_WIDTH $native_addr ID_WIDTH $native_id] {',
           ' set actual [get_property CONFIG.$property $endpoint]',
           ' if {$actual ne $expected} {error "Native HBM $property=$actual; expected verified $expected"}',
           '}',
           'set incoming [create_bd_intf_port -mode Slave -vlnv xilinx.com:interface:aximm_rtl:1.0 S_AXI]',
           'set_property -dict [list CONFIG.PROTOCOL AXI4 CONFIG.DATA_WIDTH 32 CONFIG.ADDR_WIDTH $native_addr CONFIG.ID_WIDTH $native_id CONFIG.HAS_BURST 1 CONFIG.SUPPORTS_NARROW_BURST 1 CONFIG.HAS_REGION 0 CONFIG.HAS_QOS 1 CONFIG.ARUSER_WIDTH 0 CONFIG.AWUSER_WIDTH 0 CONFIG.WUSER_WIDTH 0 CONFIG.RUSER_WIDTH 0 CONFIG.BUSER_WIDTH 0] $incoming',
           'set width [create_bd_cell -type ip -vlnv xilinx.com:ip:axi_dwidth_converter:2.1 width]',
           'set_property -dict [list CONFIG.PROTOCOL AXI4 CONFIG.SI_DATA_WIDTH 32 CONFIG.MI_DATA_WIDTH $native_width CONFIG.ADDR_WIDTH $native_addr CONFIG.SI_ID_WIDTH $native_id CONFIG.FIFO_MODE 0] $width',
           'set cdc [create_bd_cell -type ip -vlnv xilinx.com:ip:axi_clock_converter:2.1 cdc]',
           'set_property -dict [list CONFIG.PROTOCOL AXI4 CONFIG.DATA_WIDTH $native_width CONFIG.ADDR_WIDTH $native_addr CONFIG.ID_WIDTH $native_id CONFIG.ACLK_ASYNC 1 CONFIG.SYNCHRONIZATION_STAGES 3] $cdc',
           'set protocol [create_bd_cell -type ip -vlnv xilinx.com:ip:axi_protocol_converter:2.1 protocol]',
           'set_property -dict [list CONFIG.SI_PROTOCOL AXI4 CONFIG.MI_PROTOCOL AXI3 CONFIG.DATA_WIDTH $native_width CONFIG.ADDR_WIDTH $native_addr CONFIG.ID_WIDTH $native_id CONFIG.TRANSLATION_MODE 2] $protocol',
           'connect_bd_intf_net $incoming [get_bd_intf_pins width/S_AXI]',
           'connect_bd_intf_net [get_bd_intf_pins width/M_AXI] [get_bd_intf_pins cdc/S_AXI]',
           'connect_bd_intf_net [get_bd_intf_pins cdc/M_AXI] [get_bd_intf_pins protocol/S_AXI]',
           'connect_bd_intf_net [get_bd_intf_pins protocol/M_AXI] $endpoint']
    for name,key in (('kernel_clk','kernel_mhz'),('memory_clk','memory_mhz'),('apb_clk','apb_mhz'),('reference_clk','reference_mhz')):
        lines += [f'set {name} [create_bd_port -dir I -type clk {name}]',f'set_property CONFIG.FREQ_HZ {int(c[key]*1e6)} ${name}']
    for name in ('kernel_resetn','memory_resetn','apb_resetn'):
        lines += [f'set {name} [create_bd_port -dir I -type rst {name}]',f'set_property CONFIG.POLARITY ACTIVE_LOW ${name}']
    lines += ['set_property CONFIG.ASSOCIATED_BUSIF S_AXI $kernel_clk','set_property CONFIG.ASSOCIATED_RESET kernel_resetn $kernel_clk',
              'connect_bd_net $kernel_clk [get_bd_pins width/s_axi_aclk] [get_bd_pins cdc/s_axi_aclk]',
              'connect_bd_net $kernel_resetn [get_bd_pins width/s_axi_aresetn] [get_bd_pins cdc/s_axi_aresetn]',
              'connect_bd_net $memory_clk [get_bd_pins cdc/m_axi_aclk] [get_bd_pins protocol/aclk]',
              'connect_bd_net $memory_resetn [get_bd_pins cdc/m_axi_aresetn] [get_bd_pins protocol/aresetn]']
    for pin,external in c['clock_pins'].items():lines += [f'connect_bd_net ${external} [get_bd_pins hbm/{pin}]']
    for pin,external in c['reset_pins'].items():lines += [f'connect_bd_net ${external} [get_bd_pins hbm/{pin}]']
    for i,(pin,setting) in enumerate(c['idle_inputs'].items()):
        lines += [f'set tie [create_bd_cell -type ip -vlnv xilinx.com:ip:xlconstant:1.1 tie_{i}]',
                  f'set_property -dict [list CONFIG.CONST_WIDTH {int(setting["width"])} CONFIG.CONST_VAL {int(setting["value"])}] $tie',
                  f'connect_bd_net [get_bd_pins tie_{i}/dout] [get_bd_pins hbm/{pin}]']
    # Every exposed controller input must have a deliberate driver. Unknown
    # enables, extra ports or extra stacks fail instead of taking defaults.
    lines += ['foreach pin [get_bd_pins -of_objects $controller -filter {DIR == I}] {',
              ' if {![llength [get_bd_nets -quiet -of_objects $pin]]} {error "Unconnected controller input: $pin; review configured XCI and bindings"}',
              '}']
    for i,pin in enumerate(c['initialization']['ready_pins']):
        lines += [f'set ready [create_bd_port -dir O ready_{i}]',f'connect_bd_net $ready [get_bd_pins hbm/{pin}]']
    lines += ['assign_bd_address','validate_bd_design','save_bd_design',
              'set bd [get_files */memory_reference.bd]','generate_target all $bd',
              'set wrapper [make_wrapper -files $bd -top]','add_files $wrapper',
              'source $prepared/sources.tcl','add_files $rtl_files',
              'add_files -fileset sim_1 [list $out/reference_tb.sv $out/axi_trace.sv $out/bind_monitors.sv]',
              'set_property top reference_tb [get_filesets sim_1]',
              'set_property target_simulator [expr {$simulator eq "questa" ? "Questa" : "VCS"}] [current_project]',
              'set_property ${simulator}.simulate.runtime all [get_filesets sim_1]',
              'set_property compxlib.${simulator}_compiled_library_dir $libraries [current_project]',
              'update_compile_order -fileset sim_1','report_ip_status -file $out/ip-status.rpt',
              'export_simulation -simulator $simulator -of_objects [get_filesets sim_1] -directory $out/export -lib_map_path $libraries -force',
              'close_project']
    (out/'build_reference.tcl').write_text('\n'.join(lines)+'\n')


def emit_tb(out,c,ns,repetitions,core_id_width=1):
    # This slice has exactly one 32-bit single-beat Bambu AXI master.
    # External physical addresses stay 64-bit until the explicit aperture.
    lines=['`timescale 1ns/1ps','module reference_tb;',
           'reg kernel_clk=0,memory_clk=0,apb_clk=0,reference_clk=0,raw_resetn=0,owner_core=0;',
           f'always #{500/c["kernel_mhz"]:.9f} kernel_clk=~kernel_clk;',
           f'always #{500/c["memory_mhz"]:.9f} memory_clk=~memory_clk;',
           f'always #{500/c["apb_mhz"]:.9f} apb_clk=~apb_clk;',
           f'always #{500/c["reference_mhz"]:.9f} reference_clk=~reference_clk;',
           'reg [2:0] kr=0,mr=0,pr=0;',
           "always @(posedge kernel_clk or negedge raw_resetn)if(!raw_resetn)kr<=0;else kr<={kr[1:0],1'b1};",
           "always @(posedge memory_clk or negedge raw_resetn)if(!raw_resetn)mr<=0;else mr<={mr[1:0],1'b1};",
           "always @(posedge apb_clk or negedge raw_resetn)if(!raw_resetn)pr<=0;else pr<={pr[1:0],1'b1};",
           'wire kernel_resetn=kr[2],memory_resetn=mr[2],apb_resetn=pr[2];']
    ready=[]
    for i,_ in enumerate(c['initialization']['ready_pins']):
        lines += [f'wire ready_{i};'];ready.append(f'ready_{i}')
    lines += ['reg [1:0] ready_sync=0;',"always @(posedge kernel_clk or negedge kernel_resetn)if(!kernel_resetn)ready_sync<=0;else ready_sync<={ready_sync[0],("+'&'.join(ready)+")};",
              'longint unsigned cycles=0;always @(posedge kernel_clk)cycles<=cycles+1;',
              'initial begin repeat('+str(c['max_kernel_cycles'])+')@(posedge kernel_clk);$fatal(1,"Reference watchdog: initialization/kernel/bus did not finish");end']
    for name,d,w in CONTROL:
        lines += [('reg ' if d=='input' else 'wire ')+(f'[{w-1}:0] ' if w>1 else '')+'s_axi_control_'+name+('=0' if d=='input' else '')+';']
    native={}
    ignored={'arregion','awregion','aruser','awuser','wuser'}
    for suffix,(direction,width) in AXI.items():
        if suffix in ('araddr','awaddr'):width=64
        if suffix in ('arid','awid','rid','bid'):width=core_id_width
        lines += ['wire '+(f'[{width-1}:0] ' if width>1 else '')+'k_'+suffix+';']
        if suffix in ignored:continue
        nw=c['native_addr_width'] if suffix in ('araddr','awaddr') else c['native_id_width'] if suffix in ('arid','awid','rid','bid') else width
        native[suffix]=nw
        kind='reg' if direction=='output' else 'wire'
        lines += [kind+' '+(f'[{nw-1}:0] ' if nw>1 else '')+'l_'+suffix+('=0' if kind=='reg' else '')+';',
                  'wire '+(f'[{nw-1}:0] ' if nw>1 else '')+'x_'+suffix+';']
        if direction=='output':
            expr='k_'+suffix
            if suffix in ('araddr','awaddr'):expr+=f'[{nw-1}:0]'
            lines += [f'assign x_{suffix}=owner_core?{expr}:l_{suffix};']
        else:
            expr='x_'+suffix
            if suffix in ('rid','bid'):expr+=f'[{core_id_width-1}:0]'
            lines += [f'assign k_{suffix}=owner_core?{expr}:0;',f'assign l_{suffix}=owner_core?0:x_{suffix};']
    control=[f'.s_axi_control_{n}(s_axi_control_{n})' for n,_,_ in CONTROL]
    lines += ['fpga_kernel dut(.ap_clk(kernel_clk),.ap_rst_n(kernel_resetn),'+','.join(control+[f'.m_axi_0_{s}(k_{s})' for s in AXI])+');']
    connections=[f'.{name}({name})' for name in ('kernel_clk','memory_clk','apb_clk','reference_clk','kernel_resetn','memory_resetn','apb_resetn')]+[f'.{r}({r})' for r in ready]
    connections += [f'.S_AXI_{s}(x_{s})' for s in native]
    lines += ['memory_reference_wrapper subsystem('+','.join(connections)+');',
              '// Reject out-of-aperture addresses; never silently wrap them.',
              'always @(posedge kernel_clk)if(owner_core && kernel_resetn)begin']
    if c['native_addr_width']<64:
        for channel in ('ar','aw'):
            lines += [f'if(k_{channel}valid && |k_{channel}addr[63:{c["native_addr_width"]}])$fatal(1,"Address above verified controller aperture");']
    if c['native_id_width']>core_id_width:
        lines += [f'if(owner_core&&x_rvalid&&|x_rid[{c["native_id_width"]-1}:{core_id_width}])$fatal(1,"Unexpected upper RID bits");',
                  f'if(owner_core&&x_bvalid&&|x_bid[{c["native_id_width"]-1}:{core_id_width}])$fatal(1,"Unexpected upper BID bits");']
    lines += ['if((k_arvalid&&(k_arregion||k_aruser))||(k_awvalid&&(k_awregion||k_awuser))||(k_wvalid&&k_wuser))$fatal(1,"Unsupported nonzero AXI user/region semantics");','end']
    # Reuse only the owned AXI-Lite test tasks; no reference script is executed.
    tasks=control_tasks((ROOT/'fpga/tests/control_tb.sv').read_text())
    lines += [re.sub(r'\bclk\b','kernel_clk',tasks)]
    lines += [r'''
task mem_write(input [63:0] address,input [31:0] value);
 fork
  begin @(negedge kernel_clk);l_awaddr=address;l_awvalid=1;do @(posedge kernel_clk);while(!l_awready);@(negedge kernel_clk);l_awvalid=0;end
  begin @(negedge kernel_clk);l_wdata=value;l_wstrb=15;l_wlast=1;l_wvalid=1;do @(posedge kernel_clk);while(!l_wready);@(negedge kernel_clk);l_wvalid=0;end
 join
 wait(l_bvalid);if(l_bresp!==0||l_bid!==0)$fatal(1,"Memory loading B error");
 @(negedge kernel_clk);l_bready=1;@(posedge kernel_clk);@(negedge kernel_clk);l_bready=0;
endtask
task mem_read(input [63:0] address,output [31:0] value);
 @(negedge kernel_clk);l_araddr=address;l_arvalid=1;
 do @(posedge kernel_clk);while(!l_arready);@(negedge kernel_clk);l_arvalid=0;
 wait(l_rvalid);value=l_rdata;if(l_rresp!==0||!l_rlast||l_rid!==0)$fatal(1,"Memory checking R error");
 @(negedge kernel_clk);l_rready=1;@(posedge kernel_clk);@(negedge kernel_clk);l_rready=0;
endtask
''', f"localparam [63:0] BASE=64'h{c['physical_base']:016x};",
              f'integer sizes[0:{len(ns)-1}];integer fd,rep,index,n,j;reg [31:0] value,expected,lo,hi,previous;reg [63:0] core_count,drain_count,ready_cycles;',
              'integer input_fd;string input_name;',
              'initial begin', 'l_awburst=1;l_arburst=1;l_awsize=2;l_arsize=2;l_wlast=1;']
    lines += [f'sizes[{i}]={n};' for i,n in enumerate(ns)]
    lines += [f'repeat({c["reset_cycles"]})@(negedge kernel_clk);raw_resetn=1;',
              'wait(ready_sync[1]);ready_cycles=cycles;repeat(4)@(negedge kernel_clk);',
              'fd=$fopen("vendor-results.jsonl","w");if(!fd)$fatal(1,"Cannot open results");',
              f'for(rep=0;rep<{repetitions};rep=rep+1)for(index=0;index<{len(ns)};index=index+1)begin',
              'n=sizes[index];owner_core=0;',
              'input_name=$sformatf("input-%0d-%0d.bin",n,rep);input_fd=$fopen(input_name,"wb");if(!input_fd)$fatal(1,"Cannot record input bytes");',
              'for(j=0;j<n;j=j+1)begin expected=7*j+3+rep*11;$fwrite(input_fd,"%c%c%c%c",expected&255,(expected>>8)&255,(expected>>16)&255,(expected>>24)&255);end $fclose(input_fd);',
              'for(j=0;j<64+513+64;j=j+1)begin',
              " expected=(j>=64&&j<64+n)?(7*(j-64)+3+rep*11):32'ha5a5a5a5;",
              ' mem_write(BASE-256+4*j,expected);end',
              'wr(32,BASE[31:0]);wr(36,BASE[63:32],15,1);wr(16,n);rd(4,previous);',
              '@(negedge kernel_clk);owner_core=1;wr(0,1);value=0;',
              'while(!value[2])rd(0,value);',
              'if(value[0]||value[3])$fatal(1,"Kernel completion/bus error");',
              'rd(4,value);if(value!==previous+1)$fatal(1,"Stale done/generation");',
              "rd(8'h80,lo);rd(8'h84,hi);core_count={hi,lo};rd(8'h88,lo);rd(8'h8c,hi);drain_count={hi,lo};",
              'if(drain_count<core_count)$fatal(1,"Counter ordering");',
              '@(negedge kernel_clk);owner_core=0;',
              'for(j=0;j<64+513+64;j=j+1)begin',
              " expected=(j>=64&&j<64+n)?(((7*(j-64)+3+rep*11)^32'h13579bdf)+(j-64)):32'ha5a5a5a5;",
              ' mem_read(BASE-256+4*j,value);if(value!==expected)$fatal(1,"Probe oracle/guard mismatch n=%0d word=%0d got=%h expected=%h",n,j,value,expected);end',
              '$fwrite(fd,'+json.dumps('{"mode":"vendor_memory_reference","case":"memory_probe_single","functional_status":"pass","n":%0d,"repetition":%0d,"core_cycles":%0d,"drain_cycles":%0d,"input_file":"%s","initialization_kernel_cycles":%0d}\n')+',n,rep,core_count,drain_count,input_name,ready_cycles);',
              'end','$fclose(fd);$display("VENDOR PROBE REFERENCE FUNCTIONAL PASS; model fidelity separately qualified");$finish;', 'end','endmodule']
    (out/'reference_tb.sv').write_text('\n'.join(lines)+'\n')


def generate(prepared,model,out,ns=(0,65,513),repetitions=2):
    prepared=Path(prepared).resolve();out=Path(out).resolve()
    info=json.loads((prepared/'manifest.json').read_text());profile=validate(info,model)
    if any(not isinstance(n,int) or n<0 or n>513 for n in ns) or not ns or not 1<=repetitions<=100:raise ValueError('Invalid small calibration selection')
    out.mkdir(parents=True,exist_ok=False)
    parsed=ports((prepared/'rtl'/(info['top']+'.v')).read_text(),info['top'])
    ids={parsed['m_axi_0_'+s][1] for s in ('arid','awid','rid','bid')}
    if len(ids)!=1 or max(ids)>model['native_id_width']:raise ValueError('Core/native ID widths require a reviewed conversion')
    emit_tcl(prepared,out,model,profile);emit_tb(out,model,ns,repetitions,ids.pop())
    shutil.copyfile(ROOT/'validation/rtl/axi_trace.sv',out/'axi_trace.sv')
    from validation.vendor import bind_monitors
    bind_monitors(prepared,out)
    write(out/'reference-manifest.json',{'case':info['case'],'prepared_manifest_sha256':digest(prepared/'manifest.json'),
                                       'model':model,'sizes':ns,'repetitions':repetitions,'status':'source emitted; vendor generation and simulation NOT executed',
                                       'boundary':'original wrapper AXI before ownership mux/aperture/conversion',
                                       'differences':['standalone one-port HBM subsystem, not the Vitis shell','explicit loader/DUT ownership mux','configured width conversion + asynchronous CDC + AXI4-to-AXI3 converter',
                                                      'no undocumented platform controller policy or address-map equivalence inferred']})
    return out


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--prepared',required=True);p.add_argument('--model',required=True);p.add_argument('--output',required=True)
    p.add_argument('--n',default='0,65,513');p.add_argument('--repetitions',type=int,default=2);p.add_argument('--build',action='store_true');a=p.parse_args()
    c=json.loads(Path(a.model).read_text());prepared=Path(a.prepared).resolve()
    if a.build:
        info=json.loads((prepared/'manifest.json').read_text())
        if info.get('reference_only'):raise ValueError('Build requires board-generated Ferrandi RTL; kit fixture is emission-test only')
        if 'REPLACE' in c['initialization']['evidence']:raise ValueError('Verify the configured IP autonomous initialization/readiness sequence before a vendor build')
        from validation.vendor import validate as vendor_preflight
        vendor_preflight(c,c['simulator'])
        if digest(c['xci'])!=c.get('xci_sha256'):raise ValueError('Configured one-port XCI fingerprint missing/changed')
    out=generate(prepared,c,a.output,tuple(int(n) for n in a.n.split(',')),a.repetitions)
    if a.build:run([tool('vivado'),'-mode','batch','-source',out/'build_reference.tcl'],out,out/'build-reference.log')
    print(out/'reference-manifest.json')

if __name__=='__main__':
    try:main()
    except (ValueError,OSError,KeyError) as e:print('ERROR: '+str(e),file=sys.stderr);sys.exit(2)
