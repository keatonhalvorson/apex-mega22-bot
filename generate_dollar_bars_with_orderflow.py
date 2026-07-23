import os
import numpy as np
import pandas as pd

try:
    from numba import njit
except ImportError:
    def njit(*args, **kwargs):
        def decorator(func):
            return func
        return decorator


@njit(cache=False)
def _assign_bar_ids_accumulate_reset(dollar_values, threshold, start_bar_id):
    """
    تعيين bar_id بمنطق accumulate-and-reset:

    - كل tick ينتمي إلى البار الحالي.
    - إذا أصبح التراكم >= threshold بعد هذا tick، يُغلق البار.
    - يبدأ tick التالي في بار جديد.
    - لا يتم تقسيم tick واحد على أكثر من بار، حتى لو تجاوز العتبة وحده.
    """
    n = dollar_values.shape[0]
    bar_ids = np.empty(n, dtype=np.int64)

    cum = 0.0
    current_bar_id = start_bar_id

    for i in range(n):
        value = dollar_values[i]

        if not np.isfinite(value) or value < 0.0:
            value = 0.0

        cum += value
        bar_ids[i] = current_bar_id

        if cum >= threshold:
            current_bar_id += 1
            cum = 0.0

    return bar_ids, current_bar_id


def _validate_parameters(
    input_path: str,
    output_path: str,
    threshold: float,
    volume_multiplier: float,
    chunksize: int,
):
    if not input_path:
        raise ValueError("input_path فارغ.")

    if not output_path:
        raise ValueError("output_path فارغ.")

    if not os.path.exists(input_path):
        raise FileNotFoundError(f"ملف الإدخال غير موجود: {input_path}")

    if not np.isfinite(threshold) or threshold <= 0:
        raise ValueError("threshold يجب أن يكون رقمًا موجبًا.")

    if not np.isfinite(volume_multiplier) or volume_multiplier <= 0:
        raise ValueError("volume_multiplier يجب أن يكون رقمًا موجبًا.")

    if not isinstance(chunksize, int) or chunksize <= 0:
        raise ValueError("chunksize يجب أن يكون عددًا صحيحًا موجبًا.")


def _validate_required_columns(chunk: pd.DataFrame):
    required_cols = [
        "timestamp",
        "mid_price",
        "bid_price",
        "ask_price",
        "bid_volume",
        "ask_volume",
    ]

    missing = [col for col in required_cols if col not in chunk.columns]

    if missing:
        raise ValueError(
            "الأعمدة التالية مفقودة من ملف CSV: "
            + ", ".join(missing)
        )


