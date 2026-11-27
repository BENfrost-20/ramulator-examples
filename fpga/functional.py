"""Simulate a prepared FPGA kernel and its control wrapper with Verilator."""
import argparse
import json
import math
import os
from pathlib import Path
import shutil
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from fpga.prepare import digest
from fpga.run import run
from tools.ramulator import API_VERSION, installed_library, require_headers


def source(info, size=None):
    prefixes=info['axi_ports'];banks=info['banks']
    sizes = '{0,1,63,64,65,127,128,129,512,513}' if info['top'] == 'memory_probe' else '{case_n}'
    repetitions = 2
    if size is not None:
        sizes = '{'+str(size)+'}'
        repetitions = 1
    code=['#include "Vfpga_kernel.h"','#include "verilated.h"','#include "case.hpp"','#include "abi.hpp"',
          '#include "functional_axi.hpp"','#include <iostream>',
          'static std::uint64_t cycles=0;',
          'Vfpga_kernel dut;std::vector<Bytes> memory(case_banks,Bytes(slab_bytes,0xa5));',
          'std::uint64_t base(unsigned b){return 0x1200000000ULL+(std::uint64_t(b)<<24);}',
          'Port ports[] = {'+','.join('{&memory['+str(i if banks==2 else 0)+'],base('+str(i if banks==2 else 0)+')}' for i in range(len(prefixes)))+'};',
          'void step(){if(cycles>20000000)throw std::runtime_error("Simulation watchdog");dut.ap_clk=0;',
          '#ifdef FPGA_WITH_RAMULATOR','if(cycles) timing->advance_cycle();','#endif']
    for i,p in enumerate(prefixes):
        code += [f'''ports[{i}].update(cycles);
 dut.{p}_arready=ports[{i}].arready(cycles);
 dut.{p}_awready=ports[{i}].awready(cycles);
 dut.{p}_wready=ports[{i}].wready(cycles);
 dut.{p}_rvalid=ports[{i}].rv;dut.{p}_rid=ports[{i}].rid;dut.{p}_rdata=ports[{i}].rd;
 dut.{p}_rlast=1;dut.{p}_rresp=0;
 dut.{p}_bvalid=ports[{i}].bv;dut.{p}_bid=ports[{i}].bid;dut.{p}_bresp=0;''']
    code += ['dut.eval();']
    for i,p in enumerate(prefixes):
        code += [f'''if(dut.ap_rst_n) {{
 if(dut.{p}_rvalid&&dut.{p}_rready)ports[{i}].consume_read(cycles);
 if(dut.{p}_bvalid&&dut.{p}_bready)ports[{i}].consume_write(cycles);
 if(dut.{p}_arvalid&&dut.{p}_arready)ports[{i}].ar(dut.{p}_araddr,dut.{p}_arid,dut.{p}_arsize,dut.{p}_arlen,cycles);
 if(dut.{p}_awvalid&&dut.{p}_awready)ports[{i}].write_addr(dut.{p}_awaddr,dut.{p}_awid,dut.{p}_awsize,dut.{p}_awlen,cycles);
 if(dut.{p}_wvalid&&dut.{p}_wready)ports[{i}].write_data(dut.{p}_wdata,dut.{p}_wstrb,dut.{p}_wlast,cycles);
 }}''']
    code += [r'''
 dut.ap_clk=1;dut.eval();++cycles;
}
void write(unsigned a,unsigned v,unsigned strobe=15,bool reverse=false){
 dut.s_axi_control_bready=0;bool adone=false,wdone=false;
 for(unsigned i=0;!adone||!wdone;++i){
  dut.ap_clk=0;dut.s_axi_control_awaddr=a;dut.s_axi_control_wdata=v;dut.s_axi_control_wstrb=strobe;
  dut.s_axi_control_awvalid=!adone&&(reverse?i>=3:true);
  dut.s_axi_control_wvalid=!wdone&&(reverse?true:i>=3);dut.eval();
  bool ah=dut.s_axi_control_awvalid&&dut.s_axi_control_awready;
  bool wh=dut.s_axi_control_wvalid&&dut.s_axi_control_wready;step();adone|=ah;wdone|=wh;
 }
 dut.s_axi_control_awvalid=0;dut.s_axi_control_wvalid=0;
 while(!dut.s_axi_control_bvalid)step();
 auto resp=dut.s_axi_control_bresp;
 // Response must remain stable under backpressure.
 for(unsigned i=0;i<3;++i){step();if(!dut.s_axi_control_bvalid||dut.s_axi_control_bresp!=resp)throw std::runtime_error("Unstable B response");}
 dut.s_axi_control_bready=1;step();dut.s_axi_control_bready=0;
 if(resp)throw std::runtime_error("AXI-Lite write rejected");
}
unsigned read(unsigned a){
 dut.s_axi_control_araddr=a;dut.s_axi_control_arvalid=1;dut.s_axi_control_rready=0;
 dut.ap_clk=0;dut.eval();while(!dut.s_axi_control_arready)step();step();dut.s_axi_control_arvalid=0;
 while(!dut.s_axi_control_rvalid)step();auto v=dut.s_axi_control_rdata;
 if(dut.s_axi_control_rresp)throw std::runtime_error("AXI-Lite read rejected");
 for(unsigned i=0;i<2;++i){step();if(!dut.s_axi_control_rvalid||dut.s_axi_control_rdata!=v)throw std::runtime_error("Unstable R response");}
 dut.s_axi_control_rready=1;step();dut.s_axi_control_rready=0;return v;
}
std::uint64_t read64(unsigned a){auto lo=read(a);return lo|(std::uint64_t(read(a+4))<<32);}
int main(int argc,char** argv){
 try{
 Verilated::commandArgs(argc,argv);
#ifdef FPGA_WITH_RAMULATOR
 if (argc != 3) throw std::runtime_error("Pass the Ramulator YAML path and AXI period");
 timing = std::make_unique<RamulatorTiming>(argv[1], std::stold(argv[2]));
 model_data_base = '''+str(info.get('logical_base', 0))+r'''ULL;
 axi_trace.open("ramulator-axi.jsonl");
 if (!axi_trace) throw std::runtime_error("Cannot open Ramulator AXI trace");
#endif
 dut.ap_rst_n=0;for(unsigned i=0;i<8;++i)step();dut.ap_rst_n=1;step();
 if(read(0)!=0||read(4)!=0)throw std::runtime_error("Reset status");
 // Byte strobe readback and high (>4 GiB) relocation bases.
 write(abi::N,0x12345678);write(abi::N,0x0000ab00,2,true);if(read(abi::N)!=0x1234ab78)throw std::runtime_error("WSTRB failure");
 for(unsigned p=0;p<case_ports;++p){auto a=base(base_register_bank[p])+abi::GUARD;write(abi::BASE0+8*p,unsigned(a));write(abi::BASE0+8*p+4,unsigned(a>>32),15,true);if(read(abi::BASE0+8*p+4)!=unsigned(a>>32))throw std::runtime_error("High address lost");}
#ifdef FPGA_WITH_RAMULATOR
 std::ofstream results("ramulator-results.jsonl");
#else
 std::ofstream results("functional-results.jsonl");
#endif
 if (!results) throw std::runtime_error("Cannot open simulation results");
 for(unsigned rep=0;rep<'''+str(repetitions)+r''';++rep){for(unsigned n : std::vector<unsigned>'''+sizes+r'''){
#ifdef FPGA_WITH_RAMULATOR
 trace_n = n;
 trace_rep = rep;
#endif
 auto initial=case_input(n,rep),expected=case_expected(initial,n);
 auto input_file=save_input(initial,n,rep);
 auto packed=pack(initial,case_banks),want=pack(expected,case_banks);
 for(auto& p:ports)if(!p.empty())throw std::runtime_error("Memory not drained before restart");
 for(unsigned b=0;b<case_banks;++b){std::fill(memory[b].begin(),memory[b].end(),0xa5);std::copy(packed[b].begin(),packed[b].end(),memory[b].begin()+abi::GUARD);}
 auto previous=read(abi::GENERATION);write(abi::N,n,15,rep%2);write(0,1,15,!(rep%2));
 while(!(read(0)&abi::DRAINED))step();auto status=read(0);
 if((status&abi::BUSY)||(status&abi::ERROR)||read(4)!=previous+1)throw std::runtime_error("Restart/completion/error status");
 auto core=read64(abi::CORE_CYCLES),drain=read64(abi::DRAIN_CYCLES);
 if(drain<core||!core)throw std::runtime_error("Counter ordering");
 for(auto& p:ports)if(!p.empty())throw std::runtime_error("Reported completion before memory drained");
 for(unsigned b=0;b<case_banks;++b)for(unsigned i=0;i<slab_bytes;++i){unsigned v=(i>=abi::GUARD&&i<abi::GUARD+want[b].size())?want[b][i-abi::GUARD]:0xa5;if(memory[b][i]!=v)throw std::runtime_error("Functional/guard mismatch byte "+std::to_string(i));}
 if(read64(abi::CORE_CYCLES)!=core)throw std::runtime_error("Unstable completion snapshot");
 results<<"{\"mode\":\""<<simulation_mode<<"\",\"case\":\""<<case_name<<"\",\"functional_status\":\"pass\",\"n\":"<<n<<",\"repetition\":"<<rep<<",\"core_cycles\":"<<core<<",\"drain_cycles\":"<<drain<<",\"input_file\":\""<<input_file<<"\"";
#ifdef FPGA_WITH_RAMULATOR
 results<<",\"dram_ticks_per_axi_cycle\":"<<timing->ratio()
        <<",\"axi_reads\":"<<ports[0].reads<<",\"axi_writes\":"<<ports[0].writes;
#endif
 results<<"}\n";
 }}
 dut.ap_rst_n=0;for(unsigned i=0;i<4;++i)step();dut.ap_rst_n=1;step();
 if(read(0)||read(4)||read64(abi::CORE_CYCLES))throw std::runtime_error("Post-run reset");
 std::uint64_t reads = 0, writes = 0;
 for (const auto& port : ports) { reads += port.reads; writes += port.writes; }
 std::cout<<case_name<<" "<<simulation_mode<<" wrapper/DUT PASS reads="<<reads<<" writes="<<writes<<"\n";
 return 0;
 }catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}
}
''']
    return '\n'.join(code)


