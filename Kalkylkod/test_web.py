import http.client
import json
import queue
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
import server as app
from amplitude_index import AutoAmplitudeTracker, amplitude_index


class WebTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.http=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler)
        cls.thread=threading.Thread(target=cls.http.serve_forever,daemon=True); cls.thread.start()
    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown(); cls.http.server_close(); cls.thread.join()
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); app.DATA=Path(self.temp.name)
        app.STATE.update(active=False,status='Redo',t=[],pin=[],config={},result=None,error=None,
                         reference=None,last_sample_at=None,pending=None,tracker=None)
    def tearDown(self): self.temp.cleanup()
    def call(self,path,data=None,token=True):
        conn=http.client.HTTPConnection('127.0.0.1',self.http.server_port)
        headers={'Host':'127.0.0.1:8000'}
        if token: headers['X-EMG-Token']=app.TOKEN
        conn.request('GET' if data is None else 'POST',path,body=json.dumps(data) if data is not None else None,headers=headers)
        r=conn.getresponse(); body=r.read(); code=r.status; conn.close()
        return code,body
    def pending_from_samples(self,duration=2,gap=False):
        cfg=dict(gain=100,bias=1.65,auto_bias=False,name='Testinspelning')
        app.STATE.update(active=True,tracker=AutoAmplitudeTracker(100,None,None),config=cfg)
        q=queue.Queue()
        for i in range(int(duration*2000)):
            if gap and 100<i<250: continue
            q.put(('data',i/2000,1650+100*np.sin(2*np.pi*100*i/2000)))
        q.put(('done',)); app.process_recording(cfg,q,app.options({'bandpass':False,'notch':False},'TEST'))
        return app.STATE['pending']
    def test_page_token(self):
        code,page=self.call('/'); self.assertEqual(code,200); self.assertIn(app.TOKEN.encode(),page)
        self.assertIn(b'saveDialog',page); self.assertNotIn(b'id="setReference"',page)
        self.assertEqual(self.call('/api/demo',{},token=False)[0],403)
    def test_file_import_unchanged(self):
        t=np.arange(4000)/2000; v=1.65+.1*np.sin(2*np.pi*100*t)
        text='time voltage\n'+'\n'.join(f'{x} {y}' for x,y in zip(t,v))
        code,body=self.call('/api/file',dict(text=text,unit='V',bias=1.65,gain=100,bandpass=False,notch=False))
        self.assertEqual(code,200,body); self.assertAlmostEqual(json.loads(body)['overall_rms'],2**-.5,places=7)
    def test_finish_requires_choice_and_save_appears_in_history(self):
        p=self.pending_from_samples()
        self.assertFalse(app.STATE['active']); self.assertEqual(list(app.DATA.iterdir()),[])
        self.assertEqual(json.loads(self.call('/api/analyses')[1]),[])
        # A new recording must not silently overwrite an undecided one.
        self.assertEqual(self.call('/api/start',{})[0],400)
        self.assertEqual(self.call('/api/pending/save',{'id':p['id'],'name':''})[0],400)
        code,b=self.call('/api/pending/save',{'id':p['id'],'name':'Biceps set 2','comment':'8 kg','fatigue':'Trött'})
        self.assertEqual(code,200,b); a=json.loads(b)
        self.assertEqual(a['name'],'Biceps set 2'); self.assertEqual(a['comment'],'8 kg')
        self.assertEqual(a['fatigue'],'Trött'); self.assertIsNone(app.STATE['pending'])
        self.assertEqual(len(list(app.DATA.glob('*.txt'))),2)
        hist=json.loads(self.call('/api/analyses')[1]); self.assertEqual(hist[0]['id'],a['id'])
        self.assertEqual(hist[0]['fatigue'],'Trött')
        self.assertIn(b'RMS_mV',self.call('/export/'+a['id'])[1])
        # Retrying the save after a lost response returns the same ID, no duplicate.
        again=json.loads(self.call('/api/pending/save',{'id':p['id'],'name':'Biceps set 2'})[1])
        self.assertEqual(again['id'],a['id']); self.assertEqual(len(list(app.DATA.glob('*.json'))),1)
    def test_discard_writes_nothing(self):
        p=self.pending_from_samples()
        self.assertEqual(self.call('/api/pending/discard',{'id':p['id']})[0],200)
        self.assertIsNone(app.STATE['pending']); self.assertEqual(app.STATE['t'],[])
        self.assertEqual(list(app.DATA.iterdir()),[])
    def test_history_label_edit_and_delete(self):
        p=self.pending_from_samples()
        _,body=self.call('/api/pending/save',{'id':p['id'],'name':'Biceps','fatigue':'Lite trött'})
        a=json.loads(body)
        self.assertEqual(self.call('/api/edit',{'id':a['id'],'fatigue':'Mycket trött'})[0],200)
        self.assertEqual(json.loads(self.call('/api/analyses')[1])[0]['fatigue'],'Mycket trött')
        self.assertEqual(self.call('/api/delete',{'id':a['id']},token=False)[0],403)
        self.assertEqual(self.call('/api/delete',{'id':a['id']})[0],200)
        self.assertEqual(json.loads(self.call('/api/analyses')[1]),[])
        self.assertIsNone(json.loads(self.call('/api/status')[1])['result'])
        self.assertEqual(self.call('/api/analysis/'+a['id'])[0],400)
        self.assertTrue((app.DATA/a['raw_file']).exists())
        self.assertTrue((app.DATA/a['signal_file']).exists())
    def test_delete_other_analysis_keeps_current_result(self):
        current={'id':'a'*32}; other={'id':'b'*32}
        app.STATE['result']=current
        (app.DATA/(other['id']+'.json')).write_text(json.dumps(other))
        self.assertEqual(self.call('/api/delete',{'id':other['id']})[0],200)
        self.assertEqual(app.STATE['result'],current)
    def test_raw_save_when_analysis_fails(self):
        p=self.pending_from_samples(gap=True)
        self.assertIsNotNone(p['analysis_error']); self.assertEqual(list(app.DATA.iterdir()),[])
        code,b=self.call('/api/pending/save',{'id':p['id'],'name':'Avbruten mätning'})
        self.assertEqual(code,200,b); a=json.loads(b); self.assertFalse(a['analysis_available'])
        self.assertTrue((app.DATA/a['raw_file']).exists()); self.assertNotIn('signal_file',a)
    def test_save_failure_preserves_pending_and_retries(self):
        p=self.pending_from_samples()
        with patch.object(app.np,'savetxt',side_effect=OSError('Disk full')):
            self.assertEqual(self.call('/api/pending/save',{'id':p['id'],'name':'Retry'})[0],400)
        self.assertIsNotNone(app.STATE['pending']); self.assertEqual(list(app.DATA.iterdir()),[])
        self.assertEqual(self.call('/api/pending/save',{'id':p['id'],'name':'Retry'})[0],200)
    def test_timed_tcp_recording(self):
        sock=socket.socket(); sock.bind(('127.0.0.1',0)); sock.listen(1)
        port=sock.getsockname()[1]
        def sender():
            conn,_=sock.accept()
            with conn:
                conn.sendall(b'#synthetic\n'+b''.join(f'{i*500} {1650+100*np.sin(2*np.pi*100*i/2000)}\n'.encode() for i in range(2001)))
            sock.close()
        th=threading.Thread(target=sender,daemon=True); th.start()
        self.assertEqual(self.call('/api/start',dict(host='127.0.0.1',port=port,duration=1))[0],200)
        for _ in range(150):
            if not json.loads(self.call('/api/status')[1])['active']: break
            time.sleep(.02)
        self.assertFalse(app.STATE['active']); self.assertIsNotNone(app.STATE['pending'])
        self.assertEqual(list(app.DATA.iterdir()),[]); th.join(1)
    def test_manual_stop_and_reloaded_page_still_offer_save(self):
        self.assertEqual(self.call('/api/demo',{})[0],200)
        time.sleep(.55)
        self.assertEqual(self.call('/api/stop',{})[0],200)
        for _ in range(150):
            if not app.STATE['active']: break
            time.sleep(.02)
        self.assertFalse(app.STATE['active']); self.assertIsNotNone(app.STATE['pending'])
        p1=json.loads(self.call('/api/status')[1])['pending']
        self.call('/') # Reload does not consume a pending recording.
        p2=json.loads(self.call('/api/status')[1])['pending']; self.assertEqual(p1['id'],p2['id'])
        self.assertEqual(list(app.DATA.iterdir()),[])
    def test_stale_index_hides_value(self):
        tr=AutoAmplitudeTracker(100,None,None)
        for i in range(24001):
            t=i/2000; tr.add(t,1650+(1 if t<3 else 100)*np.sin(2*np.pi*100*t))
        app.STATE.update(tracker=tr,active=True,last_sample_at=time.monotonic()-3)
        self.assertIsNone(app.status()['index']['score'])


