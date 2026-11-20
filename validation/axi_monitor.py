"""Passive AXI4 handshake analysis, including IDs, bursts and independent AW/W.
Input JSONL: cycle and optional ar/r/aw/w/b dictionaries are accepted handshakes
only; stalls is a list of channels with VALID&&!READY at that edge.
Latency endpoints are accepted handshakes, not first assertion of VALID.
"""
from collections import defaultdict,deque
import json


class AXIMonitor:
    def __init__(self,data_bytes=4):
        self.width=data_bytes;self.reads=defaultdict(deque);self.writes=defaultdict(deque)
        self.aw_order=deque();self.wbeats=deque();self.previous=-1;self.pending=set()
        self.counts=dict(accepted_ar=0,accepted_aw=0,completed_r=0,completed_b=0,r_beats=0,w_beats=0,read_bytes=0,write_bytes=0,response_errors=0)
        self.latencies={'read_first':[],'read_final':[],'write_b':[],'write_first_w_to_b':[],'write_last_w_to_b':[]}
        self.stalls=defaultdict(int)

    def request(self,item,cycle):
        r=dict(item,cycle=cycle,beats=0,first=None)
        for key in ('id','addr','len','size'): r[key]=int(r[key])
        r['burst']=int(r.get('burst',1))
        if not (0<=r['len']<=255 and 0<=r['size']<=7 and 1<<r['size']<=self.width): raise ValueError('Invalid burst length/transfer width')
        if r['burst'] not in (0,1,2): raise ValueError('Reserved AXI burst type')
        if r['burst']==0 and r['len']>=16:raise ValueError('FIXED bursts cannot exceed 16 beats')
        if r['burst']==2 and (r['len']+1 not in (2,4,8,16) or r['addr']%(1<<r['size'])): raise ValueError('Invalid WRAP burst')
        if r['burst']==1 and (r['addr']//4096!=((r['addr']//(1<<r['size']))*(1<<r['size'])+(r['len']+1)*(1<<r['size'])-1)//4096): raise ValueError('AXI burst crosses 4 KiB')
        return r

    def advance_w(self):
        while self.aw_order and self.wbeats:
            request=self.aw_order[0];beat=self.wbeats.popleft();request['beats']+=1
            if request['beats']==1:request['first_w_cycle']=beat['cycle']
            if bool(beat.get('last'))!=(request['beats']==request['len']+1): raise ValueError('WLAST does not match AWLEN')
            strb=int(beat['strb']);size=1<<request['size'];index=request['beats']-1
            addr=request['addr'] if request['burst']==0 or index==0 else (request['addr']//size)*size+index*size
            if request['burst']==2:
                span=(request['len']+1)*size;addr=(request['addr']//span)*span+(addr%span)
            lane=addr%self.width;valid=((1<<(size-addr%size))-1)<<lane
            if strb<0 or strb>=1<<self.width or strb&~valid: raise ValueError('WSTRB outside transfer byte lanes')
            self.counts['write_bytes']+=bin(strb).count('1')
            if request['beats']==request['len']+1:
                request['w_complete']=True;request['last_w_cycle']=beat['cycle'];self.aw_order.popleft()

    def feed(self,event):
        cycle=int(event['cycle'])
        if cycle<=self.previous: raise ValueError('Trace must contain strictly increasing clock edges per AXI port')
        self.previous=cycle
        stalled=set(event.get('stalls',[]))
        for ch in self.pending-stalled:
            if ch not in event:raise ValueError('Pending VALID withdrawn without a handshake on '+ch)
        self.pending=stalled
        for ch in event.get('stalls',[]):
            if ch not in ('ar','r','aw','w','b'): raise ValueError('Unknown channel '+ch)
            self.stalls[ch]+=1
        for channel,queues in (('ar',self.reads),('aw',self.writes)):
            if channel in event:
                req=self.request(event[channel],cycle);queues[req['id']].append(req)
                self.counts['accepted_'+channel]+=1
                if channel=='aw': self.aw_order.append(req)
        if 'w' in event:
            self.counts['w_beats']+=1;self.wbeats.append(dict(event['w'],cycle=cycle))
        self.advance_w()
        if 'r' in event:
            r=event['r'];queue=self.reads[int(r['id'])]
            if not queue: raise ValueError('RID without accepted AR')
            req=queue[0];req['beats']+=1;self.counts['r_beats']+=1
            if req['first'] is None:
                req['first']=cycle;self.latencies['read_first'].append(cycle-req['cycle'])
            if bool(r.get('last'))!=(req['beats']==req['len']+1): raise ValueError('RLAST does not match ARLEN')
            size=1<<req['size'];unaligned=req['addr']%size if req['beats']==1 or req['burst']==0 else 0
            self.counts['read_bytes']+=size-unaligned
            self.counts['response_errors']+=int(bool(int(r.get('resp',0))&2))
            if r.get('last'):
                queue.popleft();self.counts['completed_r']+=1;self.latencies['read_final'].append(cycle-req['cycle'])
        if 'b' in event:
            b=event['b'];queue=self.writes[int(b['id'])]
            if not queue: raise ValueError('BID without accepted AW')
            req=queue[0]
            if not req.get('w_complete'): raise ValueError('B before final W handshake')
            queue.popleft();self.counts['completed_b']+=1;self.counts['response_errors']+=int(bool(int(b.get('resp',0))&2))
            self.latencies['write_b'].append(cycle-req['cycle'])
            self.latencies['write_first_w_to_b'].append(cycle-req['first_w_cycle'])
            self.latencies['write_last_w_to_b'].append(cycle-req['last_w_cycle'])

    def finish(self):
        if any(self.reads.values()) or any(self.writes.values()) or self.aw_order or self.wbeats or self.pending: raise ValueError('Trace ended with outstanding/incomplete transactions')
        def summary(xs):
            s=sorted(xs)
            return {'count':len(s),'min':s[0] if s else None,'max':s[-1] if s else None,'mean':sum(s)/len(s) if s else None,'samples':s}
        return {'boundary':'wrapper/platform AXI; VALID && READY only','latency_units':'kernel clock cycles',
                'counts':self.counts,'backpressure_cycles':dict(self.stalls),'latency':{k:summary(v) for k,v in self.latencies.items()}}


def analyze(path,data_bytes=4):
    monitor=AXIMonitor(data_bytes)
    for line in open(path):
        if line.strip(): monitor.feed(json.loads(line))
    return monitor.finish()
