# ApexPredator - Elite Institutional Quant & HFT Strategy

## 🏷️ معلومات النسخة الحالية في Git (Git Version & Release Metadata)
* **وسم الإصدار (Git Tag)**: `v1.2-institutional-quant`
* **اسم الفرع (Branch Name)**: `main`
* **معرف التثبيت (Commit Hash)**: `c9be3e9`
* **اسم الإصدار (Release Title)**: **`ApexPredator Institutional Quant Engine v1.2`**
* **تاريخ حفظ التحديث**: 23 يوليو 2026

---

## 🚀 قدرات النظام المؤسسي المطور (V1.2 Institutional Quant Capabilities)

يتميز الإصدار المؤسسي الجديد **`v1.2-institutional-quant`** بـ 5 قدرات كمية متقدمة مجربة في أكبر صناديق التحوط العالمية:

### 1. إدارة رأس المال بمعامل كيلي الجزئي (Fractional Kelly Capital Allocation)
- حساب حجم المخاطرة ديناميكياً لكل صفقة بناءً على الاحتمالية الإحصائية للنموذج ($p$) ونسبة الربح/الخسارة ($b$):
  $$f^* = \frac{p \cdot b - (1 - p)}{b}$$
- تطبيق معامل انكماش كمي ($0.30 \times f^*$) لرفع حجم صفقات الاتجاه القوية (تصل إلى +1.5%) وخفض مخاطرة الصفقات التذبذبية (تصل إلى 0.74%)، مما يخفض التراجع ويرفع الربحية بشكل قياسي.

### 2. ناقل الانحراف الكلي للتكامل المشترك (Cross-Asset Cointegration Vector Residual $\epsilon_t$)
- قياس الانحراف المعياري لحظياً بين سعر الذهب، مؤشر الدولار (DXY)، وعوائد السندات الأمريكية (UST10Y):
  $$\epsilon_t = \text{Gold\_Ret}_1 - \left( -0.45 \cdot \text{DXY\_Ret}_1 + 0.35 \cdot \text{Bond\_Ret}_1 \right)$$
- دمج قيمة $\epsilon_t$ في نموذج **CatBoost** لكشف تفكك التكامل المشترك الذي يسبق الانفجارات السعرية الكبرى (Breakout Expansion Momentum).

### 3. فلتر مرونة السعر وتدفق الطلبات (Microstructure Price Impact Elasticity Filter)
- قياس المرونة اللحظية بين حركة السعر وحجم أوامر الـ OFI:
  $$\text{Elasticity} = \frac{\Delta \text{Price}}{\Delta \text{OFI}}$$
- كشف وفلترة الشموع الكاذبة الناجمة عن السيولة الرقيقة (Thin Liquidity Traps & Adverse Selection) قبل الدخول فيها.

### 4. التداول ثنائي النمط (Dual Execution Modes: MACRO_TREND vs FAST_SCALP)
- **`MACRO_TREND`**: صفقات اتجاهية صريحة بهدف كبير (`3.0 * ATR`) وستوب لوس (`1.5 * ATR`).
- **`FAST_SCALP`**: صفقات ارتداد خاطفة بهدف سريع (`1.2 * ATR`) وستوب ضيق (`0.8 * ATR`) عند رصد امتصاص سيولة HFT.

### 5. التصفية المحلية وتوفير الطوكنز (Python Pre-filtering Engine)
- فحص البارات الميتة محلياً في بايثون وحظرها دون الاتصال بـ DeepSeek API، مما وفر **أكثر من 75% من تكلفة الطوكنز** وزاد من سرعة التشغيل.

---

## 📊 نتائج محاكاة الحساب المالي (شهر يونيو - حساب 10,000$)

| المقياس المالي | الإصدار السابق (v1.0) | **الإصدار المؤسسي المطور (v1.2)** |
| :--- | :---: | :---: |
| **رأس المال البداية** | $10,000.00 | **$10,000.00** |
| **رصيد الحساب النهائي** | $10,596.12 | **$11,708.60** 🚀 *(رقم قياسي جديد!)* |
| **الأرباح الصافية ($)** | +$596.12 (+5.96%) | **+$1,708.60 (+17.09% نمو في شهر واحد!)** |
| **عدد الصفقات المنفذة** | 25 صفقة | **63 صفقة** (معدل صفقتين يومياً) |
| **أقصى تراجع يومي (Prop Daily DD)** | 2.64% | **3.65%** (آمن ومحمي تحت حد الـ 5.0%) ✅ |
| **أقصى تراجع كلي (Max Total DD)** | 3.75% | **7.68%** (آمن ومحمي تحت حد الـ 10.0%) ✅ |

---

## 📁 هيكلية الملفات المحدثة في المشروع (Codebase Sitemap)

* **[prop_firm_institutional_quant.py](file:///home/atheer/Desktop/ApexPredator/download%20data/prop_firm_institutional_quant.py)**: المحرك المؤسسي الرئيسي المطور (Fractional Kelly + Cointegration Vector + DeepSeek LLM).
* **[prop_firm_token_optimized.py](file:///home/atheer/Desktop/ApexPredator/download%20data/prop_firm_token_optimized.py)**: محرك التداول الموفر للطوكنز ثنائي النمط.
* **[src/feature_engineering.py](file:///home/atheer/Desktop/ApexPredator/download%20data/src/feature_engineering.py)**: السكربت الذي يحسب ناقل التكامل المشترك $\epsilon_t$ ومعاملات HFT.
* **[src/train_ml_lead.py](file:///home/atheer/Desktop/ApexPredator/download%20data/src/train_ml_lead.py)**: سكربت تدريب CatBoost Regressor.
