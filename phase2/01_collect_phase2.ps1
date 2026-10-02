# Phase-2 moving-data collection
# RX1 = COM7, RX2 = COM5
# Run this from phase1\python, or edit $CaptureScript below.

$CaptureScript = ".\01_capture_dual_rx.py"
$OutDir = "..\..\phase2\data\raw_new"

python $CaptureScript --rx1 COM7 --rx2 COM5 --label S01_slow_walk       --duration 60 --out $OutDir
python $CaptureScript --rx1 COM7 --rx2 COM5 --label S01_walk_left_right --duration 60 --out $OutDir
python $CaptureScript --rx1 COM7 --rx2 COM5 --label S01_walk_tx_rx      --duration 60 --out $OutDir

python $CaptureScript --rx1 COM7 --rx2 COM5 --label S02_slow_walk       --duration 60 --out $OutDir
python $CaptureScript --rx1 COM7 --rx2 COM5 --label S02_walk_left_right --duration 60 --out $OutDir
python $CaptureScript --rx1 COM7 --rx2 COM5 --label S02_walk_tx_rx      --duration 60 --out $OutDir

python $CaptureScript --rx1 COM7 --rx2 COM5 --label S03_slow_walk       --duration 60 --out $OutDir
python $CaptureScript --rx1 COM7 --rx2 COM5 --label S03_walk_left_right --duration 60 --out $OutDir
python $CaptureScript --rx1 COM7 --rx2 COM5 --label S03_walk_tx_rx      --duration 60 --out $OutDir
