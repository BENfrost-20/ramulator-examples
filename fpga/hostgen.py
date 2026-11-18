"""Build input/oracle adapter using original C, and original smoke XML values."""
import json
from pathlib import Path
import xml.etree.ElementTree as ET
from fpga.prepare import ROOT, digest


ORACLE_SOURCES = {
    'calibration': ('fpga/calibration/memory_probe.c',),
    'micro': ('micro/pattern.c', 'micro/check.c'),
    'smoke': ('smoke/vector_add_axi.c', 'smoke/test_vector_add.xml'),
}


def write(case, info, out, *, require_source_hashes=False):
    out = Path(out)
    suite = case['suite']
    expected = info.get('generation', {}).get('source_sha256', {})
    hashes = {}
    for name in ORACLE_SOURCES[suite]:
        relative = Path('oracle') / name
        target = out / relative
        data = (ROOT / name).read_bytes()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        actual = digest(target)
        if (name in expected and actual != expected[name]) or (
                require_source_hashes and name.endswith('.c') and name not in expected):
            raise ValueError('Oracle source differs from hardware generation: ' + name)
        hashes[relative.as_posix()] = actual
    header=['#pragma once','#include "buffers.hpp"',
            f'constexpr const char* case_name={json.dumps(case["name"])};',
            f'constexpr unsigned case_n={info["n"]},case_banks={info["banks"]},slab_bytes=65536;']
    header += [f'constexpr unsigned case_ports={len(info.get("axi_ports",[None]*info["banks"]))};', 'constexpr unsigned base_register_bank[] = {'+','.join(map(str,info.get('base_register_banks',list(range(info['banks'])))))+'};']
    flags=[]
    if case['suite']=='calibration':
        header += ['#define main calibration_original_main','#include "oracle/fpga/calibration/memory_probe.c"','#undef main',
                   'inline void validate_n(unsigned n){if(n>8192)throw std::runtime_error("Probe N exceeds guarded slab");}',
                   'inline Bytes case_input(unsigned n,unsigned rep){Bytes b(n*4);for(unsigned i=0;i<n;++i){std::uint32_t v=7*i+3+rep*11;std::memcpy(b.data()+4*i,&v,4);}return b;}',
                   'inline Bytes case_expected(Bytes b,unsigned n){std::vector<std::uint32_t> w(n);if(n)std::memcpy(w.data(),b.data(),b.size());memory_probe(w.data(),n);if(n)std::memcpy(b.data(),w.data(),b.size());return b;}']
    elif case['suite']=='micro':
        flags=['-D'+k+'='+v for k,v in info['defines'].items()]
        header += ['#include "oracle/micro/pattern.c"','#define main micro_original_main','#include "oracle/micro/check.c"','#undef main',
                   'inline void validate_n(unsigned n){if(n!=case_n)throw std::runtime_error("Case has fixed dimensions");}',
                   f'inline Bytes case_input(unsigned,unsigned){{Bytes b({info["buffers"]["out"][0]+info["buffers"]["out"][1]},0);for(unsigned i=0;i<WORDS;++i){{auto v=initial(i);std::memcpy(b.data()+256+4*i,&v,4);}}return b;}}',
                   f'inline Bytes case_expected(Bytes b,unsigned){{std::vector<std::uint32_t> a(WORDS),o(OUT_WORDS);std::memcpy(a.data(),b.data()+256,WORDS*4);memory_pattern(a.data(),o.data());for(unsigned i=0;i<OUT_WORDS;++i)if(o[i]!=expected(i))throw std::runtime_error("Original oracle failed");std::memcpy(b.data()+256,a.data(),WORDS*4);std::memcpy(b.data()+{info["buffers"]["out"][0]},o.data(),OUT_WORDS*4);return b;}}']
    else:
        tb=ET.parse(out/'oracle/smoke/test_vector_add.xml').getroot().find('testbench')
        vals={k:[int(s.strip()) for s in tb.attrib[k].strip('{}').split(',')] for k in ('vec_a','vec_b','vec_c')}
        header += ['#include "oracle/smoke/vector_add_axi.c"',
                   'inline void validate_n(unsigned n){if(n!=case_n)throw std::runtime_error("Smoke uses original XML dimensions");}',
                   'inline Bytes case_input(unsigned,unsigned){Bytes b(1312,0);']
        for name,offset in (('vec_a',256),('vec_b',768),('vec_c',1280)):
            header += ['{ const int v[] = {'+','.join(map(str,vals[name]))+'};std::memcpy(b.data()+'+str(offset)+',v,sizeof(v));}']
        header += ['return b;}',
                   'inline Bytes case_expected(Bytes b,unsigned n){std::vector<int>a(n),v(n),c(n);std::memcpy(a.data(),b.data()+256,n*4);std::memcpy(v.data(),b.data()+768,n*4);vector_add(a.data(),v.data(),c.data(),n);std::memcpy(b.data()+1280,c.data(),n*4);return b;}']
    (out/'case.hpp').write_text('\n'.join(header)+'\n')
    (out/'host-flags.json').write_text(json.dumps(flags)+'\n')
    hashes.update({name: digest(out / name) for name in ('case.hpp', 'host-flags.json')})
    return hashes
