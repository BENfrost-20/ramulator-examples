"""Explicit adapter for the small 32-bit Bambu AXI contract; fail closed otherwise.

This is a verifier for literal, non-ANSI Bambu declarations, NOT an arbitrary RTL
parser. Parameters, vectors of interfaces, unknown ports and changed reset
conventions require a reviewed adapter. Vivado elaboration remains mandatory.
"""
import difflib
import hashlib
import json
from pathlib import Path
import re
import shutil

ROOT = Path(__file__).resolve().parents[1]
ABI = json.loads((ROOT/'fpga/abi.json').read_text())
# Direction is relative to DUT.
AXI = { 'arready':('input',1), 'rid':('input',1), 'rdata':('input',32),
'rresp':('input',2), 'rlast':('input',1), 'rvalid':('input',1),
'awready':('input',1), 'wready':('input',1), 'bid':('input',1),
'bresp':('input',2), 'bvalid':('input',1), 'arid':('output',1),
'araddr':('output',32), 'arlen':('output',8), 'arsize':('output',3),
'arburst':('output',2), 'arlock':('output',1), 'arcache':('output',4),
'arprot':('output',3), 'arqos':('output',4), 'arregion':('output',4),
'aruser':('output',1), 'arvalid':('output',1), 'rready':('output',1),
'awid':('output',1), 'awaddr':('output',32), 'awlen':('output',8),
'awsize':('output',3), 'awburst':('output',2), 'awlock':('output',1),
'awcache':('output',4), 'awprot':('output',3), 'awqos':('output',4),
'awregion':('output',4), 'awuser':('output',1), 'awvalid':('output',1),
'wdata':('output',32), 'wstrb':('output',4), 'wlast':('output',1),
'wvalid':('output',1), 'wuser':('output',1), 'bready':('output',1)}
CONTROL = [('awaddr','input',8),('awvalid','input',1),('awready','output',1),
('wdata','input',32),('wstrb','input',4),('wvalid','input',1),('wready','output',1),
('bresp','output',2),('bvalid','output',1),('bready','input',1),
('araddr','input',8),('arvalid','input',1),('arready','output',1),
('rdata','output',32),('rresp','output',2),('rvalid','output',1),('rready','input',1)]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def layout(case):
    if case['suite']=='calibration':
        return {'top':'memory_probe','pointers':{'data':ABI['probe_logical_base']},'n':513,
                'banks':case['banks'],'logical_base':ABI['probe_logical_base'], 'buffers':{'data':[0,2052,'inout']}}
    if case['suite']=='smoke':
        return {'top':'vector_add','pointers':{'vec_a':0x10000100,'vec_b':0x10000300,'vec_c':0x10000500},
                'n':8,'banks':1,'logical_base':ABI['suite_logical_base'],
                'buffers':{'vec_a':[256,32,'input'],'vec_b':[768,32,'input'],'vec_c':[1280,32,'output']}}
    defs = dict(f[2:].split('=',1) for f in case['flags'] if f.startswith('-D') and '=' in f)
    words,outputs = int(defs['WORDS']),int(defs['OUT_WORDS'])
    return {'top':'memory_pattern','pointers':{'in':0x10000100,'out':0x10000100+4*words+256},
            'n':0,'banks':1,'logical_base':ABI['suite_logical_base'],
            'buffers':{'in':[256,4*words,'inout'],'out':[256+4*words+256,4*outputs,'output']},'defines':defs}


def ports(text, top):
    text=re.sub(r'/\*.*?\*/|//[^\n]*','',text,flags=re.S)
    found=re.findall(r'\bmodule\s+'+re.escape(top)+r'\s*\((.*?)\);(.*?)\bendmodule',text,re.S)
    if len(found)!=1:
        raise ValueError('Expected one literal non-ANSI Bambu top: '+top)
    header,body=found[0]
    names=[s.strip() for s in header.split(',')]
    parsed={}
    for direction,hi,lo,name in re.findall(r'^\s*(input|output)\s+(?:\[(\d+):(\d+)\]\s+)?(\w+)\s*;',body,re.M):
        if lo and int(lo)!=0: raise ValueError('Nonzero vector lower bound')
        parsed[name]=(direction,int(hi)+1 if hi else 1)
    if set(names)!=set(parsed):
        raise ValueError('Unsupported top declaration. Require explicit adapter; header/declarations differ: '+str(set(names)^set(parsed)))
    return parsed


