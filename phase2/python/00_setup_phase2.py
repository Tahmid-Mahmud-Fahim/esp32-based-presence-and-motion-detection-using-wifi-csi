from pathlib import Path
import shutil

HERE = Path(__file__).resolve()
PHASE2_ROOT = HERE.parents[1]

for d in [
    PHASE2_ROOT / "data" / "raw_new",
    PHASE2_ROOT / "data" / "processed",
    PHASE2_ROOT / "models",
    PHASE2_ROOT / "reports",
]:
    d.mkdir(parents=True, exist_ok=True)

bundle_manifest = PHASE2_ROOT / "manifest_phase2.csv"
target_manifest = PHASE2_ROOT / "data" / "manifest.csv"

if bundle_manifest.exists():
    shutil.copy2(bundle_manifest, target_manifest)
    print(f"Manifest copied to: {target_manifest}")
else:
    print("manifest_phase2.csv not found beside the phase2 folder root.")
    print("Copy it manually to phase2/data/manifest.csv")

print("Phase-2 folder setup complete.")
