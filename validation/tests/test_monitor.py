import unittest
from validation.axi_monitor import AXIMonitor


def req(id,addr=0,length=0,size=2,burst=1):return {'id':id,'addr':addr,'len':length,'size':size,'burst':burst}

class MonitorTests(unittest.TestCase):
    def test_ids_bursts_and_backpressure(self):
        m=AXIMonitor()
        for e in [dict(cycle=0,ar=req(1,length=1)),dict(cycle=1,ar=req(2)),
                  dict(cycle=2,r={'id':2,'last':True},stalls=['aw']),
                  dict(cycle=3,r={'id':1,'last':False},aw=req(0),w={'strb':15,'last':True}),dict(cycle=6,r={'id':1,'last':True},b={'id':0})]:m.feed(e)
        r=m.finish();self.assertEqual(r['counts']['read_bytes'],12)
        self.assertEqual(r['latency']['read_first']['samples'],[1,3])
        self.assertEqual(r['latency']['read_final']['samples'],[1,6])
        self.assertEqual(r['backpressure_cycles'],{'aw':1})
    def test_w_before_aw_independent_b_ids(self):
        m=AXIMonitor()
        for e in [dict(cycle=0,w={'strb':15,'last':False}),dict(cycle=1,w={'strb':3,'last':True}),
                  dict(cycle=2,aw=req(3,length=1)),dict(cycle=3,aw=req(4)),
                  dict(cycle=4,w={'strb':15,'last':True}),dict(cycle=5,b={'id':4,'resp':0}),
                  dict(cycle=7,b={'id':3,'resp':2})]:m.feed(e)
        r=m.finish();self.assertEqual(r['counts']['write_bytes'],10)
        self.assertEqual(r['counts']['response_errors'],1)
        self.assertEqual(r['latency']['write_b']['samples'],[2,5])
    def test_byte_lane_and_same_id_order(self):
        m=AXIMonitor();m.feed(dict(cycle=0,aw=req(0,addr=3,size=0),w={'strb':8,'last':True}))
        m.feed(dict(cycle=1,b={'id':0}));self.assertEqual(m.finish()['counts']['write_bytes'],1)
        m=AXIMonitor();m.feed(dict(cycle=0,ar=req(0,length=1)))
        with self.assertRaisesRegex(ValueError,'RLAST'):m.feed(dict(cycle=1,r={'id':0,'last':True}))
    def test_protocol_failures_not_silent(self):
        for events in [[dict(cycle=0,b={'id':0})],
                       [dict(cycle=0,aw=req(0)),dict(cycle=1,b={'id':0})],
                       [dict(cycle=0,aw=req(0,addr=1,size=0),w={'strb':1,'last':True})]]:
            m=AXIMonitor()
            with self.assertRaises(ValueError):
                for e in events:m.feed(e)
        m=AXIMonitor();m.feed(dict(cycle=0,ar=req(0)))
        with self.assertRaisesRegex(ValueError,'outstanding'):m.finish()
    def test_wrap_and_narrow(self):
        m=AXIMonitor()
        m.feed(dict(cycle=0,aw=req(0,addr=2,length=1,size=1,burst=2)))
        m.feed(dict(cycle=1,w={'strb':12,'last':False}))
        m.feed(dict(cycle=2,w={'strb':3,'last':True}))
        m.feed(dict(cycle=3,b={'id':0}));self.assertEqual(m.finish()['counts']['write_bytes'],4)
    def test_same_id_read_responses_ordered(self):
        m=AXIMonitor();m.feed(dict(cycle=0,ar=req(0)));m.feed(dict(cycle=1,ar=req(0)))
        m.feed(dict(cycle=2,r={'id':0,'last':True}));m.feed(dict(cycle=5,r={'id':0,'last':True}))
        self.assertEqual(m.finish()['latency']['read_final']['samples'],[2,4])

    def test_pending_valid_and_unaligned_boundary(self):
        m=AXIMonitor();m.feed(dict(cycle=0,stalls=['w']))
        with self.assertRaisesRegex(ValueError,'outstanding'):m.finish()
        with self.assertRaisesRegex(ValueError,'withdrawn'):m.feed(dict(cycle=1))
        m=AXIMonitor();m.feed(dict(cycle=0,ar=req(0,addr=4093,size=2)))
        m.feed(dict(cycle=1,r={'id':0,'last':True}))
        self.assertEqual(m.finish()['counts']['read_bytes'],3)

if __name__=='__main__':unittest.main()