def verify(text, info):
    p=ports(text,info['top'])
    # This small backend is reviewed only for active-low synchronous Bambu FSMs.
    if not re.search(r"if\s*\(reset\s*==\s*1'b0\)",text):
        raise ValueError('Reset polarity not evidenced by active-low Bambu FSM; inspect RTL')
    expected={'clock':('input',1),'reset':('input',1),'start_port':('input',1),
              'done_port':('output',1),'idle_port':('output',1)}
    for name in info['pointers']:
        expected[name]=('input',32)
    if info['top'] in ('memory_probe','vector_add'): expected['n']=('input',32)
    prefixes=sorted(n[:-7] for n in p if n.endswith('_araddr'))
    if not prefixes: raise ValueError('No supported AXI master; native/minimal bridge not implemented')
    for prefix in prefixes:
        for suffix,(direction,width) in AXI.items():
            if suffix in ('arid','rid','awid','bid'):
                width=p.get(prefix+'_'+suffix,('',0))[1]
                if width not in (1,2): raise ValueError('Only inspected one/two-bit AXI IDs supported')
            if suffix in ('araddr','awaddr'):
                width=p.get(prefix+'_'+suffix,('',0))[1]
                if width not in (31,32): raise ValueError('Only reviewed 31/32-bit logical addresses supported')
            expected[prefix+'_'+suffix]=(direction,width)
        if prefix in p: expected[prefix]=('output',1)  # Bambu dummy marker
    if p!=expected:
        diff={n:(p.get(n),expected.get(n)) for n in p.keys()|expected.keys() if p.get(n)!=expected.get(n)}
        raise ValueError('Generated interface differs from supported contract; no architecture substitution: '+str(diff))
    if info['banks']==2 and prefixes!=['m_axi_0','m_axi_1']:
        raise ValueError('Banked probe requires the inspected two-port Bambu bus')
    if info['banks']==1 and info['top']=='memory_probe' and prefixes!=['m_axi_0']:
        raise ValueError('Single probe requires one inspected Bambu bus')
    return p,prefixes


def bounded_log2(text):
    start=text.index('module MinimalAXI4Adapter(')
    end=text.index('endmodule',start)
    body=text[start:end]
    pattern=r'  `ifndef _SIM_HAVE_CLOG2\s+function integer log2;.*?  endgenerate'
    replacement='''  // Fixed bound for ceil(log2(bytes)), valid transfer sizes 1..4.
  function integer fpga_size_log2;
    input integer value;
    integer v,j;
    begin
      v=value-1;fpga_size_log2=0;
      for(j=0;j<32;j=j+1) begin
        if(v>0) begin v=v>>1;fpga_size_log2=fpga_size_log2+1;end
      end
    end
  endfunction
  wire [2:0] size_next;
  assign size_next=fpga_size_log2(Mout_data_ram_size >> 3);'''
    body,count=re.subn(pattern,replacement,body,flags=re.S)
    if count!=1: raise ValueError('Adapter log2 layout changed; inspect before transforming')
    return text[:start]+body+text[end:]


def prepare(case, source, out, fix=False):
    info=layout(case);source=Path(source);out=Path(out)
    if out.exists(): raise ValueError('Refusing to overwrite prepared integration: '+str(out))
    top=source/(info['top']+'.v');lib=source/'panda_libtech.v'
    text=top.read_text();p,prefixes=verify(text,info)
    info['axi_ports']=prefixes
    info['base_register_banks']=[i if info['banks']==2 else 0 for i in range(len(prefixes))]
    if info['banks']==2:
        # Verify both bank-selector and compaction primitive instances, not just ports.
        if not all(re.search(r'\.'+name+r'\('+str(value)+r'\)',text) for name,value in (('BANK_START',9),('BANK_END',8),('BANK_COUNT',2),('SELECTOR_START',9),('SELECTOR_END',8))):
            raise ValueError('Missing RTL evidence for byte-wise 256-byte bank selection')
        contracts=json.loads((ROOT/'fpga/contracts.json').read_text())['supported_banked_probe_library_modules']
        for name,sha in contracts.items():
            module=re.search(r'\bmodule '+name+r'\(.*?\bendmodule',lib.read_text(),re.S)
            if not module: raise ValueError('Missing recognized '+name+' primitive')
            normalized=re.sub(r'\s+','',re.sub(r'/\*.*?\*/|//[^\n]*','',module[0],flags=re.S))
            if hashlib.sha256(normalized.encode()).hexdigest()!=sha:
                raise ValueError('Bank selection/compaction implementation changed; review '+name+' before deployment')
        info['bank_mapping_evidence']={'selector_bit':8,'stripe_bytes':256,'compaction':'remove bit 8','verified_library_modules':contracts}
    out.mkdir(parents=True)
    for name in ('original','rtl'): (out/name).mkdir()
    sources=[top,lib]
    for path in sources:
        shutil.copyfile(path,out/'original'/path.name)
        shutil.copyfile(path,out/'rtl'/path.name)
    changes=[]
    if fix:
        old=lib.read_text();new=bounded_log2(old)
        (out/'rtl'/lib.name).write_text(new)
        (out/'adapter.diff').write_text(''.join(difflib.unified_diff(old.splitlines(True),new.splitlines(True),fromfile='original/'+lib.name,tofile='rtl/'+lib.name)))
        changes.append('bounded MinimalAXI4Adapter transfer-size ceil(log2); original untouched; synthesis check required')
    wrapper=render_wrapper(info,p,prefixes)
    (out/'rtl/fpga_kernel.sv').write_text(wrapper)
    for file in ('control.sv','drain.sv'): shutil.copyfile(ROOT/'fpga/rtl'/file,out/'rtl'/file)
    info.update(case=case['name'],abi=ABI,original_sha256={x.name:digest(x) for x in sources},
                transformations=changes,rtl_sha256={x.name:digest(x) for x in (out/'rtl').iterdir()},
                frontend='I386_CLANG16' if 'I386_CLANG16' in text[:4000] else 'I386_CLANG13' if 'I386_CLANG13' in text[:4000] else 'unknown',
                original_flags=case['flags'], hardware_status='prepared; not synthesized or packaged')
    (out/'manifest.json').write_text(json.dumps(info,indent=2)+'\n')
    (out/'sources.tcl').write_text('set rtl_files [list '+ ' '.join('{'+str(x.resolve())+'}' for x in sorted((out/'rtl').iterdir()))+']\n')
    make_abi_header(out)
    return info


