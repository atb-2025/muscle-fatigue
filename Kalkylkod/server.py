"""Local-only browser app. Run: python3 server.py, then open http://127.0.0.1:8000."""
import csv
import os
import shutil
import io
import json
import math
import queue
import re
import socket
import tempfile
import threading
import time
import uuid
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse
import numpy as np
import emg_core as core
from amplitude_index import AutoAmplitudeTracker

ROOT = Path(__file__).resolve().parent
DATA = ROOT / 'data'
LOCK = threading.RLock()
STATE = dict(active=False, status='Redo', t=[], pin=[], config={}, result=None, error=None, reference=None, last_sample_at=None, pending=None, tracker=None)
RECORDER = None
TOKEN = uuid.uuid4().hex


def number(d, key, default, lo, hi):
    x = float(d.get(key, default))
    if not math.isfinite(x) or not lo <= x <= hi:
        raise ValueError(f'{key}: ange ett värde mellan {lo} och {hi}.')
    return x


def options(d, source):
    band = None
    if d.get('bandpass', True):
        band = (number(d,'low',20,0,10000), number(d,'high',450,1,10000))
        if band[0] >= band[1]: raise ValueError('Bandpassets nedre gräns måste vara lägre än den övre.')
    return dict(value_col=1,has_time=True,time_scale=1,gain=1,dc=True,band=band,
                notch=50 if d.get('notch', True) else None,
                window_s=number(d,'window',.25,.01,30),step_s=number(d,'step',.05,.005,30),
                signal_type='sEMG',source=source,unit='mV')


def build_result(t, v, opts, name, notes):
    result = core.run_analysis(np.column_stack([t,v]),opts)
    result.update(id=uuid.uuid4().hex, name=str(name or 'EMG-mätning')[:120],
                  date=datetime.now().isoformat(timespec='seconds'),fatigue='',comment='')
    result['notes'].extend(notes)
    return result


def save_result(t, v, opts, name, notes):
    result=build_result(t,v,opts,name,notes)
    DATA.mkdir(exist_ok=True)
    (DATA/(result['id']+'.json')).write_text(json.dumps(result,allow_nan=False),encoding='utf-8')
    return result


def load_result(ident):
    if not re.fullmatch(r'[a-f0-9]{32}',ident): raise ValueError('Ogiltigt analys-ID.')
    return json.loads((DATA/(ident+'.json')).read_text(encoding='utf-8'))


def process_recording(cfg, q, opts):
    try:
        error=None
        while True:
            msg=q.get()
            with LOCK:
                if msg[0]=='data':
                    STATE['t'].append(msg[1]); STATE['pin'].append(msg[2]); STATE['last_sample_at']=time.monotonic()
                    STATE['tracker'].add(msg[1],msg[2])
                elif msg[0]=='status': STATE['status']=msg[1]
                elif msg[0]=='started': STATE['status']='Ansluten · spelar in'
                elif msg[0]=='error': error=msg[1]; break
                elif msg[0]=='done': break
        with LOCK:
            t,pin=np.array(STATE['t']),np.array(STATE['pin'])
            STATE['status']='Förbereder inspelningen'; tracker=STATE['tracker']
        if not len(t):
            raise ValueError(error or 'Inga mätvärden kom in. Det finns ingen inspelning att spara.')
        notes=[]; result=None; corrected=None; analysis_error=None
        if error: notes.append('Avbruten anslutning: '+error)
        try:
            if len(t)<50: raise ValueError('För få sampel för RMS/MAV-analys.')
            tt,pp,missing=core.regularize(t,pin)
            warnings,mean=core.esp_recording_notes(pin,cfg['bias'],cfg['auto_bias'],missing)
            notes.extend(warnings)
            bias=mean if cfg['auto_bias'] else cfg['bias']
            values=core.esp_pin_to_values(pp,cfg['gain'],bias)
            notes.append(f'Bias: {bias:.4f} V. Gain: {cfg["gain"]:g}. Små tidsvariationer interpolerade.')
            result=build_result(tt,values,opts,cfg['name'],notes)
            corrected=np.column_stack([tt,values])
        except (ValueError,TypeError) as e:
            analysis_error=str(e)
            result=dict(id=uuid.uuid4().hex,name=cfg['name'],date=datetime.now().isoformat(timespec='seconds'),
                        signal_type='sEMG',source=opts['source'],unit='mV',duration=float(t[-1]),n_samples=len(t),
                        fs=(len(t)-1)/t[-1] if t[-1]>0 else 0,overall_rms=None,overall_mav=None,
                        t=[],rms=[],mav=[],signal_t=[],signal_v=[],notes=notes+[analysis_error],fatigue='',comment='')
        result.update(analysis_available=analysis_error is None,reference=tracker.reference,
                      amplitude_history=tracker.trace,recording_settings=cfg)
        if tracker.reference:
            result['notes'].append('Automatisk amplitudreferens. Indexet är inte procent eller validerad muskeltrötthet.')
        with LOCK:
            STATE.update(pending=dict(id=result['id'],result=result,raw=np.column_stack([t,pin]),
                                      corrected=corrected,analysis_error=analysis_error,connection_error=error),
                         status='Inspelning klar · välj om du vill spara',error=None)
    except Exception as e:
        with LOCK: STATE.update(error=str(e),status='Inspelningen kunde inte slutföras')
    finally:
        with LOCK: STATE['active']=False