def ramulator_flags(prefix, libdir=None):
    require_headers(prefix)
    library = installed_library(prefix, libdir)
    cflags = ['-DFPGA_WITH_RAMULATOR', '-I'+str(prefix/'include')]
    # Verilator places -LDFLAGS before the objects in the link command.
    ldflags = ['-L'+str(library.parent), '-Wl,-rpath,'+str(library.parent),
               '-Wl,--no-as-needed', '-lramulator', '-Wl,--as-needed']
    return cflags, ldflags, library


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--prepared', required=True, type=Path)
    ap.add_argument('--output', type=Path, help='Separate directory for build and results')
    ap.add_argument('--generate-only', action='store_true')
    ap.add_argument('--ramulator-config', type=Path, help='Use this Ramulator 2 YAML instead of AXI RAM')
    ap.add_argument('--clock-period-ns', type=float,
                    help='AXI clock period in ns (required with Ramulator 2.1)')
    ap.add_argument('--n', type=int, help='Run one probe with this size and repetition 0')
    args = ap.parse_args()

    prepared = args.prepared.resolve()
    info = json.loads((prepared/'manifest.json').read_text())
    for name, sha in info['rtl_sha256'].items():
        if digest(prepared/'rtl'/name) != sha:
            raise ValueError('RTL changed: '+name)
    if args.n is not None and (info['top'] != 'memory_probe' or not 0 <= args.n <= 8192):
        ap.error('--n requires a memory probe and a size between 0 and 8192')
    if args.ramulator_config is not None:
        if (info['case'] != 'memory_probe_single' or info['banks'] != 1
                or len(info['axi_ports']) != 1):
            ap.error('Ramulator currently supports memory_probe_single with one AXI port')
        if args.n is None:
            ap.error('--ramulator-config requires --n to select one isolated probe run')
        if args.clock_period_ns is None:
            ap.error('--ramulator-config requires --clock-period-ns to derive AXI timing from DRAM tCK')

    if args.clock_period_ns is not None and (args.ramulator_config is None
            or not math.isfinite(args.clock_period_ns) or args.clock_period_ns < 0.000001):
        ap.error('--clock-period-ns requires --ramulator-config and a finite period of at least 1 fs')

    out = args.output.resolve() if args.output else prepared
    out.mkdir(parents=True, exist_ok=True)
    cpp = out/'functional.cpp'
    cpp.write_text(source(info, args.n))
    if args.generate_only:
        print(cpp)
        return

    verilator = os.environ.get('FPGA_VERILATOR', shutil.which('verilator') or 'verilator')
    flags = json.loads((prepared/'host-flags.json').read_text())
    cflags = ['-I'+str(prepared), '-I'+str(ROOT/'fpga/host'), '-Wno-unknown-pragmas', *flags]
    cxx = os.environ.get('FPGA_VERILATOR_CXX')
    build_flags = ['-MAKEFLAGS', f'CXX={cxx} LINK={cxx}'] if cxx else []
    run_args = []
    mode = 'functional'
    if args.ramulator_config is not None:
        config = args.ramulator_config.resolve(strict=True)
        prefix = os.environ.get('RAMULATOR2_DIR')
        if not prefix:
            ap.error('Set RAMULATOR2_DIR to the installed Ramulator 2 prefix')
        libdir = os.environ.get('RAMULATOR2_LIBDIR')
        includes, ldflags, library = ramulator_flags(
            Path(prefix).resolve(), Path(libdir).resolve() if libdir else None)
        cflags += ['-std=c++20', *includes]
        build_flags += ['-LDFLAGS', ' '.join(ldflags)]
        snapshot = out/'ramulator-config.yaml'
        if config != snapshot:
            shutil.copyfile(config, snapshot)
        (out/'ramulator-run.json').write_text(json.dumps({
            'config_sha256': digest(snapshot),
            'library': str(library),
            'library_sha256': digest(library),
            'ramulator_version': API_VERSION,
            'axi_period_ns': args.clock_period_ns,
            'rtl_sha256': info['rtl_sha256'],
            'logical_base': info['logical_base'],
            'write_response': 'ramulator_acceptance',
        }, indent=2)+'\n')
        run_args.extend((snapshot, str(args.clock_period_ns)))
        mode = 'ramulator'
    else:
        cflags.append('-std=c++17')

    rtl = sorted(prepared/'rtl'/name for name in info['rtl_sha256'] if name.endswith(('.v', '.sv')))
    run([verilator, '--cc', '--exe', '--build', '--top-module', 'fpga_kernel', '-Wno-fatal',
         '--Mdir', out/'obj_dir', '-CFLAGS', ' '.join(cflags), *build_flags, *rtl, cpp],
        out, out/f'{mode}-build.log')
    run([out/'obj_dir/Vfpga_kernel', *run_args], out, out/f'{mode}.log')
    print((out/f'{mode}.log').read_text())


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError) as exc:
        print('ERROR: '+str(exc), file=sys.stderr)
        sys.exit(2)
