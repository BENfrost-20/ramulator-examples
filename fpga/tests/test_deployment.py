import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from fpga.catalog import registry,select,SMALL
from fpga.prepare import AXI,ABI,layout,ports,verify,render_wrapper,bounded_log2
from fpga.hostgen import write as hostgen
from fpga.run import board,receipt,registers


def fixture(banked=False):
    info=layout(registry()['memory_probe_banked' if banked else 'memory_probe_single'])
    p={'clock':('input',1),'reset':('input',1),'start_port':('input',1),'done_port':('output',1),'idle_port':('output',1),'data':('input',32),'n':('input',32)}
    for i in range(info['banks']):
        prefix='m_axi_'+str(i);p[prefix]=('output',1)
        p.update({prefix+'_'+s:(d,31 if banked and s in ('araddr','awaddr') else 2 if banked and s in ('arid','rid','awid','bid') else w) for s,(d,w) in AXI.items()})
    body='\n'.join(f'{d} '+(f'[{w-1}:0] ' if w>1 else '')+n+';' for n,(d,w) in p.items())
    return 'module memory_probe('+','.join(p)+');\n'+body+"\nalways @(posedge clock) if(reset == 1'b0) begin end\nendmodule",info


class DeploymentTests(unittest.TestCase):
    def test_registry_preserves_recipe(self):
        cases=registry();self.assertEqual(len(cases),145)
        flags=cases['t06_byte_lanes']['flags']
        self.assertIn('-DPATTERN=6',flags);self.assertIn('--compiler=I386_CLANG13',flags)
        self.assertIn('--bus-pipelined',flags)
        self.assertEqual(cases['smoke_axi_1ch']['clock_period_ns'],10)
        self.assertEqual(len(select()),2)
        self.assertEqual(len(select(all_supported=True)),8)
    def test_selection_never_substitutes(self):
        with self.assertRaisesRegex(ValueError,'not yet implemented'): select(['t10_*'])
        with self.assertRaisesRegex(ValueError,'No registered case'): select(['typo'])
        self.assertEqual([c['name'] for c in select(['t0[23]*'])],['t02_single_read','t03_read_after_write'])
    def test_contract_rejects_unknown_port_width_reset(self):
        text,info=fixture();p,prefix=verify(text,info);self.assertEqual(prefix,['m_axi_0'])
        for old,new in [('input reset;','input [1:0] reset;'),("1'b0","1'b1"),('output [31:0] m_axi_0_wdata;','output [63:0] m_axi_0_wdata;')]:
            with self.assertRaises(ValueError):verify(text.replace(old,new),info)
    def test_high_physical_addresses_and_compaction(self):
        for banked in (False,True):
            text,info=fixture(banked);p,prefix=verify(text,info)
            wrapper=render_wrapper(info,p,prefix)
            self.assertIn('[63:0] m_axi_0_araddr',wrapper)
            logical=info['logical_base']//info['banks']
            self.assertIn(f"64'h{logical:016x}",wrapper)
        # Independent byte-wise forward/inverse at all stripe boundaries.
        for size in [0,1,255,256,257,511,512,513,2052]:
            source=bytes((i*17)%256 for i in range(size));banks=[bytearray(),bytearray()]
            for i,x in enumerate(source): banks[(i//256)%2].append(x)
            for i,x in enumerate(source):
                local=(i//512)*256+i%256
                self.assertEqual(banks[(i//256)%2][local],x)
            self.assertEqual(sum(map(len,banks)),size)
    def test_incomplete_board_fails_without_fallback(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'boards.json';path.write_text('{}')
            with patch.dict(os.environ,{'FPGA_PROFILE':str(path)}):
                with self.assertRaisesRegex(ValueError,'add deployment metadata'):board('xcu55c')
            path.write_text(json.dumps({'xcu55c':dict(vendor='intel',part='x',tools='x',memory_kind='DDR',resources=[],platform_env='X',model_ip='x')}))
            with patch.dict(os.environ,{'FPGA_PROFILE':str(path)}):
                with self.assertRaisesRegex(ValueError,'technically unsupported'):board('xcu55c')
    def test_xclbin_topology_is_not_index_assumption(self):
        src=(ROOT/'fpga/host/host.cpp').read_text()
        self.assertIn('get_mems()',src);self.assertIn('get_index()',src)
        self.assertNotIn('group_id(',src)
    def test_native_cpp_pack_alias_and_guards(self):
        # Exercise real shared host packing code on random byte lengths, partial
        # stripes and unaligned tails, plus multiple pointer aliasing in one slab.
        with tempfile.TemporaryDirectory() as td:
            out=Path(td);src=out/'test.cpp'
            src.write_text(r'''#include "buffers.hpp"
#include <cassert>
int main(){for(unsigned n=0;n<4097;++n){Bytes b(n);for(unsigned i=0;i<n;++i)b[i]=(i*31+n)&255;for(unsigned banks:{1,2}){auto p=pack(b,banks);assert(unpack(p,n)==b);for(unsigned i=0;i<n;++i)assert(p[(i/256)%banks][(i/(256*banks))*256+i%256]==b[i]);}}
Bytes slab(4096,0xa5);auto* a=slab.data()+256;auto* alias=a+4;alias[0]=17;assert(a[4]==17&&slab[255]==0xa5&&slab[512]==0xa5);
bool failed=false;try{unpack({Bytes(1),Bytes(1)},513);}catch(...){failed=true;}assert(failed);}
''')
            subprocess.run(['c++','-std=c++17','-I'+str(ROOT/'fpga/host'),str(src),'-o',str(out/'test')],check=True)
            subprocess.run([out/'test'],check=True)
    def test_oracle_checks_original_micro(self):
        with tempfile.TemporaryDirectory() as td:
            case=registry()['t03_read_after_write'];info=layout(case);hostgen(case,info,td)
            header=(Path(td)/'case.hpp').read_text()
            self.assertIn('/micro/check.c',header);self.assertIn('/micro/pattern.c',header)
            self.assertEqual(info['buffers']['in'][2],'inout')
    def test_register_metadata_uses_abi(self):
        with tempfile.TemporaryDirectory() as td:
            text,info=fixture();info['axi_ports']=['m_axi_0'];registers(info,Path(td))
            t=(Path(td)/'registers.tcl').read_text()
            self.assertIn('address_offset '+str(ABI['registers']['CORE_CYCLES']),t)
            self.assertIn('ASSOCIATED_BUSIF',t)


class ProvenanceTests(unittest.TestCase):
    def test_actual_banner_shape_abbreviated_full_and_unknown(self):
        from fpga.provenance import banner_revision
        self.assertEqual(banner_revision('Version: PandA 2026.11 - Revision d1975e817-feature/ramulator'),'d1975e817')
        self.assertEqual(banner_revision('Version: PandA - Revision '+('a'*40)+'-main'),'a'*40)
        self.assertIsNone(banner_revision('Version: PandA - Revision unknown-trunk'))
    def test_hardware_not_coupled_to_ramulator_revision(self):
        config=json.loads((ROOT/'fpga/toolchain.json').read_text())
        self.assertIn('cda4db2e724df357f749c0c41b12bdc065462ced',config['hardware_accepted_revisions'])
        self.assertEqual(config['bambu']['ref'],'feature/ramulator')
        self.assertEqual(config['ramulator2']['revision'],'9a8ed857455d041524043bc5fb45eb7f07e6a731')

if __name__=='__main__': unittest.main()
