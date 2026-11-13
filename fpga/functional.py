"""Generate an executable Verilator test of prepared DUT + real control wrapper.
Functional single-beat 32-bit AXI responder: NO DRAM timing claim.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from fpga.prepare import digest
from fpga.run import run

MEMORY=r'''
struct Port {
 Bytes* bytes;std::uint64_t base;
 bool rv=false,bv=false;unsigned rid=0,bid=0,rd=0,rdue=0,bdue=0;
 bool arp=false;unsigned saved_rid=0;std::uint64_t saved_ra=0;
 struct A{std::uint64_t addr;unsigned id,size;};struct W{unsigned data,strb;};
 std::deque<A> aw;std::deque<W> w;
 void check(std::uint64_t a,unsigned size){if(size>2||a<base||a+(1u<<size)>base+bytes->size())throw std::runtime_error("Out-of-range/narrow AXI address");}
 void ar(std::uint64_t a,unsigned id,unsigned size,unsigned len){check(a,size);if(len)throw std::runtime_error("Functional backend supports single beats only");arp=true;saved_ra=a;saved_rid=id;rdue=cycles+2+(cycles%5);++reads;}
 void write_addr(std::uint64_t a,unsigned id,unsigned size,unsigned len){check(a,size);if(len)throw std::runtime_error("Single beat model: AWLEN must be zero");aw.push_back({a,id,size});++writes;}
 void write_data(unsigned d,unsigned s,bool last){if(!last)throw std::runtime_error("Missing WLAST");w.push_back({d,s});}
 void update(){
  if(arp && !rv && cycles>=rdue){auto a=(saved_ra-base)&~std::uint64_t(3);rd=0;for(unsigned i=0;i<4;++i)rd|=unsigned((*bytes)[a+i])<<(8*i);rid=saved_rid;rv=true;arp=false;}
  if(!bv && !aw.empty() && !w.empty() && !bdue){auto a=aw.front();auto v=w.front();aw.pop_front();w.pop_front();auto off=(a.addr-base)&~std::uint64_t(3);for(unsigned i=0;i<4;++i)if(v.strb&(1u<<i))(*bytes)[off+i]=(v.data>>(8*i))&255;bid=a.id;bdue=cycles+3;}
  if(bdue && cycles>=bdue){bv=true;bdue=0;}
 }
 bool empty()const{return !rv&&!bv&&!arp&&aw.empty()&&w.empty()&&!bdue;}
};
'''

def source(info):
    prefixes=info['axi_ports'];banks=info['banks']
    code=['#include "Vfpga_kernel.h"','#include "verilated.h"','#include "case.hpp"','#include "abi.hpp"',
          '#include <deque>','#include <fstream>','#include <iostream>',
          'static std::uint64_t cycles=0,reads=0,writes=0;',MEMORY,
          'Vfpga_kernel dut;std::vector<Bytes> memory(case_banks,Bytes(slab_bytes,0xa5));',
          'std::uint64_t base(unsigned b){return 0x1200000000ULL+(std::uint64_t(b)<<24);}',
          'Port ports[] = {'+','.join('{&memory['+str(i if banks==2 else 0)+'],base('+str(i if banks==2 else 0)+')}' for i in range(len(prefixes)))+'};',
          'void step(){if(cycles>20000000)throw std::runtime_error("Simulation watchdog");dut.ap_clk=0;']
    for i,p in enumerate(prefixes):
        code += [f'''ports[{i}].update();
 dut.{p}_arready=!ports[{i}].arp&&!ports[{i}].rv&&(cycles%3!=0);
 dut.{p}_awready=ports[{i}].aw.size()<4&&(cycles%5!=0);
 dut.{p}_wready=ports[{i}].w.size()<4&&(cycles%4!=0);
 dut.{p}_rvalid=ports[{i}].rv;dut.{p}_rid=ports[{i}].rid;dut.{p}_rdata=ports[{i}].rd;
 dut.{p}_rlast=1;dut.{p}_rresp=0;
 dut.{p}_bvalid=ports[{i}].bv;dut.{p}_bid=ports[{i}].bid;dut.{p}_bresp=0;''']
    code += ['dut.eval();']
    for i,p in enumerate(prefixes):
        code += [f'''if(dut.ap_rst_n) {{
 if(dut.{p}_rvalid&&dut.{p}_rready)ports[{i}].rv=false;
 if(dut.{p}_bvalid&&dut.{p}_bready)ports[{i}].bv=false;
 if(dut.{p}_arvalid&&dut.{p}_arready)ports[{i}].ar(dut.{p}_araddr,dut.{p}_arid,dut.{p}_arsize,dut.{p}_arlen);
 if(dut.{p}_awvalid&&dut.{p}_awready)ports[{i}].write_addr(dut.{p}_awaddr,dut.{p}_awid,dut.{p}_awsize,dut.{p}_awlen);
 if(dut.{p}_wvalid&&dut.{p}_wready)ports[{i}].write_data(dut.{p}_wdata,dut.{p}_wstrb,dut.{p}_wlast);
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
 Verilated::commandArgs(argc,argv);dut.ap_rst_n=0;for(unsigned i=0;i<8;++i)step();dut.ap_rst_n=1;step();
 if(read(0)!=0||read(4)!=0)throw std::runtime_error("Reset status");
 // Byte strobe readback and high (>4 GiB) relocation bases.
 write(abi::N,0x12345678);write(abi::N,0x0000ab00,2,true);if(read(abi::N)!=0x1234ab78)throw std::runtime_error("WSTRB failure");
 for(unsigned p=0;p<case_ports;++p){auto a=base(base_register_bank[p])+abi::GUARD;write(abi::BASE0+8*p,unsigned(a));write(abi::BASE0+8*p+4,unsigned(a>>32),15,true);if(read(abi::BASE0+8*p+4)!=unsigned(a>>32))throw std::runtime_error("High address lost");}
 std::ofstream results("functional-results.jsonl");
 for(unsigned rep=0;rep<2;++rep){for(unsigned n : std::vector<unsigned>'''+('{0,1,63,64,65,127,128,129,512,513}' if info['top']=='memory_probe' else '{case_n}')+r'''){
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
 results<<"{\"mode\":\"functional_axi_ram\",\"case\":\""<<case_name<<"\",\"functional_status\":\"pass\",\"n\":"<<n<<",\"repetition\":"<<rep<<",\"core_cycles\":"<<core<<",\"drain_cycles\":"<<drain<<",\"input_file\":\""<<input_file<<"\"}\n";
 }}
 dut.ap_rst_n=0;for(unsigned i=0;i<4;++i)step();dut.ap_rst_n=1;step();
 if(read(0)||read(4)||read64(abi::CORE_CYCLES))throw std::runtime_error("Post-run reset");
 std::cout<<case_name<<" functional wrapper/DUT PASS reads="<<reads<<" writes="<<writes<<"\n";return 0;
 }catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}
}
''']
    return '\n'.join(code)


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--prepared',required=True)
    ap.add_argument('--generate-only',action='store_true');args=ap.parse_args()
    out=Path(args.prepared).resolve();info=json.loads((out/'manifest.json').read_text())
    for name,sha in info['rtl_sha256'].items():
        if digest(out/'rtl'/name)!=sha: raise ValueError('RTL changed: '+name)
    cpp=out/'functional.cpp';cpp.write_text(source(info))
    if args.generate_only: print(cpp);return
    verilator=os.environ.get('FPGA_VERILATOR',shutil.which('verilator') or 'verilator')
    flags=json.loads((out/'host-flags.json').read_text())
    cflags=['-std=c++17','-I'+str(out),'-I'+str(ROOT/'fpga/host'),'-Wno-unknown-pragmas',*flags]
    run([verilator,'--cc','--exe','--build','--top-module','fpga_kernel','-Wno-fatal','--Mdir',out/'obj_dir',
         '-CFLAGS',' '.join(cflags),*sorted((out/'rtl').glob('*v')),cpp],out,out/'functional-build.log')
    run([out/'obj_dir/Vfpga_kernel'],out,out/'functional.log')
    print((out/'functional.log').read_text())

if __name__=='__main__':
    try: main()
    except (ValueError,OSError) as e: print('ERROR: '+str(e),file=sys.stderr);sys.exit(2)
