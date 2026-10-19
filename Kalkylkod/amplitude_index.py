"""Automatic relative amplitude indicator. Not a validated fatigue classifier."""
from collections import deque
import math
import numpy as np
import emg_core as core


def amplitude_index(rms, mav, reference):
    if reference is None:
        return dict(score=None,label='Kalibrerar automatiskt',ratio=None)
    r0,m0=reference['rms'],reference['mav']
    if not all(math.isfinite(x) and x>1e-9 for x in (r0,m0)):
        return dict(score=None,label='Referensen är för svag',ratio=None)
    if not all(math.isfinite(x) and x>=0 for x in (rms,mav)):
        return dict(score=None,label='Ingen giltig signal',ratio=None)
    ratio=.5*(rms/r0+mav/m0)
    if ratio<.25: return dict(score=None,label='Vila · ingen bedömning',ratio=ratio)
    score=min(100.,max(0.,100*(ratio-1)))
    label='Nära referensen' if score<20 else ('Ökad amplitud' if score<60 else 'Kraftigt ökad amplitud')
    return dict(score=score,label=label,ratio=ratio)


class AutoAmplitudeTracker:
    """Fixed 250 ms frames, independent of browser polling. Baseline never adapts upward."""
    WINDOW=.25
    REST_FRAMES=8
    ACTIVE_FRAMES=12

    def __init__(self,gain,band=(20.,450.),notch=50):
        self.gain=gain; self.band=band; self.notch=notch
        self.buffer=[]; self.start=None; self.boundary=None
        self.phase='settling'; self.noise=[]; self.candidates=deque(maxlen=12)
        self.reference=None; self.smoothed=None; self.threshold=None
        self.rms=self.mav=None; self.quality='Väntar på signal'; self.progress=0
        self.index=dict(score=None,label='Väntar på signal',ratio=None)
        self.trace=[]; self.last_t=0

    def add(self,t,pin):
        if self.start is None: self.start=t; self.boundary=t+self.WINDOW
        if t>=self.boundary:
            self._frame(self.buffer)
            self.buffer=[]
            self.boundary=self.start+(math.floor((t-self.start)/self.WINDOW+1e-8)+1)*self.WINDOW
        self.buffer.append((t,pin))

    def _blocked(self,message):
        self.quality=message; self.index=dict(score=None,label=message,ratio=None)

    def _frame(self,frame):
        if not frame: return
        a=np.asarray(frame); t=a[:,0]; pin=a[:,1]; self.last_t=float(t[-1])
        if len(t)<20 or t[-1]-t[0]<.20 or np.any(np.diff(t)<=0) or np.max(np.diff(t))>.010:
            self.candidates.clear(); self._blocked('Ojämna data · kontrollera anslutningen'); return
        if np.mean((pin<=20)|(pin>=3280))>.01:
            self.candidates.clear(); self._blocked('Signal nära ADC-gränsen · kontrollera krets/bias'); return
        # Do not estimate missing samples by rounding each jittered interval.
        n=len(t); grid=np.linspace(t[0],t[-1],n); pp=np.interp(grid,t,pin)
        fs=(n-1)/(t[-1]-t[0]); v=(pp-np.mean(pp))/self.gain
        band=self.band
        if band:
            band=(band[0],min(band[1],.45*fs))
            if band[0]>=band[1]: self._blocked('För låg samplingsfrekvens'); return
        v=core.fft_filter(v,fs,band,self.notch if self.notch and self.notch<.45*fs else None)
        self.rms=float(np.sqrt(np.mean(v*v))); self.mav=float(np.mean(np.abs(v)))
        self.quality='Signal mottagen'
        pin_rms=self.rms*self.gain
        if t[-1]-self.start<.5:
            self._blocked('Låt signalen stabiliseras'); return
        if len(self.noise)<self.REST_FRAMES:
            self.phase='rest'; self.noise.append(pin_rms)
            self.progress=len(self.noise)/self.REST_FRAMES
            self.index=dict(score=None,label='Mäter vilonivå · slappna av',ratio=None)
            if len(self.noise)==self.REST_FRAMES:
                self.threshold=max(3.,2.5*float(np.median(self.noise)))
                self.phase='activity'; self.progress=0
                self.index=dict(score=None,label='Börja övningen · samlar aktiv referens',ratio=None)
            return
        if self.reference is None:
            self.phase='activity'
            if pin_rms>=self.threshold:
                self.candidates.append((self.last_t,self.rms,self.mav))
            # Avoid combining very old activity with a changed setup.
            while self.candidates and self.last_t-self.candidates[0][0]>20: self.candidates.popleft()
            self.progress=len(self.candidates)/self.ACTIVE_FRAMES
            self.index=dict(score=None,label=f'Samlar aktiv referens · {len(self.candidates)}/{self.ACTIVE_FRAMES}',ratio=None)
            if len(self.candidates)<self.ACTIVE_FRAMES: return
            values=np.array(self.candidates)
            med=np.median(values[:,1:],axis=0)
            spread=float(np.median(np.abs(values[:,1]-med[0]))/max(med[0],1e-9))
            if spread>.5:
                self.index=dict(score=None,label='Varierande aktivitet · fortsätt med jämn belastning',ratio=None); return
            self.reference=dict(rms=float(med[0]),mav=float(med[1]),time_s=self.last_t,
                                noise_pin_rms=float(np.median(self.noise)),activity_threshold_pin_mv=self.threshold,
                                method='median_12_active_250ms_windows',band=band,notch=self.notch)
            self.phase='ready'; self.smoothed=1.
        active=pin_rms>=max(self.threshold*.6,self.reference['rms']*self.gain*.25)
        if not active:
            self.index=dict(score=None,label='Vila · väntar på muskelaktivitet',ratio=None)
        else:
            ratio=.5*(self.rms/self.reference['rms']+self.mav/self.reference['mav'])
            self.smoothed=ratio if self.smoothed is None else .25*ratio+.75*self.smoothed
            self.index=amplitude_index(self.smoothed,self.smoothed,dict(rms=1.,mav=1.))
        self.trace.append(dict(time_s=self.last_t,rms=self.rms,mav=self.mav,**self.index))

    def snapshot(self):
        instructions={'settling':'Väntar på data. Slappna av när inspelningen startar.',
                      'rest':'Slappna av under de första cirka 3 sekunderna.',
                      'activity':'Börja övningen. Referensen samlas automatiskt från 3 s aktiv signal. Om inget händer: kontrollera signalen eller kalibrera om och börja i vila.',
                      'ready':'Referensen är låst för denna inspelning. Jämför samma belastning och elektrodplacering.'}
        return dict(rms=self.rms,mav=self.mav,reference=self.reference,index=dict(self.index),
                    calibration=dict(phase=self.phase,progress=self.progress,instruction=instructions[self.phase]),
                    quality=self.quality)