class DemoRecorder(threading.Thread):
    def __init__(self,cfg,q):
        super().__init__(daemon=True); self.cfg=cfg; self.q=q; self.stop_event=threading.Event()
    def run(self):
        self.q.put(('started',)); start=time.monotonic(); i=0
        while not self.stop_event.is_set() and i/2000<self.cfg['duration']:
            for j in range(i,i+500):
                t=j/2000
                amp=1 if t<3 else (100 if t<7 else min(200,100+(t-7)*20))
                self.q.put(('data',t,1650+amp*math.sin(2*math.pi*100*t)))
            i+=500
            self.stop_event.wait(max(0,start+i/2000-time.monotonic()))
        self.q.put(('done',))


def start_recording(d,demo=False):
    global RECORDER
    cfg=dict(kind='wifi',host=str(d.get('host','192.168.4.1')).strip(),
             tcp_port=int(number(d,'port',5000,1,65535)),
             duration=number(d,'duration',20,1,300),gain=number(d,'gain',101.4,.001,1e6),
             bias=number(d,'bias',1.65,0,3.3),auto_bias=bool(d.get('auto_bias',False)),
             name=str(d.get('name','EMG-inspelning'))[:120],demo=demo)
    if not cfg['host']: raise ValueError('Ange ESP32:s IP-adress.')
    opts=options(d,'SIMULERAD LIVE-DEMO' if demo else 'ESP32-C6 · Wi-Fi')
    with LOCK:
        if STATE['active']: raise ValueError('En inspelning pågår redan.')
        if STATE['pending']: raise ValueError('Spara eller kasta föregående inspelning först.')
        STATE.update(active=True,status='Ansluter…',t=[],pin=[],config=cfg,result=None,error=None,
                     reference=None,last_sample_at=None,pending=None,
                     tracker=AutoAmplitudeTracker(cfg['gain'],opts['band'],opts['notch']))
        q=queue.Queue()
        RECORDER=DemoRecorder(cfg,q) if demo else core.StreamRecorder(cfg,q)
        RECORDER.start()
        threading.Thread(target=process_recording,args=(cfg,q,opts),daemon=True).start()
    return {'ok':True,'duration':cfg['duration']}


def reset_reference():
    with LOCK:
        if not STATE['active']: raise ValueError('Kalibreringen startar automatiskt med nästa inspelning.')
        old=STATE['tracker']
        STATE['tracker']=AutoAmplitudeTracker(old.gain,old.band,old.notch)
    return {'ok':True}


def save_pending(d):
    ident=str(d.get('id','')); name=str(d.get('name','')).strip()
    if not name: raise ValueError('Ange ett namn på inspelningen.')
    with LOCK:
        pending=STATE['pending']
        if pending is None:
            # Retry after a lost HTTP response must not create a duplicate.
            return load_result(ident)
        if pending['id']!=ident: raise ValueError('Inspelningen har ändrats. Ladda om sidan.')
        result=dict(pending['result'])
        result.update(name=name[:120],comment=str(d.get('comment',''))[:2000],
                      fatigue=str(d.get('fatigue',''))[:100],saved=True)
        DATA.mkdir(exist_ok=True)
        staging=Path(tempfile.mkdtemp(prefix='.save-',dir=DATA)); committed=[]
        try:
            rawname=ident+'_raw.txt'
            np.savetxt(staging/rawname,pending['raw'],fmt='%.6f',
                       header='RAW ADC: time_s pin_mV; bias INCLUDED\n'+json.dumps(result['recording_settings']))
            result['raw_file']=rawname
            if pending['corrected'] is not None:
                name_signal=ident+'_signal.txt'
                np.savetxt(staging/name_signal,pending['corrected'],fmt='%.6f',
                           header='time_s corrected_mV; bias and gain already applied')
                result['signal_file']=name_signal
            result['notes']=result['notes']+[f'Rådata: data/{rawname}']
            (staging/(ident+'.json')).write_text(json.dumps(result,allow_nan=False),encoding='utf-8')
            # Publish metadata last so history never exposes a half-written analysis.
            for f in sorted(staging.iterdir(),key=lambda f:f.suffix=='.json'):
                dest=DATA/f.name; os.replace(f,dest); committed.append(dest)
        except Exception:
            for f in committed: f.unlink(missing_ok=True)
            raise
        finally: shutil.rmtree(staging,ignore_errors=True)
        STATE.update(pending=None,result=result,status='Sparad i Mina analyser')
        return result


