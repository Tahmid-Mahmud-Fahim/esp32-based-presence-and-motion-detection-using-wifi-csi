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

PHASE2_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = PHASE2_ROOT.parent
PHASE1_ROOT = PROJECT_ROOT / "phase1"

sys.path.insert(0, str(PHASE1_ROOT))
sys.path.insert(0, str(PHASE2_ROOT / "python"))

from presence.csi_utils import extract_window_features, load_baseline
from phase2_utils import extract_motion_features

# Re-use the final Phase-1 live receiver/calibration/alignment code.
PHASE1_LIVE = PHASE1_ROOT / "python" / "07_live_presence.py"

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

            # PHASE 1
            "phase1_status": "UNKNOWN",
            "phase1_raw": "UNKNOWN",
            "probability_person": None,
            "phase1_vote_person": 0,
            "phase1_vote_total": 0,

            # PHASE 2
            "phase2_status": "--",
            "phase2_raw": "--",
            "probability_moving": None,
            "phase2_vote_moving": 0,
            "phase2_vote_total": 0,

            # SYSTEM
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
<title>Wi-Fi Human Sensing</title>
<style>
:root{font-family:system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color-scheme:dark}
*{box-sizing:border-box}
body{margin:0;min-height:100vh;background:#0b1020;color:#eef2ff}
.wrap{width:min(760px,100%);margin:0 auto;padding:18px 14px 36px}
h1{margin:4px 0;font-size:1.55rem}.sub{margin:0 0 18px;color:#aab4d6}
.card{border:1px solid #293351;background:#121a2e;border-radius:20px;padding:18px;margin-bottom:14px}
.section-title{text-align:center;color:#b9c4e2;font-weight:800;letter-spacing:.06em;font-size:.82rem}
.main-status{text-align:center;font-size:clamp(2.4rem,14vw,5rem);line-height:1.05;font-weight:900;margin:12px 0 8px;word-break:break-word}
.empty{color:#67e8a5}.person{color:#ff8a8a}.static{color:#73b7ff}.moving{color:#ffbe69}.unknown{color:#facc15}.idle{color:#b7c0d8}
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
.divider{height:1px;background:#293351;margin:18px 0}
@media(max-width:410px){.actions{grid-template-columns:1fr}}
</style>
</head>
<body>
<div class="wrap">

<h1>Wi-Fi Human Sensing</h1>
<p class="sub">Phase 1 + Phase 2 · phone-controlled sensing</p>

<div class="card">
  <div class="section-title">PHASE 1 · PRESENCE</div>
  <div id="phase1Status" class="main-status idle">READY</div>
  <div id="phase1Prob" class="prob">EMPTY / PERSON</div>

  <div class="grid" style="margin-top:16px">
    <div class="metric">
      <div class="k">Raw Phase 1</div>
      <div id="phase1Raw" class="v">--</div>
    </div>
    <div class="metric">
      <div class="k">PERSON vote</div>
      <div id="phase1Vote" class="v">--</div>
    </div>
  </div>
</div>

<div class="card">
  <div class="section-title">PHASE 2 · ACTIVITY</div>
  <div id="phase2Status" class="main-status idle">--</div>
  <div id="phase2Prob" class="prob">Runs only when Phase 1 = PERSON</div>

  <div class="grid" style="margin-top:16px">
    <div class="metric">
      <div class="k">Raw Phase 2</div>
      <div id="phase2Raw" class="v">--</div>
    </div>
    <div class="metric">
      <div class="k">MOVING vote</div>
      <div id="phase2Vote" class="v">--</div>
    </div>
  </div>
</div>

<div class="actions">
  <button id="startBtn" type="button">START OPERATION</button>
  <button id="stopBtn" type="button" disabled>STOP OPERATION</button>
</div>

<div class="card">
  <div id="stage" class="section-title">IDLE</div>
  <div id="progressWrap" class="progress" style="display:none">
    <div id="progressBar" class="bar"></div>
  </div>

  <div class="grid" style="margin-top:16px">
    <div class="metric">
      <div class="k">RX1 packets</div>
      <div id="rx1" class="v">--</div>
    </div>
    <div class="metric">
      <div class="k">RX2 packets</div>
      <div id="rx2" class="v">--</div>
    </div>
  </div>

  <div class="divider"></div>

  <div class="k">System message</div>
  <div id="message" class="message">Ready.</div>
  <div id="drift" class="hint"></div>
</div>

<div class="hint">
Phase 1 independently decides EMPTY / PERSON.
If Phase 1 says PERSON, Phase 2 decides STATIC / MOVING.
START opens RX1/RX2, performs the same empty-room calibration as Phase 1,
then starts both sections.
</div>

</div>

<script>
const q=id=>document.getElementById(id);

const stage=q('stage');
const phase1Status=q('phase1Status');
const phase1Prob=q('phase1Prob');
const phase1Raw=q('phase1Raw');
const phase1Vote=q('phase1Vote');

const phase2Status=q('phase2Status');
const phase2Prob=q('phase2Prob');
const phase2Raw=q('phase2Raw');
const phase2Vote=q('phase2Vote');

const rx1=q('rx1'), rx2=q('rx2');
const message=q('message'), drift=q('drift');
const startBtn=q('startBtn'), stopBtn=q('stopBtn');
const progressWrap=q('progressWrap'), progressBar=q('progressBar');

let busy=false;

function setStatus(el,text,cls){
  el.textContent=text;
  el.className='main-status '+cls;
}

async function postAction(path){
  if(busy)return;
  busy=true;
  try{
    const r=await fetch(path,{method:'POST',cache:'no-store'});
    const d=await r.json();
    if(!r.ok)throw new Error(d.error||d.message||('HTTP '+r.status));
  }catch(e){
    alert(e.message);
  }finally{
    busy=false;
  }
}

startBtn.addEventListener('click',()=>{
  const ok=confirm(
    'The sensing area must be EMPTY during calibration.\n\n'+
    'After you press OK, the countdown starts. Leave the area before it reaches zero.'
  );
  if(ok)postAction('/api/start');
});

stopBtn.addEventListener('click',()=>postAction('/api/stop'));

async function refresh(){
  try{
    const r=await fetch('/api/status',{cache:'no-store'});
    if(!r.ok)throw new Error('HTTP '+r.status);

    const d=await r.json();
    const sys=d.system||'UNKNOWN';

    stage.textContent=sys;
    message.textContent=d.message||'';

    rx1.textContent=d.rx1_packets??'--';
    rx2.textContent=d.rx2_packets??'--';

    phase1Raw.textContent=d.phase1_raw||'--';
    phase1Vote.textContent=`${d.phase1_vote_person??0}/${d.phase1_vote_total??0}`;

    phase2Raw.textContent=d.phase2_raw||'--';
    phase2Vote.textContent=`${d.phase2_vote_moving??0}/${d.phase2_vote_total??0}`;

    const active=!['IDLE','ERROR'].includes(sys);
    startBtn.disabled=active;
    stopBtn.disabled=!active;
    progressWrap.style.display='none';

    if(sys==='IDLE'){
      setStatus(phase1Status,'READY','idle');
      phase1Prob.textContent='EMPTY / PERSON';
      setStatus(phase2Status,'--','idle');
      phase2Prob.textContent='Runs only when Phase 1 = PERSON';
    }

    else if(sys==='CONNECTING'){
      setStatus(phase1Status,'CONNECTING','unknown');
      phase1Prob.textContent='Opening RX1 / RX2';
      setStatus(phase2Status,'--','idle');
      phase2Prob.textContent='Waiting for Phase 1';
    }

    else if(sys==='COUNTDOWN'){
      const n=Math.max(0,Number(d.countdown_remaining||0));
      setStatus(phase1Status,String(n),'unknown');
      phase1Prob.textContent='Leave the sensing area now';
      setStatus(phase2Status,'--','idle');
      phase2Prob.textContent='Waiting for calibration';
    }

    else if(sys==='CALIBRATING'){
      const left=Math.max(0,Number(d.calibration_remaining||0));
      const total=Math.max(.001,Number(d.calibration_total||1));

      setStatus(phase1Status,left.toFixed(1)+'s','unknown');
      phase1Prob.textContent='Keep sensing area EMPTY';

      setStatus(phase2Status,'--','idle');
      phase2Prob.textContent='Waiting for Phase 1';

      progressWrap.style.display='block';
      progressBar.style.width=
        `${Math.max(0,Math.min(100,100*(total-left)/total))}%`;
    }

    else if(sys==='RUNNING'){
      const p1=d.phase1_status||'UNKNOWN';

      setStatus(
        phase1Status,
        p1,
        p1==='PERSON'?'person':
        p1==='EMPTY'?'empty':'unknown'
      );

      phase1Prob.textContent=
        (d.probability_person==null)
        ?'PERSON probability: --'
        :`PERSON probability: ${(100*Number(d.probability_person)).toFixed(1)}%`;

      if(p1==='PERSON'){
        const p2=d.phase2_status||'--';

        setStatus(
          phase2Status,
          p2,
          p2==='MOVING'?'moving':
          p2==='STATIC'?'static':'unknown'
        );

        phase2Prob.textContent=
          (d.probability_moving==null)
          ?'MOVING probability: --'
          :`MOVING probability: ${(100*Number(d.probability_moving)).toFixed(1)}%`;
      }else{
        setStatus(phase2Status,'--','idle');
        phase2Prob.textContent='Phase 1 says EMPTY';
      }
    }

    else if(sys==='STOPPING'){
      setStatus(phase1Status,'STOPPING','unknown');
      phase1Prob.textContent='Closing RX streams';

      setStatus(phase2Status,'--','idle');
      phase2Prob.textContent='Stopping';
    }

    else if(sys==='ERROR'){
      setStatus(phase1Status,'ERROR','person');
      phase1Prob.textContent='Check system message';

      setStatus(phase2Status,'--','idle');
      phase2Prob.textContent='Unavailable';

      startBtn.disabled=false;
      stopBtn.disabled=true;
    }

    else{
      setStatus(phase1Status,sys,'unknown');
      setStatus(phase2Status,'--','idle');
    }

    if(d.baseline_drift_rx1!=null){
      drift.textContent=
        `Calibration drift vs training baseline: `+
        `RX1 ${Number(d.baseline_drift_rx1).toFixed(4)}, `+
        `RX2 ${Number(d.baseline_drift_rx2).toFixed(4)}`;
    }else{
      drift.textContent='';
    }

  }catch(e){
    stage.textContent='DISCONNECTED';

    setStatus(phase1Status,'OFFLINE','person');
    phase1Prob.textContent='Cannot reach laptop server';

    setStatus(phase2Status,'--','idle');
    phase2Prob.textContent='Unavailable';

    startBtn.disabled=true;
    stopBtn.disabled=true;
  }
}

refresh();
setInterval(refresh,250);
</script>
</body>
</html>'''


class Controller:
    def __init__(self, args, presence_bundle, motion_bundle):
        self.args = args
        self.presence_bundle = presence_bundle
        self.motion_bundle = motion_bundle
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
            self.worker = threading.Thread(
                target=self._run,
                args=(self.stop_event,),
                daemon=True,
            )
            self.worker.start()

            return True, "Operation started."

    def stop(self):
        with self.lock:
            if self.worker is None or not self.worker.is_alive():
                STATE.update(
                    system="IDLE",
                    message="Already stopped. Press START to begin.",
                )
                return False, "Operation is not active."

            STATE.update(
                system="STOPPING",
                message="Stop requested from phone...",
            )
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
        r1 = None
        r2 = None
        args = self.args

        try:
            STATE.update(
                system="CONNECTING",

                phase1_status="UNKNOWN",
                phase1_raw="UNKNOWN",
                probability_person=None,
                phase1_vote_person=0,
                phase1_vote_total=0,

                phase2_status="--",
                phase2_raw="--",
                probability_moving=None,
                phase2_vote_moving=0,
                phase2_vote_total=0,

                rx1_packets=0,
                rx2_packets=0,

                countdown_remaining=args.countdown,
                calibration_remaining=0.0,
                calibration_total=args.calibration,

                baseline_drift_rx1=None,
                baseline_drift_rx2=None,

                message="Opening RX1 and RX2...",
            )

            # -------------------------------------------------------------
            # Open the same receiver streams used by final Phase 1.
            # -------------------------------------------------------------
            t0 = time.perf_counter()

            r1 = phase1_live.ReceiverStream(
                "RX1",
                args.rx1,
                args.baud,
                t0,
            )

            r2 = phase1_live.ReceiverStream(
                "RX2",
                args.rx2,
                args.baud,
                t0,
            )

            r1.start()
            r2.start()

            # -------------------------------------------------------------
            # Countdown.
            # -------------------------------------------------------------
            STATE.update(
                system="COUNTDOWN",
                message="Leave the sensing area before calibration starts.",
            )

            for n in range(args.countdown, 0, -1):
                STATE.update(
                    countdown_remaining=n,
                    rx1_packets=r1.valid_packets,
                    rx2_packets=r2.valid_packets,
                    message=f"Leave the sensing area. Calibration starts in {n}s.",
                )

                if not self._wait(1.0, stop_event):
                    return

            # -------------------------------------------------------------
            # Empty-room calibration.
            # -------------------------------------------------------------
            r1.clear()
            r2.clear()

            STATE.update(
                system="CALIBRATING",
                countdown_remaining=0,
                calibration_remaining=args.calibration,
                calibration_total=args.calibration,
                message="Keep the sensing area EMPTY.",
            )

            cal_start = time.perf_counter()

            def tick(_):
                left = max(
                    0.0,
                    args.calibration - (time.perf_counter() - cal_start),
                )

                STATE.update(
                    calibration_remaining=left,
                    rx1_packets=r1.valid_packets,
                    rx2_packets=r2.valid_packets,
                    message=f"EMPTY calibration: {left:.1f}s remaining.",
                )

            if not self._wait(args.calibration, stop_event, tick):
                return

            if not r1.running:
                raise RuntimeError(f"RX1 stopped: {r1.last_error}")

            if not r2.running:
                raise RuntimeError(f"RX2 stopped: {r2.last_error}")

            current_baseline = phase1_live.build_current_empty_baseline(
                r1,
                r2,
                fs=args.fs,
                min_overlap_s=max(5.0, args.calibration - 2.0),
            )

            drift1 = None
            drift2 = None

            if args.training_baseline:
                old = load_baseline(args.training_baseline)

                drift1 = phase1_live.rmse(
                    current_baseline["rx1"],
                    old["rx1"],
                )

                drift2 = phase1_live.rmse(
                    current_baseline["rx2"],
                    old["rx2"],
                )

            r1.clear()
            r2.clear()

            # -------------------------------------------------------------
            # Load model information.
            # -------------------------------------------------------------
            presence_model = self.presence_bundle["model"]
            presence_features = list(self.presence_bundle["feature_names"])
            presence_threshold = float(
                self.presence_bundle.get("decision_threshold", 0.5)
            )

            motion_model = self.motion_bundle["model"]
            motion_features = list(self.motion_bundle["feature_names"])
            motion_threshold = float(
                self.motion_bundle.get("decision_threshold", 0.5)
            )

            # Independent voting:
            # Phase 1 votes EMPTY/PERSON.
            # Phase 2 votes STATIC/MOVING only while Phase 1 says PERSON.
            phase1_recent = deque(maxlen=max(1, args.vote))
            phase2_recent = deque(maxlen=max(1, args.vote))

            # Phase 2 is deliberately PRE-COMPUTED from the raw Phase-1
            # PERSON decision.  We do NOT wait for the smoothed/stable
            # Phase-1 vote before starting the motion classifier.
            #
            # This removes the accidental sequential delay:
            #   wait for Phase-1 vote -> then start Phase-2 vote
            #
            # The phone still SHOWS Phase 2 only when stable Phase 1 = PERSON.
            last_p_moving = None
            last_phase2_raw = "--"
            last_phase2_stable = "--"
            last_phase2_moving_votes = 0
            last_phase2_total_votes = 0

            next_infer = time.perf_counter() + args.window + 0.25
            last_used = -1.0

            STATE.update(
                system="RUNNING",
                calibration_remaining=0.0,
                baseline_drift_rx1=drift1,
                baseline_drift_rx2=drift2,
                message="Calibration complete. Phase 1 + Phase 2 active.",
            )

            # =============================================================
            # LIVE LOOP
            # =============================================================
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
                    r1,
                    r2,
                    fs=args.fs,
                    window_s=args.window,
                    now_rel=time.perf_counter() - t0,
                    stale_s=args.stale,
                )

                if prepared is None:
                    STATE.update(
                        system="RUNNING",
                        message=f"Waiting for valid CSI: {reason}",
                        rx1_packets=r1.valid_packets,
                        rx2_packets=r2.valid_packets,
                    )
                    continue

                W1, W2, common_end = prepared

                if common_end <= last_used + 1e-6:
                    continue

                last_used = common_end

                # =========================================================
                # PHASE 1: EMPTY / PERSON
                # =========================================================
                base_feat = extract_window_features(
                    W1,
                    W2,
                    current_baseline,
                )

                X_presence = pd.DataFrame(
                    [base_feat],
                    columns=presence_features,
                )

                p_person = float(
                    presence_model.predict_proba(X_presence)[0, 1]
                )

                raw_person = p_person >= presence_threshold

                phase1_recent.append(
                    1 if raw_person else 0
                )

                phase1_person_votes = int(sum(phase1_recent))
                phase1_total_votes = len(phase1_recent)

                stable_person = (
                    phase1_person_votes
                    >
                    (phase1_total_votes - phase1_person_votes)
                )

                phase1_raw_label = (
                    "PERSON" if raw_person else "EMPTY"
                )

                phase1_stable_label = (
                    "PERSON" if stable_person else "EMPTY"
                )

                # =========================================================
                # PHASE 2: STATIC / MOVING
                # =========================================================
                # IMPORTANT LATENCY CORRECTION:
                #
                # Run the motion model as soon as the CURRENT RAW Phase-1
                # window says PERSON.  Do not wait for the 5-window stable
                # Phase-1 majority vote first.
                #
                # Therefore Phase-1 voting and Phase-2 voting happen in
                # PARALLEL over the same incoming windows rather than one
                # after another.
                if raw_person:
                    motion_feat = extract_motion_features(
                        W1,
                        W2,
                        fs=args.fs,
                    )

                    X_motion = pd.DataFrame(
                        [motion_feat],
                        columns=motion_features,
                    )

                    last_p_moving = float(
                        motion_model.predict_proba(X_motion)[0, 1]
                    )

                    raw_moving = (
                        last_p_moving >= motion_threshold
                    )

                    phase2_recent.append(
                        1 if raw_moving else 0
                    )

                    last_phase2_moving_votes = int(
                        sum(phase2_recent)
                    )
                    last_phase2_total_votes = len(
                        phase2_recent
                    )

                    stable_moving = (
                        last_phase2_moving_votes
                        >
                        (
                            last_phase2_total_votes
                            -
                            last_phase2_moving_votes
                        )
                    )

                    last_phase2_raw = (
                        "MOVING" if raw_moving else "STATIC"
                    )

                    last_phase2_stable = (
                        "MOVING" if stable_moving else "STATIC"
                    )

                # If Phase 1 has now become stably EMPTY, reset Phase 2.
                # A single transient raw EMPTY while stable Phase 1 is still
                # PERSON does NOT destroy the accumulated motion vote.
                if not stable_person:
                    if not raw_person:
                        phase2_recent.clear()
                        last_p_moving = None
                        last_phase2_raw = "--"
                        last_phase2_stable = "--"
                        last_phase2_moving_votes = 0
                        last_phase2_total_votes = 0

                    p_moving = None
                    phase2_moving_votes = 0
                    phase2_total_votes = 0
                    phase2_raw_label = "--"
                    phase2_stable_label = "--"

                else:
                    # Stable Phase 1 = PERSON:
                    # expose the motion result that has already been building.
                    p_moving = last_p_moving
                    phase2_moving_votes = last_phase2_moving_votes
                    phase2_total_votes = last_phase2_total_votes
                    phase2_raw_label = last_phase2_raw
                    phase2_stable_label = last_phase2_stable

                # ---------------------------------------------------------
                # Update phone UI.
                # ---------------------------------------------------------
                STATE.update(
                    system="RUNNING",

                    phase1_status=phase1_stable_label,
                    phase1_raw=phase1_raw_label,
                    probability_person=p_person,
                    phase1_vote_person=phase1_person_votes,
                    phase1_vote_total=phase1_total_votes,

                    phase2_status=phase2_stable_label,
                    phase2_raw=phase2_raw_label,
                    probability_moving=p_moving,
                    phase2_vote_moving=phase2_moving_votes,
                    phase2_vote_total=phase2_total_votes,

                    rx1_packets=r1.valid_packets,
                    rx2_packets=r2.valid_packets,
                    rx1_bad=r1.parse_bad,
                    rx2_bad=r2.parse_bad,

                    message="Live detection active.",
                )

                # ---------------------------------------------------------
                # Terminal output.
                # ---------------------------------------------------------
                if stable_person:
                    print(
                        f"P1 p_person={p_person:6.3f} "
                        f"raw={phase1_raw_label:6s} "
                        f"vote={phase1_person_votes}/{phase1_total_votes} "
                        f"=> {phase1_stable_label:6s} | "
                        f"P2 p_move={p_moving:6.3f} "
                        f"raw={phase2_raw_label:6s} "
                        f"vote={phase2_moving_votes}/{phase2_total_votes} "
                        f"=> {phase2_stable_label:6s} | "
                        f"RX1={r1.valid_packets:5d} "
                        f"RX2={r2.valid_packets:5d}"
                    )
                else:
                    print(
                        f"P1 p_person={p_person:6.3f} "
                        f"raw={phase1_raw_label:6s} "
                        f"vote={phase1_person_votes}/{phase1_total_votes} "
                        f"=> {phase1_stable_label:6s} | "
                        f"P2 -- | "
                        f"RX1={r1.valid_packets:5d} "
                        f"RX2={r2.valid_packets:5d}"
                    )

        except Exception as exc:
            if not stop_event.is_set():
                STATE.update(
                    system="ERROR",

                    phase1_status="UNKNOWN",
                    phase1_raw="UNKNOWN",
                    probability_person=None,

                    phase2_status="--",
                    phase2_raw="--",
                    probability_moving=None,

                    message=f"{type(exc).__name__}: {exc}",
                )

        finally:
            if r1 is not None:
                r1.stop()

            if r2 is not None:
                r2.stop()

            if stop_event.is_set():
                STATE.update(
                    system="IDLE",

                    phase1_status="UNKNOWN",
                    phase1_raw="UNKNOWN",
                    probability_person=None,
                    phase1_vote_person=0,
                    phase1_vote_total=0,

                    phase2_status="--",
                    phase2_raw="--",
                    probability_moving=None,
                    phase2_vote_moving=0,
                    phase2_vote_total=0,

                    countdown_remaining=0,
                    calibration_remaining=0.0,

                    message="Stopped from phone. Press START to run again.",
                )


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
        self.send_body(
            code,
            "application/json; charset=utf-8",
            json.dumps(obj).encode(),
        )

    def do_GET(self):
        p = urlparse(self.path).path

        if p == "/":
            self.send_body(
                200,
                "text/html; charset=utf-8",
                HTML.encode(),
            )

        elif p == "/api/status":
            self.send_json(
                200,
                STATE.snapshot(),
            )

        else:
            self.send_body(
                404,
                "text/plain",
                b"Not found",
            )

    def do_POST(self):
        global CONTROLLER

        p = urlparse(self.path).path

        if p == "/api/start":
            ok, msg = CONTROLLER.start()

            self.send_json(
                200 if ok else 409,
                {
                    "ok": ok,
                    "message": msg,
                },
            )

        elif p == "/api/stop":
            ok, msg = CONTROLLER.stop()

            self.send_json(
                200,
                {
                    "ok": ok,
                    "message": msg,
                },
            )

        else:
            self.send_json(
                404,
                {
                    "ok": False,
                    "error": "Not found",
                },
            )

    def log_message(self, fmt, *args):
        return


def best_local_ip():
    try:
        s = socket.socket(
            socket.AF_INET,
            socket.SOCK_DGRAM,
        )

        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()

        return ip

    except Exception:
        return socket.gethostbyname(
            socket.gethostname()
        )


def main():
    global CONTROLLER

    ap = argparse.ArgumentParser()

    ap.add_argument("--rx1", default="COM6")
    ap.add_argument("--rx2", default="COM8")
    ap.add_argument("--baud", type=int, default=921600)

    ap.add_argument("--presence-model", required=True)
    ap.add_argument("--motion-model", required=True)
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

    presence_bundle = joblib.load(
        args.presence_model
    )

    motion_bundle = joblib.load(
        args.motion_model
    )

    # -------------------------------------------------------------------------
    # LIVE INFERENCE THREADING
    # -------------------------------------------------------------------------
    # The Random Forest models were trained with parallel workers.
    # For live operation we predict ONE CSI window at a time, so parallel
    # joblib workers are unnecessary and can produce repeated sklearn warnings.
    #
    # Setting n_jobs=1:
    #   - does NOT retrain either model
    #   - does NOT change the learned trees
    #   - does NOT change the prediction logic
    #   - only changes how prediction is executed
    #
    # This also keeps the live server simpler and lighter.
    presence_live_model = presence_bundle["model"]
    if hasattr(presence_live_model, "n_jobs"):
        presence_live_model.n_jobs = 1

    motion_live_model = motion_bundle["model"]
    if hasattr(motion_live_model, "n_jobs"):
        motion_live_model.n_jobs = 1

    CONTROLLER = Controller(
        args,
        presence_bundle,
        motion_bundle,
    )

    ip = best_local_ip()

    server = ThreadingHTTPServer(
        (args.host, args.port),
        Handler,
    )

    print("=" * 78)
    print("PHASE-2 PHONE CONTROL SERVER")
    print("=" * 78)
    print(f"RX1 / RX2       : {args.rx1} / {args.rx2}")
    print(f"Presence model  : {presence_bundle.get('model_name','unknown')}")
    print(f"Motion model    : {motion_bundle.get('model_name','unknown')}")
    print(f"Countdown       : {args.countdown}s")
    print(f"Calibration     : {args.calibration:.1f}s")
    print(f"Sampling / FS   : {args.fs:.1f} Hz")
    print(f"Window          : {args.window:.1f} s")
    print(f"Update step     : {args.step:.1f} s")
    print(f"Majority vote   : {args.vote}")
    print(f"Laptop URL      : http://127.0.0.1:{args.port}")
    print(f"Phone URL       : http://{ip}:{args.port}")
    print()
    print("PHASE 1: EMPTY / PERSON")
    print("PHASE 2: if PERSON -> STATIC / MOVING")
    print("Latency mode     : parallel voting (no Phase1->Phase2 vote cascade)")
    print()
    print("Detector is IDLE until START is pressed on the phone.")
    print("STOP stops sensing but keeps the phone server alive.")
    print("Ctrl+C here shuts down the server itself.")
    print("=" * 78)

    try:
        server.serve_forever(
            poll_interval=0.25
        )

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