class TrackerTests(unittest.TestCase):
    def feed(self,tr,start,end,amplitude,jitter=False):
        for i in range(int(start*2000),int(end*2000)):
            t=i/2000+(.00015 if jitter and i%2 else 0)
            tr.add(t,1650+amplitude*np.sin(2*np.pi*100*t))
    def test_auto_rest_activity_increase_and_rest(self):
        tr=AutoAmplitudeTracker(100)
        self.feed(tr,0,3,1); self.assertIsNone(tr.reference)
        self.feed(tr,3,7,100); self.assertIsNotNone(tr.reference)
        self.assertAlmostEqual(tr.index['score'],0,delta=1)
        fixed=dict(tr.reference)
        self.feed(tr,7,12,150); self.assertAlmostEqual(tr.index['score'],50,delta=1)
        self.assertEqual(tr.reference,fixed) # never learns the increase as a new baseline
        self.feed(tr,12,14,1); self.assertIsNone(tr.index['score'])
        self.feed(tr,14,18,150); self.assertAlmostEqual(tr.index['score'],50,delta=1)
    def test_only_rest_never_creates_reference(self):
        tr=AutoAmplitudeTracker(100); self.feed(tr,0,15,1)
        self.assertIsNone(tr.reference); self.assertIsNone(tr.index['score'])
    def test_jitter_and_intermittent_curls(self):
        tr=AutoAmplitudeTracker(100); self.feed(tr,0,3,1,True)
        for t in range(3,12): self.feed(tr,t,t+1,100 if t%2 else 1,True)
        self.assertIsNotNone(tr.reference)
    def test_old_adc_gate_no_longer_rejects_c6_signal(self):
        tr=AutoAmplitudeTracker(100); self.feed(tr,0,3,1)
        self.feed(tr,3,8,1000) # max 2650 mV, valid C6 range, old 2450 gate failed
        self.assertIsNotNone(tr.reference)
    def test_rail_signal_is_blocked(self):
        tr=AutoAmplitudeTracker(100); self.feed(tr,0,3,1)
        for i in range(6000,16001): tr.add(i/2000,3300)
        self.assertIsNone(tr.reference); self.assertIsNone(tr.index['score'])
        self.assertIn('ADC',tr.index['label'])
    def test_relative_formula(self):
        ref=dict(rms=1,mav=.8)
        self.assertEqual(amplitude_index(1.5,1.2,ref)['score'],50)
        self.assertEqual(amplitude_index(2,1.6,ref)['score'],100)

if __name__=='__main__': unittest.main()