def discard_pending(d):
    with LOCK:
        pending=STATE['pending']
        if pending is None: return {'ok':True}
        if pending['id']!=d.get('id'): raise ValueError('Inspelningen har ändrats.')
        STATE.update(pending=None,result=None,t=[],pin=[],tracker=None,last_sample_at=None,
                     status='Inspelningen kastades · redo för nästa',error=None)
    return {'ok':True}


def status():
    with LOCK:
        cfg=STATE['config']; tracker=STATE['tracker']
        t=np.array(STATE['t'][-20000:]); pin=np.array(STATE['pin'][-20000:])
        bias=float(np.mean(pin))/1000 if len(pin) and cfg.get('auto_bias') else cfg.get('bias',1.65)
        v=core.esp_pin_to_values(pin,cfg.get('gain',101.4),bias)
        tt,vv=core.minmax_decimate(t,v,3000) if len(t) else ([],[])
        state=tracker.snapshot() if tracker else dict(rms=None,mav=None,reference=None,
            index=dict(score=None,label='Starta inspelningen för automatisk kalibrering',ratio=None),
            calibration=dict(phase='idle',progress=0,instruction='Börja med cirka 3 s vila, sedan din övning.'),quality='')
        if STATE['active'] and STATE['last_sample_at'] and time.monotonic()-STATE['last_sample_at']>1.5:
            state['index']=dict(score=None,label='Väntar på nya data',ratio=None)
        if STATE['error']: state['index']=dict(score=None,label='Mätfel · ingen bedömning',ratio=None)
        pending=STATE['pending']; summary=None
        if pending:
            a=pending['result']; summary=dict(id=pending['id'],name=a['name'],duration=a['duration'],
                n_samples=a['n_samples'],analysis_error=pending['analysis_error'],connection_error=pending['connection_error'],
                source=a['source'])
        return dict(active=STATE['active'],status=STATE['status'],error=STATE['error'],
                    n=len(STATE['t']),elapsed=float(t[-1]) if len(t) else 0,
                    pin=float(pin[-1])/1000 if len(pin) else None,t=list(tt),v=list(vv),
                    result=STATE['result'],pending=summary,**state)


def file_analysis(d):
    text=str(d.get('text',''))
    if not text.strip(): raise ValueError('Välj en textfil med mätdata.')
    with tempfile.NamedTemporaryFile(mode='w+',encoding='utf-8',suffix='.txt') as f:
        f.write(text); f.flush(); arr=core.load_text_file(f.name)
    if not np.all(np.isfinite(arr)): raise ValueError('Filen innehåller NaN eller oändliga värden.')
    has_time=bool(d.get('has_time',True))
    col=int(number(d,'column',2 if has_time else 1,1,100))-1
    if col>=arr.shape[1] or (has_time and col==0): raise ValueError('Fel signalkolumn. Tid är kolumn 1.')
    if has_time:
        scale={'s':1,'ms':.001,'us':.000001}.get(d.get('time_unit','s'))
        if scale is None: raise ValueError('Ogiltig tidsenhet.')
        t=(arr[:,0]-arr[0,0])*scale
    else: t=np.arange(len(arr))/number(d,'fs',2000,1,100000)
    factor={'mV':1,'V':1000,'uV':.001}.get(d.get('unit','mV'))
    if factor is None: raise ValueError('Ogiltig spänningsenhet.')
    gain=number(d,'gain',1,.001,1e6); bias=number(d,'bias',0,-100,100)
    v=(arr[:,col]*factor-1000*bias)/gain
    if has_time: t,v,_=core.regularize(t,v)
    return save_result(t,v,options(d,str(d.get('filename','Textfil'))),d.get('name','Filanalys'),
                       [f'Filimport: gain {gain:g}, bias {bias:g} V; små tidsvariationer interpolerade.'])


