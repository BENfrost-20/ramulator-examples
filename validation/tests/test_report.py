import unittest
from validation.report import eligible,compare
from validation.vendor import SUPPORTED,validate

class ReportTests(unittest.TestCase):
    def record(self,mode='bambu_ramulator'):
        return dict(case='memory_probe_single',n=513,mode=mode,functional_status='pass',core_cycles=100,drain_cycles=102,
                    source_fingerprint='src',rtl_fingerprint='rtl',input_fingerprint='input',kernel_mhz=100,measurement='D-S',
                    observation_boundary='wrapper/platform AXI',alignment_status='verified',model={'fidelity_verified':True})
    def test_no_predetermined_agreement_or_latency_adjustment(self):
        a=self.record();b=self.record('vendor_memory_reference');b['core_cycles']=250
        p=compare([a,b])[0];self.assertEqual(p['cycle_ratio_left_over_right'],0.4);self.assertEqual(p['cycle_difference_left_minus_right'],-150)
    def test_no_missing_fingerprint_or_emulation_fidelity(self):
        a=self.record();b=self.record('hw_emu')
        self.assertTrue(eligible(a,b));b=self.record('vendor_memory_reference');b['input_fingerprint']=None
        self.assertTrue(eligible(a,b));b['input_fingerprint']='input';b['alignment_status']='unverified'
        self.assertTrue(eligible(a,b))
    def test_different_wrappers_not_same_rtl(self):
        a=self.record();b=self.record('physical_board');b['rtl_fingerprint']='other'
        self.assertIn('unaligned/missing rtl_fingerprint',eligible(a,b))
    def test_old_simulator_rejected_before_license_or_build(self):
        for sim,version in [('questa','10.7c'),('vcs','V-2023.12')]:
            with self.assertRaisesRegex(ValueError,'requires'):validate({'simulator':sim,'simulator_release':version},sim)

if __name__=='__main__':unittest.main()
