import os
os.environ["STREAMLIT_SERVER_HEADLESS"] = "true"
import streamlit as st
import io, json, re
from datetime import date
from PIL import Image
from docx import Document
from fpdf import FPDF
import requests
from streamlit_lottie import st_lottie
try:
    from google import genai
except Exception:
    genai = None

st.set_page_config(page_title="EBillX - Electricity Bill Analyzer", page_icon="⚡", layout="wide", initial_sidebar_state="expanded")

def get_client():
    key = None
    if "GEMINI_API_KEY" in os.environ:
        key = os.environ["GEMINI_API_KEY"]
    else:
        try:
            key = st.secrets["GEMINI_API_KEY"]
        except Exception:
            key = None
    if not key or genai is None:
        return None
    try:
        return genai.Client(api_key=key)
    except Exception:
        return None

client = get_client()

@st.cache_data
def load_lottie(url: str):
    try:
        r = requests.get(url, timeout=8)
        if r.status_code == 200:
            return r.json()
    except:
        pass
    return None

LOTTIE = load_lottie("https://assets10.lottiefiles.com/packages/lf20_jtbfg2nb.json")

st.markdown("""
<style>
body, .stApp { background-color: #0b1220 !important; color: #e6edf3 !important; font-family: 'Inter', sans-serif !important; }
h1, h2, h3, h4 { color: #58a6ff !important; font-weight: 700 !important; }
p, label, .stText { color: #c9d1d9 !important; }
.stTextInput > div > div > input, textarea { background-color: #0f1724 !important; color: #e6edf3 !important; border: 1px solid #263241 !important; border-radius: 10px !important; padding: 8px !important; }
.css-1n76uvr, .stFileUploader { background-color: #0f1724 !important; border: 2px dashed #263241 !important; border-radius: 12px !important; color: #c9d1d9 !important; padding: 12px !important; }
.stButton>button { background-color: #238636 !important; color: white !important; border-radius: 8px !important; padding: 10px 18px !important; font-weight:600 !important; }
.card { background-color: #0f1724 !important; padding: 18px; border-radius: 12px; box-shadow: 0 6px 24px rgba(0,0,0,0.6); }
.stCodeBlock, .stJson { background-color: #071024 !important; border: 1px solid #263241 !important; color: #e6edf3 !important; padding: 12px !important; border-radius: 8px !important; }
table, th, td { border-collapse: collapse; padding:8px; }
th { background:#0e2a3a; color:#e6edf3; }
td { background:#08151b; color:#c9d1d9; }
</style>
""", unsafe_allow_html=True)