class Handler(BaseHTTPRequestHandler):
    def log_message(self,*a): pass
    def reply(self,obj,code=200,ctype='application/json; charset=utf-8'):
        body=json.dumps(obj,allow_nan=False).encode() if ctype.startswith('application/json') else obj
        self.send_response(code); self.send_header('Content-Type',ctype)
        self.send_header('Content-Length',str(len(body))); self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff'); self.send_header('X-Frame-Options','DENY')
        self.end_headers(); self.wfile.write(body)
    def valid_host(self):
        return self.headers.get('Host','') in ('127.0.0.1:8000','localhost:8000')
    def do_GET(self):
        try:
            if not self.valid_host(): return self.reply({'error':'Local host only'},403)
            path=urlparse(self.path).path
            if path=='/':
                body=(ROOT/'index.html').read_text().replace('__TOKEN__',TOKEN).encode()
                return self.reply(body,ctype='text/html; charset=utf-8')
            if path=='/api/status': return self.reply(status())
            if path=='/api/analyses':
                rows=[]
                for f in sorted(DATA.glob('*.json'),key=lambda p:p.stat().st_mtime,reverse=True):
                    try:
                        a=json.loads(f.read_text()); rows.append({k:a.get(k) for k in ('id','name','date','overall_rms','duration','source','fatigue')})
                    except (ValueError,OSError): pass
                return self.reply(rows)
            if path.startswith('/api/analysis/'): return self.reply(load_result(path.rsplit('/',1)[1]))
            if path.startswith('/export/'):
                a=load_result(path.rsplit('/',1)[1]); f=io.StringIO(); w=csv.writer(f)
                w.writerow(['time_s','RMS_mV','MAV_mV']); w.writerows(zip(a['t'],a['rms'],a['mav']))
                return self.reply(f.getvalue().encode(),ctype='text/csv; charset=utf-8')
            self.reply({'error':'Sidan finns inte'},404)
        except (ValueError,OSError) as e: self.reply({'error':str(e)},400)
    def do_POST(self):
        try:
            if not self.valid_host() or self.headers.get('X-EMG-Token')!=TOKEN:
                return self.reply({'error':'Ladda om den lokala sidan.'},403)
            n=int(self.headers.get('Content-Length','0'))
            if n>30_000_000: raise ValueError('Filen är för stor (max 30 MB).')
            d=json.loads(self.rfile.read(n))
            if not isinstance(d,dict): raise ValueError('Ogiltig begäran.')
            path=urlparse(self.path).path
            if path=='/api/start': return self.reply(start_recording(d))
            if path=='/api/reference/reset': return self.reply(reset_reference())
            if path=='/api/pending/save': return self.reply(save_pending(d))
            if path=='/api/pending/discard': return self.reply(discard_pending(d))
            if path=='/api/stop':
                with LOCK:
                    if RECORDER: RECORDER.stop_event.set()
                return self.reply({'ok':True})
            if path=='/api/file': return self.reply(file_analysis(d))
            if path=='/api/demo': return self.reply(start_recording(dict(duration=14,gain=100,bias=1.65,name='Live-demo · simulerad signal'),demo=True))
            if path=='/api/edit':
                a=load_result(d.get('id',''))
                for k in ('name','comment','fatigue'): a[k]=str(d.get(k,a.get(k,'')))[:1000]
                (DATA/(a['id']+'.json')).write_text(json.dumps(a,allow_nan=False),encoding='utf-8')
                return self.reply(a)
            if path=='/api/delete':
                a=load_result(d.get('id','')); (DATA/(a['id']+'.json')).unlink()
                with LOCK:
                    if STATE.get('result') and STATE['result']['id']==a['id']:
                        STATE['result']=None
                return self.reply({'ok':True})
            self.reply({'error':'Okänd åtgärd'},404)
        except Exception as e: self.reply({'error':str(e)},400)


if __name__=='__main__':
    try:
        server=ThreadingHTTPServer(('127.0.0.1',8000),Handler)
    except OSError:
        raise SystemExit('Port 8000 är upptagen. Stäng en tidigare server med Ctrl+C och försök igen.')
    print('EMG-webbsidan är igång: http://127.0.0.1:8000\nBehåll terminalen öppen. Stoppa med Ctrl+C.',flush=True)
    threading.Timer(1,lambda:webbrowser.open('http://127.0.0.1:8000')).start()
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally:
        if RECORDER: RECORDER.stop_event.set()
        server.server_close()
