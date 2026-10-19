"""Signal processing and ESP32 TCP reader, extracted from the supplied desktop app."""
import socket, threading, time
from collections import Counter
import numpy as np
MAX_DISPLAY_POINTS = 6000
ADC_LOW_MV, ADC_HIGH_MV = 20.0, 3280.0  # C6: conservative near-rail warning, not protection
def load_text_file(path):
    """Read a numeric text file. Returns an array of shape (rows, columns)."""
    rows = []
    with open(path, "r", encoding="utf-8-sig", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line or line[0] in "#%":
                continue                                   # empty / comment lines
            if ";" in line:                                # semicolons -> commas are decimals
                line = line.replace(",", ".").replace(";", " ")
            else:
                line = line.replace(",", " ")
            try:
                rows.append([float(p) for p in line.split()])
            except ValueError:
                continue                                   # header / text lines

    if not rows:
        raise ValueError("No numeric data found in the file.")

    # keep only rows with the most common number of columns
    ncols = Counter(len(r) for r in rows).most_common(1)[0][0]
    rows = [r for r in rows if len(r) == ncols]
    return np.array(rows, dtype=float)

def _smoothstep(u):
    u = np.clip(u, 0.0, 1.0)
    return 0.5 - 0.5 * np.cos(np.pi * u)

def fft_filter(x, fs, band=None, notch_hz=None):
    """
    Zero-phase band-pass and/or notch filter done in the frequency domain.
    (Zero-phase = the signal is not shifted in time, which suits offline analysis.)
    """
    n = len(x)
    X = np.fft.rfft(x)
    f = np.fft.rfftfreq(n, d=1.0 / fs)
    gain = np.ones_like(f)

    if band is not None:
        lo, hi = band
        if lo > 0:
            w = max(lo * 0.25, 0.5)                              # soft edge width (Hz)
            gain *= _smoothstep((f - (lo - w / 2)) / w)
        w = max(hi * 0.10, 0.5)
        gain *= 1.0 - _smoothstep((f - (hi - w / 2)) / w)

    if notch_hz is not None:
        sigma = 0.8                                              # notch width (Hz)
        gain *= 1.0 - np.exp(-0.5 * ((f - notch_hz) / sigma) ** 2)

    return np.fft.irfft(X * gain, n=n)

def sliding_rms_mav(t, v, window_s, step_s):
    """
    Calculate RMS and MAV over a sliding window.
    Each value covers the last 'window_s' seconds up to the time t_end.
        RMS = sqrt( (x1^2 + x2^2 + ... + xN^2) / N )
        MAV = (1/N) * sum( |xi| )
    Returns (t_end, rms, mav).
    """
    t = np.asarray(t)
    v = np.asarray(v)
    t_ends, rms_list, mav_list = [], [], []
    if len(t) == 0:
        return np.array([]), np.array([]), np.array([])
    t_end = window_s
    while t_end <= t[-1] + 1e-9:
        i0 = np.searchsorted(t, t_end - window_s, side="right")   # t >  t_end - window
        i1 = np.searchsorted(t, t_end, side="right")              # t <= t_end
        window = v[i0:i1]
        if len(window) > 0:
            t_ends.append(t_end)
            rms_list.append(np.sqrt(np.mean(window ** 2)))
            mav_list.append(np.mean(np.abs(window)))
        t_end += step_s
    return np.array(t_ends), np.array(rms_list), np.array(mav_list)

def minmax_decimate(t, v, max_points=MAX_DISPLAY_POINTS):
    """Thin out a long signal for plotting while keeping the peaks (min and max per bucket)."""
    n = len(v)
    if n <= max_points:
        return t, v
    buckets = max_points // 2
    edges = np.linspace(0, n, buckets + 1).astype(int)
    out_t, out_v = [], []
    for i in range(buckets):
        seg_v = v[edges[i]:edges[i + 1]]
        seg_t = t[edges[i]:edges[i + 1]]
        if len(seg_v) == 0:
            continue
        for j in sorted((int(np.argmin(seg_v)), int(np.argmax(seg_v)))):
            out_t.append(seg_t[j])
            out_v.append(seg_v[j])
    return np.array(out_t), np.array(out_v)

def sig(a, digits=6):
    """Round numbers to a number of significant digits (keeps saved files small)."""
    return [float(f"{x:.{digits}g}") for x in a]

def run_analysis(arr, o):
    """
    Process the loaded file according to the options dict 'o' and return an analysis dict.
    Raises ValueError with a readable message if something is wrong.
    """
    n, ncols = arr.shape
    col = o["value_col"]
    if not 0 <= col < ncols:
        raise ValueError("The chosen value column does not exist in the file.")
    x = arr[:, col].astype(float)
    notes = []

    # ---- time axis and sampling frequency ----
    if o["has_time"]:
        if col == 0:
            raise ValueError("The value column cannot be the time column.")
        t = (arr[:, 0] - arr[0, 0]) * o["time_scale"]
        if n < 2 or not np.all(np.diff(t) > 0):
            raise ValueError("The time column must be strictly increasing. "
                             "Check the time unit and the file.")
        fs = (n - 1) / t[-1]
    else:
        fs = o["fs"]
        t = np.arange(n) / fs

    if n < 20:
        raise ValueError("Too few samples in the file.")
    duration = float(t[-1])
    if duration < o["window_s"]:
        raise ValueError(f"The recording is {duration:.2f} s long, which is shorter than "
                         f"the RMS/MAV window ({o['window_s']} s).")

    # ---- scaling and cleaning ----
    x = x / o["gain"]
    if o["dc"]:
        x = x - np.mean(x)

    nyq = fs / 2.0
    band, notch = o["band"], o["notch"]
    if band is not None:
        lo, hi = band
        if hi > 0.9 * nyq:
            hi = 0.9 * nyq
            notes.append(f"Band-pass high edge limited to {hi:.0f} Hz (sampling frequency is {fs:.0f} Hz).")
        if lo >= hi:
            raise ValueError(f"Band-pass low edge ({lo} Hz) must be below the high edge "
                             f"({hi:.0f} Hz). Half the sampling frequency is {nyq:.0f} Hz.")
        band = (lo, hi)
    if notch is not None and notch >= 0.9 * nyq:
        notes.append("Mains notch skipped (sampling frequency is too low).")
        notch = None
    y = fft_filter(x, fs, band, notch) if (band or notch) else x

    # ---- RMS and MAV ----
    t_win, rms, mav = sliding_rms_mav(t, y, o["window_s"], o["step_s"])
    if len(t_win) == 0:
        raise ValueError("No RMS/MAV values could be calculated. Check window and step.")

    disp_t, disp_v = minmax_decimate(t, y)

    return {
        "signal_type": o["signal_type"],
        "source": o["source"],
        "unit": o["unit"],
        "fs": float(fs),
        "n_samples": int(n),
        "duration": duration,
        "window_s": o["window_s"],
        "step_s": o["step_s"],
        "overall_rms": float(np.sqrt(np.mean(y ** 2))),
        "overall_mav": float(np.mean(np.abs(y))),
        "max_rms": float(np.max(rms)),
        "notes": notes,
        "fatigue": "",
        "tags": [],
        "comment": "",
        "signal_t": sig(disp_t),
        "signal_v": sig(disp_v),
        "t": sig(t_win),
        "rms": sig(rms),
        "mav": sig(mav),
    }

def parse_stream_line(raw):
    """Parse one line from the ESP32 (bytes).
    Returns ("info", text), ("data", time_us, pin_mV) or None for anything unusable."""
    text = raw.decode("ascii", errors="ignore").strip()
    if not text:
        return None
    if text[0] == "#":
        return ("info", text.lstrip("# ").strip())
    parts = text.split()
    if len(parts) != 2:
        return None
    try:
        us = int(parts[0])
        mv = float(parts[1])
    except ValueError:
        return None
    if us < 0 or not -200.0 <= mv <= 3800.0:        # also rejects 'nan'; a corrupted line
        return None
    return ("data", us, mv)

def esp_pin_to_values(pin_mv, gain, bias_v):
    """Pin voltage (mV) -> millivolts at the electrodes:  (V_pin - bias) / gain."""
    return (np.asarray(pin_mv, dtype=float) / 1000.0 - bias_v) / gain * 1000.0

def regularize(t, v):
    """Resample modest timing jitter; reject substantial gaps instead of hiding them."""
    t, v = np.asarray(t, dtype=float), np.asarray(v, dtype=float)
    if len(t) < 2 or len(t) != len(v) or not np.all(np.isfinite(t)) or not np.all(np.isfinite(v)):
        raise ValueError("Invalid recording arrays.")
    dt = np.diff(t)
    if np.any(dt <= 0):
        raise ValueError("The time stamps must be strictly increasing.")
    step = float(np.median(dt))
    expected = int(round((t[-1] - t[0]) / step)) + 1
    missing = float(np.sum(np.where(dt > 1.8 * step, np.maximum(np.rint(dt / step) - 1, 0), 0)))
    fraction = missing / (len(t) + missing)
    if np.max(dt) > 0.010 or fraction > 0.01 or expected > 10000000:
        raise ValueError("Too many missing/irregular samples (>1%) or gap >10 ms. "
                         "Repeat recording or choose to save the raw data; check connection and sampling.")
    grid = np.linspace(t[0], t[-1], expected)
    return grid, np.interp(grid, t, v), fraction

def esp_recording_notes(pin_mv, entered_bias, auto_bias, missing_fraction):
    """Warnings about a finished recording. Returns (list of texts, measured mean level in volts)."""
    pin_mv = np.asarray(pin_mv, dtype=float)
    mean_v = float(np.mean(pin_mv)) / 1000.0
    notes = []
    off_limits = float(np.mean((pin_mv < ADC_LOW_MV) | (pin_mv > ADC_HIGH_MV)))
    if off_limits > 0.005:
        notes.append(f"{off_limits * 100:.1f} % of the samples are near the ADC limits "
                     f"(below {ADC_LOW_MV / 1000:.2f} V or above {ADC_HIGH_MV / 1000:.2f} V). "
                     "Check your chip ADC range, amplification and bias; this does not prove clipping.")
    if abs(mean_v - entered_bias) > 0.25:
        used = "the measured average" if auto_bias else "your value"
        notes.append(f"The average level on the ESP32 pin was {mean_v:.2f} V but the bias is set to "
                     f"{entered_bias:.2f} V. The analysis used {used}. Check the bias setting and the wiring.")
    if missing_fraction > 0:
        notes.append(f"{missing_fraction * 100:.1f} % of the samples appear missing from timing and were filled in "
                     "by interpolation. Move closer to the ESP32 or use USB.")
    return notes, mean_v

class SocketLines:
    """Reads text lines from a TCP socket (timeouts do not lose data)."""

    def __init__(self, sock):
        self.sock = sock
        self.buf = b""

    def readline(self):
        """One line (bytes), or None if nothing complete arrived within the timeout."""
        while b"\n" not in self.buf:
            try:
                chunk = self.sock.recv(4096)
            except socket.timeout:
                return None
            if not chunk:
                raise ConnectionError("The ESP32 closed the connection.")
            self.buf += chunk
            if len(self.buf) > 65536 and b"\n" not in self.buf:
                self.buf = b""                       # garbage without line breaks
        line, self.buf = self.buf.split(b"\n", 1)
        return line

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass

class StreamRecorder(threading.Thread):
    """Reads the ESP32 in the background and posts messages to a queue for the window:
         ("status", text)  ("info", text)  ("started",)  ("data", time_s, pin_mV)
         ("done",)         ("error", text)"""

    STALL_S = 6.0

    def __init__(self, cfg, out_queue):
        super().__init__(daemon=True)
        self.cfg = cfg
        self.q = out_queue
        self.stop_event = threading.Event()

    def _open(self):
        c = self.cfg
        if c["kind"] == "wifi":
            self.q.put(("status", f"Connecting to {c['host']}:{c['tcp_port']} ..."))
            try:
                sock = socket.create_connection((c["host"], c["tcp_port"]), timeout=6)
            except OSError as e:
                raise ConnectionError(
                    f"Could not connect to {c['host']}:{c['tcp_port']}\n({e})\n\n"
                    "- Is the ESP32 powered on?\n"
                    "- Is this computer connected to the ESP32's Wi-Fi (or to the same network)?\n"
                    "- Are the address and port correct? (The Serial Monitor in the Arduino IDE shows them.)")
            sock.settimeout(0.5)
            return SocketLines(sock)

        raise ConnectionError("Webbversionen använder Wi-Fi (TCP). Välj Wi-Fi som anslutning.")

    def run(self):
        reader = None
        try:
            reader = self._open()
            self.q.put(("started",))
            duration = self.cfg["duration"]
            start_us = last_us = None
            last_data = time.time()
            wall_end = time.time() + duration + 15           # safety net
            while not self.stop_event.is_set() and time.time() < wall_end:
                raw = reader.readline()
                if raw is None:
                    if time.time() - last_data > self.STALL_S:
                        raise ConnectionError(
                            f"No data arrived from the ESP32 for {self.STALL_S:.0f} seconds.\n\n"
                            "- Is the sketch uploaded, with TRANSPORT set to the connection you chose?\n"
                            "- USB: is the baud rate the same as USB_BAUD in the sketch?\n"
                            "- Bluetooth: is the right (outgoing) port selected?")
                    continue
                msg = parse_stream_line(raw)
                if msg is None:
                    continue
                if msg[0] == "info":
                    self.q.put(msg)
                    continue
                _, us, mv = msg
                last_data = time.time()
                if start_us is None:
                    start_us = us
                if last_us is not None and us <= last_us:
                    continue                                 # duplicate or out of order
                last_us = us
                t = (us - start_us) / 1e6
                self.q.put(("data", t, mv))
                if t >= duration:
                    break
            self.q.put(("done",))
        except Exception as e:                               # report every problem to the window
            self.q.put(("error", str(e) if isinstance(e, ConnectionError) else f"{type(e).__name__}: {e}"))
        finally:
            if reader is not None:
                reader.close()
