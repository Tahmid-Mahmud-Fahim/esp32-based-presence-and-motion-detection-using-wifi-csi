from __future__ import annotations

import argparse
import importlib.util
import json
import socket
import sys
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import joblib
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from presence.csi_utils import extract_window_features, load_baseline

PHASE1_LIVE = PROJECT_ROOT / "python" / "07_live_presence.py"
spec = importlib.util.spec_from_file_location("phase1_live", PHASE1_LIVE)
if spec is None or spec.loader is None:
    raise RuntimeError(f"Could not load {PHASE1_LIVE}")
phase1_live = importlib.util.module_from_spec(spec)
spec.loader.exec_module(phase1_live)


class SharedState:
    def __init__(self):
        self.lock = threading.Lock()
        self.data = {
            "system": "IDLE",
            "status": "UNKNOWN",
            "raw_status": "UNKNOWN",
            "probability_person": None,
            "vote_person": 0,
            "vote_total": 0,
            "rx1_packets": 0,
            "rx2_packets": 0,
            "rx1_bad": 0,
            "rx2_bad": 0,
            "countdown_remaining": 0,
            "calibration_remaining": 0.0,
            "calibration_total": 0.0,
            "baseline_drift_rx1": None,
            "baseline_drift_rx2": None,
            "message": "Ready. Press START on the phone.",
            "updated_unix": time.time(),
        }

    def update(self, **kwargs):
        with self.lock:
            self.data.update(kwargs)
            self.data["updated_unix"] = time.time()

    def snapshot(self):
        with self.lock:
            return dict(self.data)


STATE = SharedState()