def decl(direction,width,name): return f'{direction} wire '+(f'[{width-1}:0] ' if width>1 else '')+name


def render_wrapper(info,p,prefixes):
    bus_names='s_axi_control:'+':'.join(prefixes)
    decls=[f'(* X_INTERFACE_INFO = "xilinx.com:signal:clock:1.0 ap_clk CLK", X_INTERFACE_PARAMETER = "ASSOCIATED_BUSIF {bus_names}, ASSOCIATED_RESET ap_rst_n" *) '+decl('input',1,'ap_clk'),
           '(* X_INTERFACE_INFO = "xilinx.com:signal:reset:1.0 ap_rst_n RST", X_INTERFACE_PARAMETER = "POLARITY ACTIVE_LOW" *) '+decl('input',1,'ap_rst_n')]
    decls += [decl(d,w,'s_axi_control_'+n) for n,d,w in CONTROL]
    for prefix in prefixes:
        decls += [decl(d,64 if suffix in ('araddr','awaddr') else p[prefix+'_'+suffix][1],prefix+'_'+suffix) for suffix,(d,_) in AXI.items()]
    lines=['module fpga_kernel(\n '+',\n '.join(decls)+'\n);',
           f"wire [{len(prefixes)*64-1}:0] bases; wire [31:0] n; wire start_core,done_core;",
           f'wire [{len(prefixes)-1}:0] drained,errors;']
    control=['.clk(ap_clk)','.resetn(ap_rst_n)']+[f'.s_axi_control_{n}(s_axi_control_{n})' for n,_,_ in CONTROL]
    control += ['.bases(bases)','.n(n)','.start_core(start_core)','.done_core(done_core)', '.drained(&drained)','.memory_error(|errors)',
                '.busy()','.core_done()','.drain_done()','.core_cycles()','.drain_cycles()']
    lines+= [f"fpga_control #(.BANKS({len(prefixes)})) control("+', '.join(control)+');']
    connects=['.clock(ap_clk)','.reset(ap_rst_n)','.start_port(start_core)','.done_port(done_core)','.idle_port()']
    connects += [f'.{name}(32\'h{value:08x})' for name,value in info['pointers'].items()]
    if 'n' in p: connects.append('.n(n)')
    for i,prefix in enumerate(prefixes):
        bank=i  # independent base register per AXI interface; shared-BO aliasing is configured by host
        logical=info['logical_base']//info['banks']
        for suffix in AXI:
            name=prefix+'_'+suffix
            if suffix in ('araddr','awaddr'):
                width=p[name][1]
                lines += [f'wire [{width-1}:0] raw_{name};',
                          f"assign {name}=bases[{bank*64}+:64]+({{{{{64-width}{{1'b0}}}},raw_{name}}}-64'h{logical:016x});"]
                connects.append(f'.{name}(raw_{name})')
            else: connects.append(f'.{name}({name})')
        if prefix in p: connects.append(f'.{prefix}()')
        def handshake(channel):return f'({prefix}_{channel}valid && {prefix}_{channel}ready)'
        lines.append(f'''fpga_drain drain_{i}(.clk(ap_clk),.resetn(ap_rst_n),
 .ar({handshake('ar')}),.rlast({handshake('r')} && {prefix}_rlast),
 .aw({handshake('aw')}),.w({handshake('w')}),.wlast({prefix}_wlast),.b({handshake('b')}),
 .arvalid({prefix}_arvalid),.awvalid({prefix}_awvalid),.wvalid({prefix}_wvalid),
 .rvalid({prefix}_rvalid),.bvalid({prefix}_bvalid),.accepted_idle(),.pending_requests(),
 .response_error(({handshake('r')} && {prefix}_rresp[1])||({handshake('b')} && {prefix}_bresp[1])),
 .drained(drained[{i}]),.error(errors[{i}]));''')
    lines.append(info['top']+' core('+',\n '.join(connects)+');\nendmodule\n')
    return '\n'.join(lines)


def make_abi_header(out):
    lines=['#pragma once','#include <cstdint>','namespace abi {']
    lines += [f'constexpr unsigned {k} = {v};' for group in ('registers','status') for k,v in ABI[group].items()]
    lines+=['constexpr unsigned GUARD = '+str(ABI['guard_bytes'])+';','}']
    (Path(out)/'abi.hpp').write_text('\n'.join(lines)+'\n')
