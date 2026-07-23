"""
═══════════════════════════════════════════════════════════════
 تحميل البيانات الكامل | Full Download
═══════════════════════════════════════════════════════════════
 تحميل من بداية 2024 حتى بداية البيانات المعالجة الموجودة
═══════════════════════════════════════════════════════════════
"""

import os
import sys
from datetime import datetime

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)

from config.settings import TICK_DIR
from src.data_engine.tick_fetcher import fetch_ticks_batched
from src.data_engine.data_cleaner import load_raw_ticks, clean_ticks, quality_report, save_clean

# ─── فترة التحميل ────────────────────────────────────────────
SYMBOL   = "BTCUSD"
DL_START = "2024-01-01"
DL_END   = "2026-03-27"


def run_full_download():
    symbol = SYMBOL

    print("╔══════════════════════════════════════════════════════╗")
    print("║   عبد الحي القيوم - Quant Engine                   ║")
    print("║   DOWNLOAD: BTCUSD 2024-01-01 → 2026-03-27        ║")
    print("╚══════════════════════════════════════════════════════╝")
    print()
    print(f"  Symbol : {symbol}")
    print(f"  Period : {DL_START} → {DL_END}")
    print(f"  Output : {TICK_DIR}")
    print()

    t0 = datetime.now()

    # ── تحميل على دفعات شهرية ───────────────────────────────
    files = fetch_ticks_batched(symbol, DL_START, DL_END)

    elapsed = datetime.now() - t0
    print(f"\n{'═'*55}")
    print(f"  Download: {elapsed}")
    print(f"  Files   : {len(files)}")

    if not files:
        print("  ✗ No files downloaded!")
        return

    # ── تنظيف كل ملف ────────────────────────────────────────
    print(f"\n  Cleaning all files...")
    for i, fpath in enumerate(files, 1):
        print(f"\n─── [{i}/{len(files)}] {os.path.basename(fpath)} ───")
        df = load_raw_ticks(fpath)
        if df is not None and len(df) > 0:
            df = clean_ticks(df)
            quality_report(df)
            tag = os.path.splitext(os.path.basename(fpath))[0] + "_clean"
            save_clean(df, symbol, tag)

    total = datetime.now() - t0
    print()
    print("╔══════════════════════════════════════════════════════╗")
    print("║  ✓ FULL DOWNLOAD COMPLETE                           ║")
    print(f"║  Total time: {str(total):>38s} ║")
    print("╚══════════════════════════════════════════════════════╝")


if __name__ == "__main__":
    run_full_download()
