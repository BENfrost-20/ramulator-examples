import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from validation.build_reference import validate,emit_tb,emit_tcl

ROOT=Path(__file__).resolve().parents[2]

class ReferenceGeneratorTests(unittest.TestCase):
    def model(self):
        c=json.loads((ROOT/'validation/profiles/hbm-reference.example.json').read_text())
        c.update(memory_mhz=400,apb_mhz=100,reference_mhz=100,capacity_bytes=256*1024*1024)
        c['initialization']['evidence']='Synthetic test profile; not a qualified installed model'
        return c
    def info(self):return {'case':'memory_probe_single','axi_ports':['m_axi_0']}
    def test_missing_clocks_or_wrong_case_rejected(self):
        c=self.model();c['memory_mhz']=0
        with self.assertRaisesRegex(ValueError,'memory_mhz'):validate(self.info(),c)
        with self.assertRaisesRegex(ValueError,'only'):validate({'case':'smoke_axi_1ch','axi_ports':['m_axi_0']},self.model())
        c=self.model();c['initialization']['mode']='skip_calibration'
        with self.assertRaisesRegex(ValueError,'sequencer'):validate(self.info(),c)
    def test_aperture_and_guard_validation(self):
        c=self.model();c['physical_base']=c['capacity_bytes']-4
        with self.assertRaisesRegex(ValueError,'guards'):validate(self.info(),c)
    def test_loader_checker_and_no_prebuilt_project(self):
        with tempfile.TemporaryDirectory() as td:
            out=Path(td);c=self.model();profile=validate(self.info(),c)
            emit_tb(out,c,(0,65,513),2);emit_tcl(out,out,c,profile)
            tb=(out/'reference_tb.sv').read_text();tcl=(out/'build_reference.tcl').read_text()
            self.assertIn('wait(ready_sync[1])',tb)
            self.assertIn('mem_write(BASE-256+4*j,expected)',tb)
            self.assertIn('mem_read(BASE-256+4*j,value)',tb)
            self.assertIn('value!==expected',tb)
            self.assertIn('Address above verified controller aperture',tb)
            self.assertIn('core_count',tb);self.assertIn('drain_count',tb)
            line=next(s for s in tb.splitlines() if '$fwrite(fd,' in s)
            self.assertTrue(line.startswith('$fwrite(fd,"{'))
            self.assertIn('create_bd_design memory_reference',tcl)
            self.assertNotIn('open_project',tcl)
            self.assertIn('axi_dwidth_converter:2.1',tcl)
            self.assertIn('axi_clock_converter:2.1',tcl)
            self.assertIn('axi_protocol_converter:2.1',tcl)
            self.assertIn('Unconnected controller input',tcl)
            self.assertNotIn('upgrade_ip',tcl)

if __name__=='__main__':unittest.main()
