"""Interactive dataset collector using data/collection_plan.csv."""
import argparse, csv, subprocess, sys
from pathlib import Path


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--rx1',required=True); ap.add_argument('--rx2',required=True)
    ap.add_argument('--plan',default='data/collection_plan.csv'); ap.add_argument('--out',default='data/raw')
    ap.add_argument('--start',default=None,help='optional session_id to start from')
    args=ap.parse_args()
    rows=list(csv.DictReader(open(args.plan,encoding='utf-8')))
    if args.start:
        ids=[r['session_id'] for r in rows]
        if args.start not in ids: raise SystemExit(f'{args.start} not found in plan')
        rows=rows[ids.index(args.start):]
    capture=Path(__file__).with_name('01_capture_dual_rx.py')
    for i,r in enumerate(rows,1):
        sid=r['session_id']; dur=float(r['duration_s'])
        print('\n'+'='*72)
        print(f"SESSION {i}/{len(rows)}: {sid}")
        print(f"Label={r['label']}  Split={r['split']}  Subject={r['subject']}  Scenario={r['scenario']}")
        print(r.get('notes',''))
        ans=input("Set up this condition. ENTER=record, s=skip, q=quit: ").strip().lower()
        if ans=='q': break
        if ans=='s': continue
        cmd=[sys.executable,str(capture),'--rx1',args.rx1,'--rx2',args.rx2,'--label',sid,'--duration',str(dur),'--out',args.out]
        rc=subprocess.call(cmd)
        if rc!=0:
            print(f'Capture failed with code {rc}. Stopping.'); break

if __name__=='__main__': main()
