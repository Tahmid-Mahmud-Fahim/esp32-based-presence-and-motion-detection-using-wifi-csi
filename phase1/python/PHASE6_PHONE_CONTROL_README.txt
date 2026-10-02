PHASE 6B — PHONE-CONTROLLED PHASE-1 DETECTOR

What you can do from the phone:
- START OPERATION
- watch the countdown
- watch EMPTY calibration progress
- see live EMPTY / PERSON
- see PERSON probability and RX health
- STOP OPERATION at any time
- START again later

Important:
The laptop must have this lightweight web-control server running first.
Later you can configure Windows to start the server automatically at boot.

Put 08_phase6_phone_control.py in:
E:\Study\Micro_Project_Final_Try_1\phase1\python\

Keep:
phase1\python\07_live_presence_calibrated.py
phase1\presence\csi_utils.py
phase1\models\presence_model.joblib
phase1\data\processed\empty_baseline.npz

Run once on laptop:

cd "E:\Study\Micro_Project_Final_Try_1\phase1\python"

python 08_phase6_phone_control.py `
--rx1 COM6 `
--rx2 COM8 `
--model ..\models\presence_model.joblib `
--training-baseline ..\data\processed\empty_baseline.npz `
--countdown 5 `
--calibration 12 `
--port 8080

Open the printed Phone URL on a phone connected to the same normal Wi-Fi/LAN.

Phone flow:
READY
-> START OPERATION
-> 5-second countdown
-> 12-second EMPTY calibration
-> live EMPTY/PERSON
-> STOP OPERATION
-> READY

STOP works during countdown, calibration, or live detection.

If Windows Firewall prompts, allow Python on Private networks.