HTML = r'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Wi-Fi Presence Control</title>
<style>
:root{font-family:system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color-scheme:dark}
*{box-sizing:border-box}
body{margin:0;min-height:100vh;background:#0b1020;color:#eef2ff}
.wrap{width:min(760px,100%);margin:0 auto;padding:18px 14px 36px}
h1{margin:4px 0;font-size:1.55rem}.sub{margin:0 0 18px;color:#aab4d6}
.card{border:1px solid #293351;background:#121a2e;border-radius:20px;padding:18px;margin-bottom:14px}
.stage{text-align:center;color:#b9c4e2;font-weight:700;letter-spacing:.05em;font-size:.92rem}
.main-status{text-align:center;font-size:clamp(2.5rem,15vw,5.4rem);line-height:1.05;font-weight:900;margin:12px 0 8px;word-break:break-word}
.empty{color:#67e8a5}.person{color:#ff8a8a}.unknown{color:#facc15}.idle{color:#b7c0d8}
.prob{text-align:center;color:#cbd5e1;font-size:1rem}
.actions{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:14px}
button{min-height:54px;border:0;border-radius:16px;font-size:1rem;font-weight:800;cursor:pointer;padding:12px 16px}
#startBtn{background:#37c978;color:#07140d}#stopBtn{background:#ef6b6b;color:#210909}
button:disabled{opacity:.42;cursor:not-allowed}
.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}
.metric{border:1px solid #26304a;border-radius:15px;background:#0f1729;padding:13px;min-width:0}
.k{color:#91a0c5;font-size:.8rem}.v{margin-top:5px;font-weight:750;font-size:1.02rem;overflow-wrap:anywhere}
.message{font-weight:650;line-height:1.45;margin-top:6px}
.progress{width:100%;height:12px;border-radius:999px;overflow:hidden;background:#222c45;margin-top:12px}
.bar{height:100%;width:0;background:#facc15;transition:width .2s linear}
.hint{color:#8d9abc;font-size:.82rem;line-height:1.45;margin-top:12px}
@media(max-width:410px){.actions{grid-template-columns:1fr}}
</style>
</head>
<body>
<div class="wrap">
<h1>Wi-Fi Presence Control</h1>
<p class="sub">Phase 1 · phone-controlled EMPTY / PERSON sensing</p>

<div class="card">
<div id="stage" class="stage">IDLE</div>
<div id="mainStatus" class="main-status idle">READY</div>
<div id="prob" class="prob">Press START to begin</div>
<div id="progressWrap" class="progress" style="display:none"><div id="progressBar" class="bar"></div></div>
</div>

<div class="actions">
<button id="startBtn" type="button">START OPERATION</button>
<button id="stopBtn" type="button" disabled>STOP OPERATION</button>
</div>

<div class="card">
<div class="grid">
<div class="metric"><div class="k">Raw window</div><div id="raw" class="v">--</div></div>
<div class="metric"><div class="k">Majority vote</div><div id="vote" class="v">--</div></div>
<div class="metric"><div class="k">RX1 packets</div><div id="rx1" class="v">--</div></div>
<div class="metric"><div class="k">RX2 packets</div><div id="rx2" class="v">--</div></div>
</div>
</div>

<div class="card">
<div class="k">System message</div>
<div id="message" class="message">Ready.</div>
<div id="drift" class="hint"></div>
</div>

<div class="hint">
START opens RX1/RX2, runs the countdown, calibrates the empty area, then starts live detection.
STOP works during countdown, calibration, or live sensing. The laptop server remains on so START can be pressed again.
</div>
</div>

<script>
const q=id=>document.getElementById(id);
const stage=q('stage'), mainStatus=q('mainStatus'), prob=q('prob'), raw=q('raw'), vote=q('vote'),
rx1=q('rx1'),rx2=q('rx2'),message=q('message'),drift=q('drift'),
startBtn=q('startBtn'),stopBtn=q('stopBtn'),progressWrap=q('progressWrap'),progressBar=q('progressBar');
let busy=false;

function setMain(t,c){mainStatus.textContent=t;mainStatus.className='main-status '+c}

async function postAction(path){
 if(busy)return; busy=true;
 try{
  const r=await fetch(path,{method:'POST',cache:'no-store'});
  const d=await r.json();
  if(!r.ok)throw new Error(d.error||d.message||('HTTP '+r.status));
 }catch(e){alert(e.message)}
 finally{busy=false}
}

startBtn.addEventListener('click',()=>{
 const ok=confirm('The sensing area must be EMPTY during calibration.\\n\\nAfter you press OK, the countdown starts. Leave the area before it reaches zero.');
 if(ok)postAction('/api/start');
});
stopBtn.addEventListener('click',()=>postAction('/api/stop'));

async function refresh(){
 try{
  const r=await fetch('/api/status',{cache:'no-store'});
  if(!r.ok)throw new Error('HTTP '+r.status);
  const d=await r.json(), sys=d.system||'UNKNOWN';
  stage.textContent=sys; message.textContent=d.message||'';
  raw.textContent=d.raw_status||'--';
  vote.textContent=`${d.vote_person??0}/${d.vote_total??0}`;
  rx1.textContent=d.rx1_packets??'--'; rx2.textContent=d.rx2_packets??'--';
  const active=!['IDLE','ERROR'].includes(sys);
  startBtn.disabled=active; stopBtn.disabled=!active;
  progressWrap.style.display='none';

  if(sys==='IDLE'){setMain('READY','idle');prob.textContent='Press START to begin'}
  else if(sys==='CONNECTING'){setMain('CONNECTING','unknown');prob.textContent='Opening RX1 / RX2'}
  else if(sys==='COUNTDOWN'){setMain(String(Math.max(0,Number(d.countdown_remaining||0))),'unknown');prob.textContent='Leave the sensing area now'}
  else if(sys==='CALIBRATING'){
    const left=Math.max(0,Number(d.calibration_remaining||0)), total=Math.max(.001,Number(d.calibration_total||1));
    setMain(left.toFixed(1)+'s','unknown');prob.textContent='Keep sensing area EMPTY';
    progressWrap.style.display='block';progressBar.style.width=`${Math.max(0,Math.min(100,100*(total-left)/total))}%`;
  }
  else if(sys==='RUNNING'){
    const s=d.status||'UNKNOWN';setMain(s,s==='PERSON'?'person':s==='EMPTY'?'empty':'unknown');
    prob.textContent=(d.probability_person==null)?'PERSON probability: --':`PERSON probability: ${(100*d.probability_person).toFixed(1)}%`;
  }
  else if(sys==='STOPPING'){setMain('STOPPING','unknown');prob.textContent='Closing RX streams'}
  else if(sys==='ERROR'){setMain('ERROR','person');prob.textContent='Check system message';startBtn.disabled=false;stopBtn.disabled=true}
  else setMain(sys,'unknown');

  if(d.baseline_drift_rx1!=null){
    drift.textContent=`Calibration drift vs training baseline: RX1 ${Number(d.baseline_drift_rx1).toFixed(4)}, RX2 ${Number(d.baseline_drift_rx2).toFixed(4)}`;
  }else drift.textContent='';
 }catch(e){
  stage.textContent='DISCONNECTED';setMain('OFFLINE','person');prob.textContent='Cannot reach laptop server';
  startBtn.disabled=true;stopBtn.disabled=true;
 }
}
refresh();setInterval(refresh,250);
</script>
</body>
</html>'''


class Controller:
    def __init__(self, args, bundle):
        self.args = args
        self.bundle = bundle
        self.lock = threading.Lock()
        self.worker = None
        self.stop_event = None

    def is_active(self):
        with self.lock:
            return self.worker is not None and self.worker.is_alive()

    def start(self):
        with self.lock:
            if self.worker is not None and self.worker.is_alive():
                return False, "Operation is already active."
            self.stop_event = threading.Event()
            self.worker = threading.Thread(target=self._run, args=(self.stop_event,), daemon=True)
            self.worker.start()
            return True, "Operation started."

    def stop(self):
        with self.lock:
            if self.worker is None or not self.worker.is_alive():
                STATE.update(system="IDLE", message="Already stopped. Press START to begin.")
                return False, "Operation is not active."
            STATE.update(system="STOPPING", message="Stop requested from phone...")
            self.stop_event.set()
            return True, "Stop requested."

    def _wait(self, seconds, stop_event, tick=None):
        end = time.perf_counter() + seconds
        while True:
            if stop_event.is_set():
                return False
            left = end - time.perf_counter()
            if left <= 0:
                return True
            if tick:
                tick(left)
            time.sleep(min(0.1, left))

    def _run(self, stop_event):
        r1 = r2 = None
        args = self.args
        try:
            STATE.update(system="CONNECTING", status="UNKNOWN", raw_status="UNKNOWN",
                         probability_person=None, vote_person=0, vote_total=0,
                         rx1_packets=0, rx2_packets=0, countdown_remaining=args.countdown,
                         calibration_remaining=0.0, calibration_total=args.calibration,
                         baseline_drift_rx1=None, baseline_drift_rx2=None,
                         message="Opening RX1 and RX2...")

            t0 = time.perf_counter()
            r1 = phase1_live.ReceiverStream("RX1", args.rx1, args.baud, t0)
            r2 = phase1_live.ReceiverStream("RX2", args.rx2, args.baud, t0)
            r1.start(); r2.start()

            STATE.update(system="COUNTDOWN", message="Leave the sensing area before calibration starts.")
            for n in range(args.countdown, 0, -1):
                STATE.update(countdown_remaining=n, rx1_packets=r1.valid_packets, rx2_packets=r2.valid_packets,
                             message=f"Leave the sensing area. Calibration starts in {n}s.")
                if not self._wait(1.0, stop_event):
                    return

            r1.clear(); r2.clear()

            STATE.update(system="CALIBRATING", countdown_remaining=0,
                         calibration_remaining=args.calibration, calibration_total=args.calibration,
                         message="Keep the sensing area EMPTY.")
            cal_start = time.perf_counter()

            def tick(_):
                left = max(0.0, args.calibration - (time.perf_counter() - cal_start))
                STATE.update(calibration_remaining=left, rx1_packets=r1.valid_packets, rx2_packets=r2.valid_packets,
                             message=f"EMPTY calibration: {left:.1f}s remaining.")

            if not self._wait(args.calibration, stop_event, tick):
                return

            if not r1.running:
                raise RuntimeError(f"RX1 stopped: {r1.last_error}")
            if not r2.running:
                raise RuntimeError(f"RX2 stopped: {r2.last_error}")

            current_baseline = phase1_live.build_current_empty_baseline(
                r1, r2, fs=args.fs, min_overlap_s=max(5.0, args.calibration - 2.0)
            )

            drift1 = drift2 = None
            if args.training_baseline:
                old = load_baseline(args.training_baseline)
                drift1 = phase1_live.rmse(current_baseline["rx1"], old["rx1"])
                drift2 = phase1_live.rmse(current_baseline["rx2"], old["rx2"])

            r1.clear(); r2.clear()

            model = self.bundle["model"]
            feature_names = list(self.bundle["feature_names"])
            threshold = float(self.bundle.get("decision_threshold", 0.5))
            recent = deque(maxlen=max(1, args.vote))
            next_infer = time.perf_counter() + args.window + 0.25
            last_used = -1.0

            STATE.update(system="RUNNING", calibration_remaining=0.0,
                         baseline_drift_rx1=drift1, baseline_drift_rx2=drift2,
                         message="Calibration complete. Live detection active.")

            while not stop_event.is_set():
                if not r1.running:
                    raise RuntimeError(f"RX1 stopped: {r1.last_error}")
                if not r2.running:
                    raise RuntimeError(f"RX2 stopped: {r2.last_error}")

                now = time.perf_counter()
                if now < next_infer:
                    time.sleep(min(0.05, next_infer - now))
                    continue
                next_infer += args.step

                prepared, reason = phase1_live.prepare_live_window(
                    r1, r2, fs=args.fs, window_s=args.window,
                    now_rel=time.perf_counter() - t0, stale_s=args.stale
                )
                if prepared is None:
                    STATE.update(system="RUNNING", message=f"Waiting for valid CSI: {reason}",
                                 rx1_packets=r1.valid_packets, rx2_packets=r2.valid_packets)
                    continue

                W1, W2, common_end = prepared
                if common_end <= last_used + 1e-6:
                    continue
                last_used = common_end

                feat = extract_window_features(W1, W2, current_baseline)
                X = pd.DataFrame([feat], columns=feature_names)
                p = float(model.predict_proba(X)[0, 1])

                raw_person = p >= threshold
                recent.append(1 if raw_person else 0)
                pv = int(sum(recent))
                stable_person = pv > (len(recent) - pv)

                raw_label = "PERSON" if raw_person else "EMPTY"
                stable_label = "PERSON" if stable_person else "EMPTY"

                STATE.update(system="RUNNING", status=stable_label, raw_status=raw_label,
                             probability_person=p, vote_person=pv, vote_total=len(recent),
                             rx1_packets=r1.valid_packets, rx2_packets=r2.valid_packets,
                             rx1_bad=r1.parse_bad, rx2_bad=r2.parse_bad,
                             message="Live detection active.")

                print(f"prob={p:6.3f} raw={raw_label:6s} vote={pv}/{len(recent)} => {stable_label:6s} "
                      f"| RX1={r1.valid_packets:5d} RX2={r2.valid_packets:5d}")

        except Exception as exc:
            if not stop_event.is_set():
                STATE.update(system="ERROR", status="UNKNOWN", raw_status="UNKNOWN",
                             probability_person=None, message=f"{type(exc).__name__}: {exc}")
        finally:
            if r1 is not None: r1.stop()
            if r2 is not None: r2.stop()
            if stop_event.is_set():
                STATE.update(system="IDLE", status="UNKNOWN", raw_status="UNKNOWN",
                             probability_person=None, vote_person=0, vote_total=0,
                             countdown_remaining=0, calibration_remaining=0.0,
                             message="Stopped from phone. Press START to run again.")


CONTROLLER = None


class Handler(BaseHTTPRequestHandler):
    def send_body(self, code, ctype, body):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, code, obj):
        self.send_body(code, "application/json; charset=utf-8", json.dumps(obj).encode())

    def do_GET(self):
        p = urlparse(self.path).path
        if p == "/":
            self.send_body(200, "text/html; charset=utf-8", HTML.encode())
        elif p == "/api/status":
            self.send_json(200, STATE.snapshot())
        else:
            self.send_body(404, "text/plain", b"Not found")

    def do_POST(self):
        global CONTROLLER
        p = urlparse(self.path).path
        if p == "/api/start":
            ok, msg = CONTROLLER.start()
            self.send_json(200 if ok else 409, {"ok": ok, "message": msg})
        elif p == "/api/stop":
            ok, msg = CONTROLLER.stop()
            self.send_json(200, {"ok": ok, "message": msg})
        else:
            self.send_json(404, {"ok": False, "error": "Not found"})

    def log_message(self, fmt, *args):
        return


def best_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return socket.gethostbyname(socket.gethostname())


def main():
    global CONTROLLER
    ap = argparse.ArgumentParser()
    ap.add_argument("--rx1", default="COM6")
    ap.add_argument("--rx2", default="COM8")
    ap.add_argument("--baud", type=int, default=921600)
    ap.add_argument("--model", required=True)
    ap.add_argument("--training-baseline", default=None)
    ap.add_argument("--countdown", type=int, default=5)
    ap.add_argument("--calibration", type=float, default=12.0)
    ap.add_argument("--fs", type=float, default=25.0)
    ap.add_argument("--window", type=float, default=2.0)
    ap.add_argument("--step", type=float, default=0.5)
    ap.add_argument("--vote", type=int, default=5)
    ap.add_argument("--stale", type=float, default=1.0)
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8080)
    args = ap.parse_args()

    bundle = joblib.load(args.model)
    CONTROLLER = Controller(args, bundle)
    ip = best_local_ip()
    server = ThreadingHTTPServer((args.host, args.port), Handler)

    print("="*78)
    print("PHASE-6 PHONE CONTROL SERVER")
    print("="*78)
    print(f"RX1 / RX2   : {args.rx1} / {args.rx2}")
    print(f"Model       : {bundle.get('model_name','unknown')}")
    print(f"Countdown   : {args.countdown}s")
    print(f"Calibration : {args.calibration:.1f}s")
    print(f"Laptop URL  : http://127.0.0.1:{args.port}")
    print(f"Phone URL   : http://{ip}:{args.port}")
    print()
    print("Detector is IDLE until START is pressed on the phone.")
    print("STOP on the phone stops sensing but leaves this server alive.")
    print("Ctrl+C here shuts down the server itself.")
    print("="*78)

    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        print("\nShutting down server...")
        if CONTROLLER and CONTROLLER.is_active():
            CONTROLLER.stop()
            time.sleep(0.5)
    finally:
        server.server_close()
        print("Server stopped.")


if __name__ == "__main__":
    main()
