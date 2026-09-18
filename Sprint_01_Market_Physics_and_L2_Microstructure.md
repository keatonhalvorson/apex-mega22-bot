# 🎯 سجل ومتابعة الأهداف اليومية والأسبوعية (Sprint 01 - Modern Empirical Edition)
## Sprint 01: Modern Empirical Microstructure & L2 Order Book Physics
### فيزياء عمق السوق اللحظية، تدفق الأوامر وهندسة شموع المعلومات

---

## 📊 لوحة المتابعة والتقدم الإجمالي (Sprint Dashboard)

* 🟢 **تاريخ الانطلاق (Start Date):** `2026-09-18` (الجمعة - غداً صباحاً)
* 🎯 **تاريخ الإغلاق المستهدف (Target Close Date):** `2026-09-25` (الجمعة القادم)
* 📈 **مستوى الإنجاز العام (Overall Progress):** `[▱▱▱▱▱▱▱] 0% جاهز للانطلاق غداً صباحاً`
* 🧭 **المسار في الدستور السيادي:** المرحلة 0 (الموديولات P1, P2, P3, P5, P8 من خارطة الطريق ودستور العالم الكمي)
* 💻 **البيئة ومحرك التداول الحي:** `/home/atheer/Desktop/ApexPredator/download data`
* ⚖️ **الضوابط الشرعية:** تداول فوري نقدي حلال 100% (1x Cash Spot Only - Zero CFDs, Zero Leverage, Zero Shorting).
* 👑 **المرجع الأعلى:** [The_Sovereign_Quant_Scientist_Master_Curriculum.md](file:///home/atheer/Desktop/ApexPredator/download%20data/The_Sovereign_Quant_Scientist_Master_Curriculum.md)

---

## 🗺️ المخطط الزمني للسبرنت (7-Day Empirical Roadmap)

```
       ┌─────────────────────────────────────────────────────────────────────────┐
       │     Sprint 01: Modern Empirical Microstructure & L2 Order Book Physics   │
       └────────────────────────────────────┬────────────────────────────────────┘
                                            │
   ┌───────────────┬────────────────────────┼────────────────────────┬───────────────┐
   ▼               ▼                        ▼                        ▼               ▼
[18 سبتمبر]     [19 سبتمبر]              [20 - 21 سبتمبر]         [22 - 23 سبتمبر] [24 - 25 سبتمبر]
Day 1: L2       Day 2: OFI &             Day 3-4: Dollar Bars,    Day 5-6: FracDiff, Day 7: Integration,
Depth & Micro   Order Flow               VPIN Toxicity &          CUSUM & Purged   Fee Audit &
   Price         Imbalance               Hawkes Cascade Shield       K-Fold CV     Sprint 01 Close
```

---

## 📋 المهام اليومية وقائمة التحقق التفاعلية (Daily Checklist)

---

### 📍 اليوم 1 (الجمعة 18 سبتمبر 2026): تشريح دفتر الأوامر اللحظي وحساب السعر الدقيق (Micro-Price)
* [ ] **📖 الجلسة النظرية المركزة (30%):**
  * `Larry Harris - Trading and Exchanges` ➔ **الفصول 4 و 5** (Orders, Properties & Order-Driven Markets).
  * `Lehalle & Laruelle - Market Microstructure in Practice` ➔ **الفصل 2** (Order Flow & Price Formation).
  * **المعادلة المستهدفة:** استنتاج معادلة السعر المجهري (Stoikov Micro-Price) الموزون بأحجام أول مستوى للطلب والعرض:
    $$P_{\text{micro}} = P_{\text{bid}} \left(\frac{Q_{\text{ask}}}{Q_{\text{bid}} + Q_{\text{ask}}}\right) + P_{\text{ask}} \left(\frac{Q_{\text{bid}}}{Q_{\text{bid}} + Q_{\text{ask}}}\right)$$
* [ ] **💻 الجلسة التطبيقية والهندسية (70%):**
  * قراءة ملف لقطات دفتر الأوامر اللحظي الحي: `l2_live_data/btcusdt_l2_snapshots_2026-07-31.jsonl`.
  * استخراج أفضل سعر طلب وعرض، وحساب السبريد بنقاط الأساس (Spread bps)، وحساب عمق أول 5 مستويات وأول 20 مستوى.
  * كتابة وتشغيل اختبارات الوحدة للتأكد من أن $P_{\text{bid}} \le P_{\text{micro}} \le P_{\text{ask}}$ دائماً:
    `pytest apex_sovereign_engine/test_empirical_microstructure_physics.py`
* 🎯 **معيار إنجاز اليوم (DoD):** تشغيل `python l2_orderbook_analyzer.py` بنجاح وإنتاج تقرير لقطات موثق في `processed_data/l2_analyzed_metrics.csv`.

---

### 📍 اليوم 2 (السبت 19 سبتمبر 2026): اختلال تدفق الأوامر المتعدد (Multi-Level OFI) وقدرته التنبؤية
* [ ] **📖 الجلسة النظرية المركزة (30%):**
  * `Barry Johnson - Algorithmic Trading and DMA` ➔ **الفصل 3 و 4** (Limit Order Book Dynamics).
  * بحث Cont, Kukanov & Stoikov (2014) حول علاقة اختلال تدفق الأوامر بتغيرات الأسعار الفورية:
    $$\text{OFI}_t = I_{\{P_{b,t} \ge P_{b,t-1}\}} Q_{b,t} - I_{\{P_{b,t} \le P_{b,t-1}\}} Q_{b,t-1} - I_{\{P_{a,t} \le P_{a,t-1}\}} Q_{a,t} + I_{\{P_{a,t} \ge P_{a,t-1}\}} Q_{a,t-1}$$
* [ ] **💻 الجلسة التطبيقية والهندسية (70%):**
  * برمجة دالة متجهة لحساب الـ OFI على لقطات L2 المتتالية (100ms snapshots).
  * قياس معامل الارتباط الخطي والرتبي (Pearson & Spearman $IC$) بين $\text{OFI}_t$ والعوائد المستقبلية للأمام ($k=10\text{ seconds}$).
* 🎯 **معيار إنجاز اليوم (DoD):** إثبات إحصائي بأن معامل الارتباط $IC \ge 0.035$ مع قيمة $p < 0.001$.

---

### 📍 اليوم 3 (الأحد 20 سبتمبر 2026): شموع الدولار بار ومؤشر سمية التدفق (VPIN)
* [ ] **📖 الجلسة النظرية المركزة (30%):**
  * `Marcos López de Prado - Advances in Financial ML` ➔ **الفصل 2** (Alternative Bars & Information Sampling).
  * ورقة Easley, López de Prado & O'Hara حول حجم التدفق السام (VPIN - Volume-Synchronized Probability of Toxicity):
    $$\text{VPIN} = \frac{\sum_{\tau=1}^N |V_\tau^B - V_\tau^S|}{N \times V}$$
* [ ] **💻 الجلسة التطبيقية والهندسية (70%):**
  * فحص مجموعة بيانات شموع الدولار بار الحقيقية: `processed_data/btcusdt_dollar_bars_1m.parquet`.
  * حساب الـ VPIN ومؤشر امتصاص السيولة (Absorption Metric) وكشف الجدران المخفية (Icebergs).
  * ربط الميزة بـ `microstructure_intent_engine.py` وحفظ النتائج في `btcusdt_dollar_bars_intent.parquet`.
* 🎯 **معيار إنجاز اليوم (DoD):** خفض معدل الصفقات الخاسرة بنسبة $>20\%$ عند تفعيل فلتر حظر الشراء عندما يكون $\text{VPIN} > 0.65$.

---

### 📍 اليوم 4 (الإثنين 21 سبتمبر 2026): عمليات النقاط ودرع التفرع الذاتي (Hawkes Cascade Shield)
* [ ] **📖 الجلسة النظرية المركزة (30%):**
  * `Cartea & Jaimungal - Algorithmic and High-Frequency Trading` ➔ **الفصل 6 و 10** (Hawkes Processes for Order Arrival).
  * معادلة الكثافة اللحظية لعملية هوكس ذات التلاشي الأسي:
    $$\lambda(t) = \mu + \sum_{t_i < t} \alpha e^{-\beta (t - t_i)}$$
* [ ] **💻 الجلسة التطبيقية والهندسية (70%):**
  * بناء مقدّر لحظي خفيف (Online Recursive Hawkes Estimator) لكثافة تدفق الصفقات البيعية الكبيرة.
  * برمجة "درع هوكس" (Hawkes Cascade Shield) لإلغاء أي أوامر شراء معلقة فوراً عندما تتجاوز الكثافة العتبة الحرجة $\lambda(t) > \mu + 3\sigma_\lambda$.
* 🎯 **معيار إنجاز اليوم (DoD):** حماية المحفظة من الإنزلاقات أثناء الفلاش كراش وخفض أقصى هبوط بنسبة ملحوظة.

---

### 📍 اليوم 5 (الثلاثاء 22 سبتمبر 2026): التفاضل الكسري (Fractional Differencing) وحفظ الذاكرة
* [ ] **📖 الجلسة النظرية المركزة (30%):**
  * `Marcos López de Prado - Advances in Financial ML` ➔ **الفصل 5** (Fractionally Differentiated Features).
  * المتسلسلة ذات الحدين ومبرهنة الذاكرة الطويلة:
    $$(1-B)^d = 1 - dB + \frac{d(d-1)}{2!} B^2 - \frac{d(d-1)(d-2)}{3!} B^3 + \dots$$
* [ ] **💻 الجلسة التطبيقية والهندسية (70%):**
  * اختبار قيم $d \in [0.1, 0.9]$ بخطوة $0.05$ على إغلاقات شموع الدولار بار لـ BTC.
  * تطبيق اختبار ديكي-فولر المطور (ADF Test) على كل قيمة $d$ وحساب معامل الارتباط مع السلسلة الأصلية.
  * استخراج $d^*$ الأمثل الذي يحقق الاستقرار ($p\text{-value} < 0.01$) مع الحفاظ على ارتباط $> 90\%$.
* 🎯 **معيار إنجاز اليوم (DoD):** إنتاج ميزة سعرية مستقرة إحصائياً تحتفظ بذاكرة الترند لاستخدامها كمدخل لنماذج التصنيف.

---

### 📍 اليوم 6 (الأربعاء 23 سبتمبر 2026): فلتر CUSUM والتجزئة المطهرة (Purged & Embargoed CV)
* [ ] **📖 الجلسة النظرية المركزة (30%):**
  * `Marcos López de Prado - Advances in Financial ML` ➔ **الفصل 2** (CUSUM Filter) + **الفصل 7** (Cross-Validation).
  * فهم سبب فشل K-Fold العادي في السلاسل المالية وكيفية تطبيق الـ Purging والـ Embargo للقضاء على التسريب الزمني.
* [ ] **💻 الجلسة التطبيقية والهندسية (70%):**
  * بناء فلتر CUSUM متماثل لاقتناص الأحداث السعرية التي تتجاوز انحراف التذبذب المحلي $\pm 2\sigma$.
  * تطبيق خوارزمية `PurgedKFold` مع حظر بنسبة 1% من طول السلسلة.
  * اختبار كود استراتيجية التداول والتأكد من خلوه التام من التسريب.
* 🎯 **معيار إنجاز اليوم (DoD):** تشغيل الباكتست بنظام Walk-Forward المنقى والتأكد من ثبات معدل شارب خارج العينة ($Sharpe > 1.8$).

---

### 📍 اليوم 7 والختام (الخميس 24 - الجمعة 25 سبتمبر 2026): التكامل الشامل وفحص الأثر السعري والرسوم
* [ ] **📖 الجلسة النظرية المركزة (30%):**
  * `Barry Johnson - Algorithmic Trading and DMA` ➔ **الفصل 4** (Kyle-Obizhaeva Market Impact & Square-Root Law).
  * دراسة أثر عمولة بينانس الفورية (0.075% Taker Fee) وكيفية التحول لأوامر Limit صانعة للسوق لتوفير الرسوم.
* [ ] **💻 الجلسة التطبيقية والهندسية (70%):**
  * ربط كافة الميزات (L2 Micro-Price, OFI, Dollar Bars, VPIN, Hawkes Shield, FracDiff) بمحرك التداول `apex_sovereign_engine`.
  * تشغيل الاختبارات الشاملة: `pytest apex_sovereign_engine/test_mega22_parity.py` و `test_mega22_dashboard.py` و `test_empirical_microstructure_physics.py`.
  * مراجعة وتدقيق أداء المحفظة على بيانات 2025 و 2026 وتوليد التقرير النهائي.
* 🎯 **معيار إنجاز السبرنت بالكامل (Final DoD):**
  * اجتياز جميع اختبارات الـ Parity بنجاح بنسبة 100% (18/18 Tests Passed).
  * تحقيق عامل ربحية $\text{Profit Factor} \ge 1.40$ بعد خصم الرسوم الفعلية.
  * كتابة تقرير التوثيق والدروس المستفادة والانتقال رسمياً إلى **Sprint 02 (High-Frequency Execution & Cointegration Stat-Arb)**!

---

## 🏆 معايير الاعتماد المؤسساتي للسبرنت (Definition of Done - DoD)
* [ ] الكود البرمجي يعمل بالكامل داخل بيئة `/home/atheer/Desktop/ApexPredator/download data`.
* [ ] لا استخدام لأي رافعة مالية أو مشتقات أو عقود فروقات (100% Halal Spot Cash Only).
* [ ] التحقق من خلو جميع المتجهات من تسريب المستقبل (*Zero Lookahead Bias*).
* [ ] توثيق نتائج ومخرجات كل يوم في سجل الملاحظات أدناه.

---

## 📝 سجل الملاحظات والنتائج اليومية (Lab Journal)

* **18 سبتمبر 2026 (اليوم 1):** *(جاهز للانطلاق غداً صباحاً - تشريح لقطات L2 واستخراج Micro-Price)*
* **19 سبتمبر 2026 (اليوم 2):** *(حساب OFI وقياس الـ IC)*
* **20 سبتمبر 2026 (اليوم 3):** *(توليد Dollar Bars وحساب VPIN)*
* **21 سبتمبر 2026 (اليوم 4):** *(بناء Hawkes Cascade Shield)*
* **22 سبتمبر 2026 (اليوم 5):** *(استخراج $d^*$ للتفاضل الكسري)*
* **23 سبتمبر 2026 (اليوم 6):** *(تطبيق CUSUM Filter و Purged K-Fold)*
* **24 - 25 سبتمبر 2026 (اليوم 7):** *(فحص التكامل، محاكاة الرسوم والانزلاق، وإغلاق السبرنت الأول بنجاح)*