def _safe_to_numeric(df: pd.DataFrame, cols):
    for col in cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def generate_dollar_bars_streaming(
    input_path: str,
    output_path: str,
    threshold: float = 2_000_000_000.0,
    volume_multiplier: float = 100.0,
    chunksize: int = 2_000_000,
    write_final_incomplete_bar: bool = True,
    warn_open_bar_rows: bool = True,
):
    """
    Dollar Bars v6.2 — Streaming Version
    ====================================

    الفكرة:
    -------
    توليد Dollar Bars من بيانات L1 Quotes باستخدام trade_dollar_value
    المستدل عليه بقاعدة Tick Rule، وليس book_dollar_value.

    الإصلاحات:
    ----------
    1. استخدام accumulate-and-reset بدل cum_dollars // threshold.
    2. منع تضخيم carryover_row مرة ثانية بـ volume_multiplier.
    3. الحفاظ على آخر tick_direction غير صفري بين الـ chunks.
    4. الحفاظ على استمرارية diff/shift بين الـ chunks.
    5. حمل البار المفتوح كـ DataFrame بدل list[dict].
    6. إضافة حارس تشخيصي إذا كان البار المفتوح يمتد عبر أكثر من chunk.
    7. إنشاء مجلد الإخراج تلقائيًا.
    8. فحص الأعمدة الأساسية وتحويل الأعمدة الرقمية بأمان.
    9. fallback تلقائي إذا لم تكن numba مثبتة.

    ملاحظة:
    -------
    إذا كان threshold كبيرًا جدًا مقارنةً بـ trade_dollar_value لكل tick،
    قد يمتد بار واحد عبر عدة chunks، وهذا يرفع استهلاك الذاكرة.
    """

    _validate_parameters(
        input_path=input_path,
        output_path=output_path,
        threshold=threshold,
        volume_multiplier=volume_multiplier,
        chunksize=chunksize,
    )

    print(f"⏳ بدء توليد Dollar Bars | Chunksize={chunksize:,}")

    output_dir = os.path.dirname(output_path)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    if os.path.exists(output_path):
        os.remove(output_path)

    carryover_row = None
    carryover_tick_direction = 0.0

    incomplete_bar_df = None
    carryover_bar_id = 0

    is_first_write = True
    total_bars_generated = 0
    first_chunk = True

    diff_cols = [
        "mid_price",
        "bid_price",
        "ask_price",
        "bid_volume",
        "ask_volume",
    ]

    numeric_cols = [
        "mid_price",
        "bid_price",
        "ask_price",
        "bid_volume",
        "ask_volume",
        "total_volume",
    ]

    reader = pd.read_csv(
        input_path,
        chunksize=chunksize,
        low_memory=False,
    )

    for chunk_idx, chunk in enumerate(reader):
        print(f"📦 معالجة الجزء رقم {chunk_idx + 1} ...")

        if first_chunk:
            _validate_required_columns(chunk)
            first_chunk = False

        prepended_helper = carryover_row is not None

        if prepended_helper:
            helper_df = pd.DataFrame([carryover_row])
            work = pd.concat([helper_df, chunk], ignore_index=True)
        else:
            work = chunk.copy()

        work = _safe_to_numeric(work, numeric_cols)

        # إذا كان هناك helper row، فهو آتٍ من chunk سابق وقد ضُرب مسبقًا في volume_multiplier.
        # لذلك نبدأ الضرب من الصف 1، لا من الصف 0.
        scale_start = 1 if prepended_helper else 0

        for col in ["total_volume", "bid_volume", "ask_volume"]:
            if col in work.columns:
                work.loc[scale_start:, col] = (
                    work.loc[scale_start:, col].astype(float) * volume_multiplier
                )

        work["book_volume"] = work["bid_volume"] + work["ask_volume"]
        work["book_dollar_value"] = work["mid_price"] * work["book_volume"]

        valid_mask = (
            np.isfinite(work["book_dollar_value"])
            & (work["book_dollar_value"] > 0)
            & np.isfinite(work["mid_price"])
            & np.isfinite(work["ask_price"])
            & np.isfinite(work["bid_price"])
            & np.isfinite(work["bid_volume"])
            & np.isfinite(work["ask_volume"])
            & (work["bid_volume"] >= 0)
            & (work["ask_volume"] >= 0)
            & (work["ask_price"] > 0)
            & (work["bid_price"] > 0)
            & (work["mid_price"] > 0)
        )

        if prepended_helper and len(valid_mask) > 0:
            valid_mask.iloc[0] = True

        work = work[valid_mask].reset_index(drop=True)

        if work.empty:
            continue

        # Tick Rule مع استمرارية عبر الـ chunks.
        price_diff = work["mid_price"].diff()
        raw_tick_direction = np.sign(price_diff).replace(0, np.nan)

        if prepended_helper:
            raw_tick_direction.iloc[0] = carryover_tick_direction

        tick_direction = raw_tick_direction.ffill().fillna(0.0)
        work["tick_direction"] = tick_direction.astype(float).values

        work["inferred_trade_price"] = np.where(
            work["tick_direction"] > 0,
            work["ask_price"],
            np.where(
                work["tick_direction"] < 0,
                work["bid_price"],
                work["mid_price"],
            ),
        )

        work["inferred_trade_volume"] = np.where(
            work["tick_direction"] > 0,
            work["ask_volume"],
            np.where(
                work["tick_direction"] < 0,
                work["bid_volume"],
                0.0,
            ),
        )

        work["trade_dollar_value"] = (
            work["inferred_trade_price"] * work["inferred_trade_volume"]
        )

        work["tick_rule_signed_flow"] = (
            work["trade_dollar_value"] * work["tick_direction"]
        )

        work["quote_imbalance"] = np.where(
            work["book_volume"] > 0,
            (work["bid_volume"] - work["ask_volume"]) / work["book_volume"],
            np.nan,
        )

        work["quote_imbalance_dollar"] = (
            work["quote_imbalance"].fillna(0.0) * work["trade_dollar_value"]
        )

        # Continuous OFI مع استمرارية shift عبر helper row.
        prev_bid_p = work["bid_price"].shift(1)
        prev_ask_p = work["ask_price"].shift(1)
        prev_bid_v = work["bid_volume"].shift(1)
        prev_ask_v = work["ask_volume"].shift(1)

        bid_ofi = np.where(
            work["bid_price"] > prev_bid_p,
            work["bid_volume"],
            np.where(
                work["bid_price"] == prev_bid_p,
                work["bid_volume"] - prev_bid_v,
                -prev_bid_v,
            ),
        )

        ask_ofi = np.where(
            work["ask_price"] < prev_ask_p,
            work["ask_volume"],
            np.where(
                work["ask_price"] == prev_ask_p,
                work["ask_volume"] - prev_ask_v,
                -prev_ask_v,
            ),
        )

        work["cont_ofi_units"] = pd.Series(
            bid_ofi - ask_ofi,
            index=work.index,
        ).fillna(0.0).values

        work["cont_ofi_dollar"] = work["mid_price"] * work["cont_ofi_units"]

        # حذف helper row بعد استخدامه فقط لاستمرارية diff/shift/tick rule.
        if prepended_helper:
            work = work.iloc[1:].reset_index(drop=True)

            if work.empty:
                continue

        # تحديث آخر tick_direction غير صفري.
        nonzero_tick_direction = work.loc[
            work["tick_direction"] != 0,
            "tick_direction",
        ]

        if len(nonzero_tick_direction) > 0:
            carryover_tick_direction = float(nonzero_tick_direction.iloc[-1])

        # حفظ آخر صف صالح لاستمرارية الجزء التالي.
        carryover_row = work.iloc[-1][diff_cols].copy()

        # إضافة صفوف البار المفتوح من الجزء السابق.
        if incomplete_bar_df is not None and not incomplete_bar_df.empty:
            work = pd.concat(
                [incomplete_bar_df, work],
                ignore_index=True,
            )
            incomplete_bar_df = None

        dollar_values = (
            pd.to_numeric(work["trade_dollar_value"], errors="coerce")
            .fillna(0.0)
            .clip(lower=0.0)
            .values
            .astype(np.float64)
        )

        bar_ids, next_open_bar_id = _assign_bar_ids_accumulate_reset(
            dollar_values,
            float(threshold),
            int(carryover_bar_id),
        )

        work["bar_id"] = bar_ids

        # البار المفتوح هو البار الذي يحمل next_open_bar_id.
        # إن لم توجد صفوف بهذا المعرف، فهذا يعني أن آخر tick أغلق البار تمامًا.
        open_bar_mask = work["bar_id"] == next_open_bar_id

        if open_bar_mask.any():
            incomplete_bar_df = work.loc[open_bar_mask].copy()
            work = work.loc[~open_bar_mask].reset_index(drop=True)
        else:
            incomplete_bar_df = None

        carryover_bar_id = int(next_open_bar_id)

        if (
            warn_open_bar_rows
            and incomplete_bar_df is not None
            and len(incomplete_bar_df) > chunksize
        ):
            print(
                f"⚠️ تحذير: البار المفتوح يحتوي الآن على "
                f"{len(incomplete_bar_df):,} صفًا، وهو أكبر من chunksize={chunksize:,}. "
                f"قد تكون threshold={threshold:,.2f} كبيرة جدًا مقارنةً بالتدفق الدولاري لكل tick."
            )

        if work.empty:
            continue

        bars = work.groupby("bar_id", sort=True).agg(
            timestamp=("timestamp", "last"),
            open=("inferred_trade_price", "first"),
            high=("inferred_trade_price", "max"),
            low=("inferred_trade_price", "min"),
            close=("inferred_trade_price", "last"),
            total_book_volume=("book_volume", "sum"),
            total_trade_volume=("inferred_trade_volume", "sum"),
            total_dollar_value=("trade_dollar_value", "sum"),
            tick_rule_signed_flow=("tick_rule_signed_flow", "sum"),
            trade_dollar_value_sum=("trade_dollar_value", "sum"),
            quote_imbalance_dollar_sum=("quote_imbalance_dollar", "sum"),
            cont_ofi_dollar=("cont_ofi_dollar", "sum"),
            num_ticks=("mid_price", "count"),
        ).reset_index(drop=True)

        bars["vwap"] = np.where(
            bars["total_trade_volume"] != 0,
            bars["total_dollar_value"] / bars["total_trade_volume"],
            np.nan,
        )

        bars["tick_rule_ofi_ratio"] = np.where(
            bars["trade_dollar_value_sum"] != 0,
            bars["tick_rule_signed_flow"] / bars["trade_dollar_value_sum"],
            np.nan,
        )

        bars["quote_imbalance_ratio"] = np.where(
            bars["total_dollar_value"] != 0,
            bars["quote_imbalance_dollar_sum"] / bars["total_dollar_value"],
            np.nan,
        )

        bars.drop(
            columns=[
                "trade_dollar_value_sum",
                "quote_imbalance_dollar_sum",
            ],
            inplace=True,
        )

        col_order = [
            "timestamp",
            "open",
            "high",
            "low",
            "close",
            "total_book_volume",
            "total_trade_volume",
            "total_dollar_value",
            "vwap",
            "tick_rule_signed_flow",
            "tick_rule_ofi_ratio",
            "quote_imbalance_ratio",
            "cont_ofi_dollar",
            "num_ticks",
        ]

        bars = bars[col_order]

        if is_first_write:
            bars.to_csv(output_path, index=False, mode="w")
            is_first_write = False
        else:
            bars.to_csv(output_path, index=False, mode="a", header=False)

        total_bars_generated += len(bars)

    # كتابة البار الأخير غير المكتمل في نهاية الملف، إذا كان الخيار مفعّلًا.
    if (
        write_final_incomplete_bar
        and incomplete_bar_df is not None
        and not incomplete_bar_df.empty
    ):
        tail = incomplete_bar_df.copy()

        trade_vol = tail["inferred_trade_volume"].sum()
        trade_dv = tail["trade_dollar_value"].sum()
        signed_flow = tail["tick_rule_signed_flow"].sum()
        quote_imbalance_dollar_sum = tail["quote_imbalance_dollar"].sum()

        final_bar = pd.DataFrame([{
            "timestamp": tail["timestamp"].iloc[-1],
            "open": tail["inferred_trade_price"].iloc[0],
            "high": tail["inferred_trade_price"].max(),
            "low": tail["inferred_trade_price"].min(),
            "close": tail["inferred_trade_price"].iloc[-1],
            "total_book_volume": tail["book_volume"].sum(),
            "total_trade_volume": trade_vol,
            "total_dollar_value": trade_dv,
            "vwap": (trade_dv / trade_vol) if trade_vol != 0 else np.nan,
            "tick_rule_signed_flow": signed_flow,
            "tick_rule_ofi_ratio": (
                signed_flow / trade_dv
            ) if trade_dv != 0 else np.nan,
            "quote_imbalance_ratio": (
                quote_imbalance_dollar_sum / trade_dv
            ) if trade_dv != 0 else np.nan,
            "cont_ofi_dollar": tail["cont_ofi_dollar"].sum(),
            "num_ticks": len(tail),
        }])

        if is_first_write:
            final_bar.to_csv(output_path, index=False, mode="w")
            is_first_write = False
        else:
            final_bar.to_csv(output_path, index=False, mode="a", header=False)

        total_bars_generated += 1

    print(
        f"✅ اكتمل التوليد! "
        f"إجمالي البارات: {total_bars_generated:,} | "
        f"الحفظ في: {output_path}"
    )


if __name__ == "__main__":
    input_file = "/home/atheer/Desktop/ApexPredator/gold_data/gc_l1_quotes.csv"
    output_file = "/home/atheer/Desktop/ApexPredator/process data/dollar_bars_v6_2.csv"

    generate_dollar_bars_streaming(
        input_path=input_file,
        output_path=output_file,
        threshold=2_000_000_000.0,
        volume_multiplier=100.0,
        chunksize=2_000_000,
        write_final_incomplete_bar=True,
        warn_open_bar_rows=True,
    )