def safe_clean_json(text):
    if not text:
        return None
    s = text.strip()
    s = re.sub(r"^```(?:json)?", "", s, flags=re.IGNORECASE).strip()
    s = re.sub(r"```$", "", s).strip()
    s = re.sub(r'[\u200b-\u200f\u202a-\u202e]', '', s)
    try:
        return json.loads(s)
    except:
        m = re.search(r"\{.*\}", s, flags=re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except:
                pass
        m2 = re.search(r"\[.*\]", s, flags=re.DOTALL)
        if m2:
            try:
                return json.loads(m2.group(0))
            except:
                pass
    return None

def call_gemini_extract(image_file, extra_context=""):
    if client is None:
        return None, "Gemini client not configured"
    try:
        img = Image.open(image_file)
        prompt = (
            "You are an expert extractor. From the provided electricity bill image, return a JSON only with keys: "
            "Consumer_ID, Consumer_Name, Sanctioned_Load_kW, Units_Consumed_kWh, Billing_Date, Total_Amount_Payable_INR, Discom_Name, Division, Tariff_Category, Raw_Bill_Text. "
            "If any value is missing, set it to 'N/A'. Provide values as simple strings or numbers. Context: " + extra_context
        )
        resp = client.models.generate_content(model="gemini-2.5-flash", contents=[prompt, img])
        text = getattr(resp, "text", None) or str(resp)
        parsed = safe_clean_json(text)
        if parsed is None:
            return None, "Gemini returned non-JSON or unparsable response"
        return parsed, None
    except Exception as e:
        return None, str(e)

def call_gemini_calculate_and_explain(bill_payload, extra_context=""):
    if client is None:
        return None, "Gemini client not configured"
    try:
        prompt = (
            "You are a billing expert. Given the extracted bill data and raw text, identify the applicable discom, division, tariff category, fixed charge, slab structure (range and rate), duty percentage and any surcharge. "
            "Then calculate slab-wise energy charges, fixed charges and duty and present a full breakdown and final total. Finally compare your calculated total with the provided Total_Amount_Payable_INR and output a JSON with keys: discom, division, tariff_category, fixed_per_kw, slabs (list of {range, rate}), duty, calculation {fixed, energy_details, energy_total, duty, total}, bill_correct (true/false), difference. Use the bill data below and extra context: "
            + json.dumps(bill_payload, ensure_ascii=False)
        )
        resp = client.models.generate_content(model="gemini-2.5-flash", contents=[prompt])
        text = getattr(resp, "text", None) or str(resp)
        parsed = safe_clean_json(text)
        if parsed is None:
            return None, "Gemini calculation returned non-JSON or unparsable response"
        return parsed, None
    except Exception as e:
        return None, str(e)

def call_gemini_letter(bill, calculation_json, selected_mistakes, extra_context, officer, lang, mobile, app_date):
    if client is None:
        return None, "Gemini client not configured"
    try:
        prompt = (
            f"You are a formal government letter writer. Using the bill data, calculation results and user context, write a formal complaint letter addressed to {officer}. "
            f"Include the identified mistakes and request action. Language: {lang}. Mobile: {mobile}. Date: {app_date}. "
            "Bill data:\n" + json.dumps(bill, ensure_ascii=False) + "\nCalculation:\n" + json.dumps(calculation_json, ensure_ascii=False) + "\nMistakes:\n" + json.dumps(selected_mistakes, ensure_ascii=False) + "\nUser context:\n" + extra_context + "\nOutput only the final letter text."
        )
        resp = client.models.generate_content(model="gemini-2.5-flash", contents=[prompt])
        text = getattr(resp, "text", None) or str(resp)
        clean = re.sub(r'[\u200b-\u200f\u202a-\u202e]', '', text).strip()
        return clean, None
    except Exception as e:
        return None, str(e)

def generate_local_simple_letter(bill, mistakes, officer, lang, mobile, app_date, extra_context):
    points = "\n".join(["- " + (m.get("Description_Hindi") or m.get("description") or "") for m in mistakes]) if mistakes else ""
    context_para = extra_context if extra_context and extra_context.strip() != "" else ""
    if lang == "हिंदी":
        letter = f"""सेवा में,
{officer}
{bill.get('Discom_Name','')}
दिनांक: {app_date}

विषय: बिजली बिल में विसंगति के संबंध में शिकायत — उपभोक्ता संख्या {bill.get('Consumer_ID','N/A')}

मान्यवर,

मैं, {bill.get('Consumer_Name','N/A')} (उपभोक्ता संख्या: {bill.get('Consumer_ID','N/A')}), सूचित करता/करती हूँ कि मेरे बिल में निम्नलिखित विसंगतियाँ पाई गईं:
{points}

{context_para}

कृपया बिल की जाँच कर आवश्यक सुधार करें। कृपया कार्रवाई की सूचना मेरे मोबाइल {mobile} पर उपलब्ध कराएँ।

धन्यवाद,
{bill.get('Consumer_Name','N/A')}
"""
    else:
        letter = f"""To,
{officer}
{bill.get('Discom_Name','')}
Date: {app_date}

Subject: Complaint regarding discrepancy in electricity bill — Consumer ID {bill.get('Consumer_ID','N/A')}

Respected Sir/Madam,

I, {bill.get('Consumer_Name','N/A')} (Consumer ID: {bill.get('Consumer_ID','N/A')}), wish to inform you of the following discrepancies in my bill:
{points}

{context_para}

Kindly re-check the bill and make necessary corrections. Please notify me at mobile {mobile}.

Thank you,
{bill.get('Consumer_Name','N/A')}
"""
    return letter


def create_pdf_buffer(text):
    text = re.sub(r'[\u200b-\u200f\u202a-\u202e]', '', text)

    pdf = FPDF(format='A4')
    pdf.add_page()
    pdf.set_left_margin(12)
    pdf.set_right_margin(12)

    try:
        pdf.add_font("NotoSans", "", "NotoSans-Regular.ttf", uni=True)
        pdf.set_font("NotoSans", size=11)
    except:
        pdf.set_font("Arial", size=11)

    max_width = pdf.w - 24

    for para in text.split("\n"):
        line = para.strip()
        if line == "":
            pdf.ln(6)
            continue

        while len(line) > 0:
            try:
                pdf.multi_cell(max_width, 6, line)
                break
            except Exception:
                if len(line) <= 1:
                    break
                split_at = max(1, int(len(line) * 0.8))
                part = line[:split_at]
                try:
                    pdf.multi_cell(max_width, 6, part)
                    line = line[split_at:].lstrip()
                except Exception:
                    line = line[1:]

    pdf_bytes = bytes(pdf.output(dest='S'))
    buf = io.BytesIO(pdf_bytes)
    buf.seek(0)
    return buf

def create_docx_buffer(text):
    doc = Document()
    for line in text.split("\n"):
        doc.add_paragraph(line)
    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf

def pretty_json(v):
    try:
        return json.dumps(v, ensure_ascii=False, indent=2)
    except:
        return str(v)

st.title("⚡ EBillX — Electricity Bill Analyzer")
ui_lang = st.radio("App भाषा / App Language", ["हिंदी", "English"], horizontal=True)

col1, col2 = st.columns([1,2])
with col1:
    image_path = "/mnt/data/1675e9e4-ed9d-4eec-9d54-b394297d95a8.png"
    try:
        img = Image.open(image_path)
        st.image(img, use_column_width=True)
    except:
        if LOTTIE:
            st_lottie(LOTTIE, height=220)
    st.write("")
    if client:
        st.success("Gemini configured")
    else:
        st.warning("Gemini not configured. Set GEMINI_API_KEY in env or st.secrets")

with col2:
    if ui_lang == "हिंदी":
        uploaded_file = st.file_uploader("बिल अपलोड करें (JPG/PNG)", type=["jpg","jpeg","png"])
        extra_context = st.text_input("अतिरिक्त संदर्भ (optional)", placeholder="जैसे: कई महीनों से गलत आ रहा है")
        officer = st.selectbox("पत्र किसे संबोधित किया जाए?", ["EXECUTIVE ENGINEER", "JUNIOR ENGINEER", "SDO", "SUPERINTENDENT ENGINEER"])
        mobile = st.text_input("मोबाइल नंबर दर्ज करें")
        app_date = st.date_input("आवेदन की तिथि चुनें", value=date.today())
    else:
        uploaded_file = st.file_uploader("Upload bill (JPG/PNG)", type=["jpg","jpeg","png"])
        extra_context = st.text_input("Extra context (optional)", placeholder="e.g. wrong for months")
        officer = st.selectbox("Address letter to", ["EXECUTIVE ENGINEER", "JUNIOR ENGINEER", "SDO", "SUPERINTENDENT ENGINEER"])
        mobile = st.text_input("Enter mobile number")
        app_date = st.date_input("Select application date", value=date.today())

if 'extracted' not in st.session_state:
    st.session_state.extracted = None
if 'calculation' not in st.session_state:
    st.session_state.calculation = None
if 'analysis_mistakes' not in st.session_state:
    st.session_state.analysis_mistakes = None
if 'letter_text' not in st.session_state:
    st.session_state.letter_text = None

if uploaded_file is not None:
    if st.button("📥 Extract & Analyze (Gemini)"):
        with st.spinner("Processing..."):
            extracted, err = call_gemini_extract(uploaded_file, extra_context)
            if extracted is None:
                st.error("Extraction failed: " + str(err))
            else:
                st.session_state.extracted = extracted
                st.success("Extraction successful")
                calc_res, calc_err = call_gemini_calculate_and_explain(extracted, extra_context)
                if calc_res is None:
                    st.error("Calculation by Gemini failed: " + str(calc_err))
                    st.session_state.calculation = None
                else:
                    st.session_state.calculation = calc_res
                    st.success("Calculation completed by Gemini")
                    mistakes = []
                    provided = None
                    try:
                        provided = float(extracted.get("Total_Amount_Payable_INR")) if extracted.get("Total_Amount_Payable_INR") not in (None, "", "N/A") else None
                    except:
                        provided = None
                    calc_total = None
                    try:
                        calc_total = float(calc_res.get("calculation", {}).get("total"))
                    except:
                        calc_total = None
                    if calc_total is not None and provided is not None:
                        diff = abs(calc_total - provided)
                        pct = (diff / provided * 100) if provided else 0
                        if pct > 3:
                            mistakes.append({"Mistake_Code":"CALC_ERR", "Description_Hindi": f"बिल गणना में अंतर: अपेक्षित ₹{calc_total} जबकि बिल में ₹{provided}. अंतर {round(pct,2)}%."})
                    if extracted.get("Sanctioned_Load_kW") in (None, "", "N/A"):
                        mistakes.append({"Mistake_Code":"MISSING_DATA", "Description_Hindi":"Sanctioned Load गायब है।"})
                    try:
                        sload = float(extracted.get("Sanctioned_Load_kW")) if extracted.get("Sanctioned_Load_kW") not in (None, "", "N/A") else None
                        units = float(extracted.get("Units_Consumed_kWh")) if extracted.get("Units_Consumed_kWh") not in (None, "", "N/A") else None
                        if sload and units:
                            if units / sload > 200:
                                mistakes.append({"Mistake_Code":"HIGH_USE", "Description_Hindi":f"प्रति kW {round(units/sload,1)} यूनिट — असामान्य खपत।"})
                    except:
                        pass
                    st.session_state.analysis_mistakes = mistakes

if st.session_state.extracted:
    st.markdown("---")
    if ui_lang == "हिंदी":
        st.subheader("निकाला गया डेटा")
    else:
        st.subheader("Extracted Data")
    # Hide raw JSON; show key summary
    ex = st.session_state.extracted
    summary_cols = {
        "Consumer ID": ex.get('Consumer_ID','N/A'),
        "Name": ex.get('Consumer_Name','N/A'),
        "Discom": ex.get('Discom_Name','N/A'),
        "Division": ex.get('Division','N/A'),
        "Tariff": ex.get('Tariff_Category','N/A'),
        "Sanctioned Load (kW)": ex.get('Sanctioned_Load_kW','N/A'),
        "Units Consumed (kWh)": ex.get('Units_Consumed_kWh','N/A'),
        "Bill Amount (₹)": ex.get('Total_Amount_Payable_INR','N/A')
    }
    st.table(summary_cols)

if st.session_state.calculation:
    st.markdown("---")
    if ui_lang == "हिंदी":
        st.subheader("स्लैब-वाइज गणना")
    else:
        st.subheader("Slab-wise Calculation")
    calc = st.session_state.calculation
    # Build table rows from calc['calculation']['energy_details']
    energy = calc.get('calculation', {}).get('energy_details', [])
    rows = []
    for e in energy:
        slab_name = e.get('slab') or e.get('range') or ''
        units = e.get('units') or e.get('units_billed') or e.get('units_billed', 0)
        rate = e.get('rate') or e.get('rate', 0)
        amount = e.get('amount') or e.get('amount', 0)
        rows.append({"Slab": slab_name, "Units": units, "Rate (₹/unit)": rate, "Amount (₹)": amount})
    # display table
    st.table(rows)
    # summary
    summ = calc.get('calculation', {})
    fixed = summ.get('fixed', 0)
    energy_total = summ.get('energy_total', 0)
    duty = summ.get('duty', 0)
    total = summ.get('total', 0)
    provided = None
    try:
        provided = float(st.session_state.extracted.get('Total_Amount_Payable_INR'))
    except:
        provided = None
    st.markdown("**Summary**")
    st.write(f"Fixed Charge: ₹{fixed}")
    st.write(f"Energy Total: ₹{energy_total}")
    st.write(f"Duty: ₹{duty}")
    st.write(f"Calculated Total: ₹{total}")
    if provided is not None:
        diff = round(abs(total - provided),2)
        st.write(f"Bill Total (from bill): ₹{provided}")
        st.write(f"Difference: ₹{diff}")
        if diff <=  (0.03 * provided):
            st.success("✅ बिल सही प्रतीत होता है।")
        else:
            st.error("⚠️ बिल में अंतर पाया गया — कृपया शिकायत पत्र बनाएं।")

if st.session_state.analysis_mistakes is not None:
    st.markdown("---")
    if ui_lang == "हिंदी":
        st.subheader("संभावित विसंगतियाँ")
    else:
        st.subheader("Potential Mistakes")
    if st.session_state.analysis_mistakes:
        for i, m in enumerate(st.session_state.analysis_mistakes):
            checked = st.checkbox(f"[{m.get('Mistake_Code')}] {m.get('Description_Hindi')}", value=True, key=f"mist_{i}")
        selected = [m for i,m in enumerate(st.session_state.analysis_mistakes) if st.session_state.get(f"mist_{i}", True)]
        st.session_state.selected_mistakes = selected
    else:
        if ui_lang == "हिंदी":
            st.success("🎉 आपका बिल सही प्रतीत होता है।")
        else:
            st.success("🎉 Your bill appears correct.")

if st.session_state.calculation and st.session_state.extracted:
    st.markdown("---")
    if ui_lang == "हिंदी":
        st.subheader("पत्र तैयार करें")
    else:
        st.subheader("Generate Application Letter")
    use_gemini_letter = st.checkbox("Gemini से पत्र परिष्कृत करें (यदि उपलब्ध)", value=True)
    if ui_lang == "हिंदी":
        extra_for_letter = st.text_area("पत्र के लिए अतिरिक्त संदर्भ (optional)", placeholder="उदाहरण: कई महीनों से गलत आ रहा है")
    else:
        extra_for_letter = st.text_area("Additional context for letter (optional)")
    if st.button("📝 पत्र बनाएं / Generate Letter"):
        with st.spinner("Generating letter..."):
            selected = st.session_state.get("selected_mistakes", [])
            if use_gemini_letter and client is not None:
                letter, err = call_gemini_letter(st.session_state.extracted, st.session_state.calculation, selected, extra_for_letter, officer, "Hindi" if ui_lang=="हिंदी" else "English", mobile, app_date.isoformat())
                if letter is None:
                    letter = generate_local_simple_letter(st.session_state.extracted, selected, officer, "Hindi" if ui_lang=="हिंदी" else "English", mobile, app_date.isoformat(), extra_for_letter)
                st.session_state.letter_text = letter
            else:
                letter = generate_local_simple_letter(st.session_state.extracted, selected, officer, "Hindi" if ui_lang=="हिंदी" else "English", mobile, app_date.isoformat(), extra_for_letter)
                st.session_state.letter_text = letter
        st.success("Letter ready")

if st.session_state.letter_text:
    st.markdown("---")
    if ui_lang == "हिंदी":
        st.subheader("जनरेटेड पत्र")
    else:
        st.subheader("Generated Letter")
    st.text_area("Letter / पत्र", st.session_state.letter_text, height=360)
    pdf_buf = create_pdf_buffer(st.session_state.letter_text)
    docx_buf = create_docx_buffer(st.session_state.letter_text)
    colp, cold, colc = st.columns([1,1,1])
    colp.download_button("PDF डाउनलोड / Download PDF", pdf_buf, file_name=f"Complaint_{st.session_state.extracted.get('Consumer_ID','N-A')}.pdf", mime="application/pdf")
    cold.download_button("DOCX डाउनलोड / Download DOCX", docx_buf, file_name=f"Complaint_{st.session_state.extracted.get('Consumer_ID','N-A')}.docx", mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    if colc.button("Start Over / फिर से शुरू करें"):
        for k in ['extracted','calculation','analysis_mistakes','selected_mistakes','letter_text']:
            if k in st.session_state:
                del st.session_state[k]
        st.experimental_rerun()

st.markdown("---")
if ui_lang == "हिंदी":
    st.markdown("**नोट:** Gemini API key आवश्यक है। Render पर `GEMINI_API_KEY` env में डालें। PDF के लिए `NotoSans-Regular.ttf` मौजूद होना चाहिए।")
else:
    st.markdown("**Note:** Gemini API key is required. Set `GEMINI_API_KEY` as env on Render. Keep `NotoSans-Regular.ttf` in project for PDF.")
