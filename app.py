import os
os.environ["STREAMLIT_SERVER_HEADLESS"] = "true"
import streamlit as st
import io
import json
import re
from PIL import Image
from docx import Document
from streamlit_lottie import st_lottie
import requests
from fpdf import FPDF
from google import genai

st.set_page_config(
    page_title="Electricity Bill Analyzer (बिजली बिल विश्लेषक)",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)

def get_client():
    key = None
    if "GEMINI_API_KEY" in os.environ:
        key = os.environ["GEMINI_API_KEY"]
    else:
        try:
            key = st.secrets["GEMINI_API_KEY"]
        except:
            pass
    if not key:
        return None
    try:
        return genai.Client(api_key=key)
    except:
        return None

client = get_client()

@st.cache_data
def lottie(url):
    try:
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            return r.json()
    except:
        pass
    return None

LOTTIE = lottie("https://assets10.lottiefiles.com/packages/lf20_jtbfg2nb.json")

def clean_json(text):
    if not text:
        return None
    s = text.strip()
    s = re.sub(r"^```json", "", s, flags=re.IGNORECASE).strip()
    s = re.sub(r"^```", "", s).strip()
    s = re.sub(r"```$", "", s).strip()
    try:
        return json.loads(s)
    except:
        pass
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

def extract_with_gemini(image_file, context=""):
    if client is None:
        return None, "Gemini Key Missing"
    try:
        img = Image.open(image_file)
        prompt = (
            "Extract the following from this electricity bill and output only pure JSON with no extra text. "
            "Fields: Consumer_ID, Consumer_Name, Sanctioned_Load_kW, Units_Consumed_kWh, Billing_Date, "
            "Total_Amount_Payable_INR, Discom_Name. "
            "If any value missing, set 'N/A'. Context: " + context
        )
        try:
            resp = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=[prompt, img]
            )
            txt = getattr(resp, "text", None) or str(resp)
        except:
            return None, "Gemini Vision Error"
        data = clean_json(txt)
        if data is None:
            return None, "JSON Parse Failed"
        return data, None
    except Exception as e:
        return None, str(e)

def validate_data(b):
    issues = []
    c = {}
    c['Consumer_ID'] = b.get('Consumer_ID') or "N/A"
    c['Consumer_Name'] = b.get('Consumer_Name') or "N/A"
    def num(v, key):
        if v in (None, "", "N/A"):
            issues.append(f"{key} Missing")
            return None
        try:
            return float(str(v).replace(",", ""))
        except:
            issues.append(f"{key} Invalid")
            return None
    c['Sanctioned_Load_kW'] = num(b.get('Sanctioned_Load_kW'), "Sanctioned_Load_kW")
    c['Units_Consumed_kWh'] = num(b.get('Units_Consumed_kWh'), "Units_Consumed_kWh")
    c['Total_Amount_Payable_INR'] = num(b.get('Total_Amount_Payable_INR'), "Total_Amount_Payable_INR")
    c['Billing_Date'] = b.get('Billing_Date') or "N/A"
    c['Discom_Name'] = b.get('Discom_Name') or "N/A"
    return c, issues

TARIFF = {
    "fc": 120,
    "slab1": 5.50,
    "slab2": 7.00,
    "duty": 0.05
}

def recalc(b):
    fixed = 0
    energy = 0
    if b['Sanctioned_Load_kW']:
        fixed = TARIFF['fc'] * b['Sanctioned_Load_kW']
    if b['Units_Consumed_kWh'] != None:
        u = b['Units_Consumed_kWh']
        if u <= 100:
            energy = u * TARIFF['slab1']
        else:
            energy = 100 * TARIFF['slab1'] + (u - 100) * TARIFF['slab2']
    duty = (fixed + energy) * TARIFF['duty']
    total = round(fixed + energy + duty, 2)
    return {"fixed": fixed, "energy": energy, "duty": duty, "total": total}

def analyze(b):
    m = []
    r = recalc(b)
    if b['Sanctioned_Load_kW'] is None:
        m.append({"Mistake_Code":"MISSING_DATA","Description_Hindi":"Sanctioned Load गायब है।"})
    if b['Total_Amount_Payable_INR'] != None:
        try:
            diff = abs(r['total'] - b['Total_Amount_Payable_INR']) / b['Total_Amount_Payable_INR'] * 100
            if diff > 3:
                m.append({"Mistake_Code":"CALC_ERR","Description_Hindi":f"बिल गणना में अंतर: अपेक्षित ₹{r['total']} जबकि बिल में ₹{b['Total_Amount_Payable_INR']}."})
        except:
            pass
    if b['Sanctioned_Load_kW'] and b['Units_Consumed_kWh'] != None:
        try:
            per_kw = b['Units_Consumed_kWh'] / b['Sanctioned_Load_kW']
            if per_kw > 200:
                m.append({"Mistake_Code":"HIGH_USE","Description_Hindi":f"असामान्य खपत: प्रति kW {round(per_kw,1)} यूनिट।"})
        except:
            pass
    return m, r

def letter(b, m, extra, lang):
    pts = "\n".join(["- "+x['Description_Hindi'] for x in m])
    if lang == "Hindi":
        return f"""
सेवा में,
{b['Discom_Name']}

विषय: बिजली बिल में विसंगति हेतु शिकायत — उपभोक्ता ID {b['Consumer_ID']}

मान्यवर,

मैं {b['Consumer_Name']} (उपभोक्ता ID: {b['Consumer_ID']}) यह सूचित करना चाहता/चाहती हूँ कि मेरे बिजली बिल में निम्नलिखित विसंगतियाँ पाई गईं:
{pts}

कृपया जाँच कर आवश्यक सुधार करें। अतिरिक्त संदर्भ: {extra}

धन्यवाद
{b['Consumer_Name']}
"""
    else:
        return f"""
To
{b['Discom_Name']}

Subject: Complaint regarding discrepancy in bill — Consumer ID {b['Consumer_ID']}

Respected Sir/Madam,

I, {b['Consumer_Name']} (Consumer ID: {b['Consumer_ID']}), found the following discrepancies:
{pts}

Kindly investigate and correct. Additional context: {extra}

Thank you
{b['Consumer_Name']}
"""

def pdf(text):
    pdf = FPDF()
    try:
        pdf.add_font("NotoSans", "", "NotoSans-Regular.ttf", uni=True)
        pdf.set_font("NotoSans", size=11)
    except:
        pdf.set_font("Arial", size=11)
    pdf.add_page()
    for line in text.split("\n"):
        pdf.multi_cell(0, 6, line)
    buf = io.BytesIO(pdf.output(dest='S').encode('latin-1', errors='replace'))
    buf.seek(0)
    return buf

def docx(text):
    d = Document()
    for line in text.split("\n"):
        d.add_paragraph(line)
    buf = io.BytesIO()
    d.save(buf)
    buf.seek(0)
    return buf

st.markdown("""
<style>
.stApp { background:#f7fafc; color:#0f172a; }
h1 { color:#0b7a74; font-weight:700; }
.stButton>button { background:#0b7a74; color:white; border-radius:10px; padding:8px 18px; }
.card { background:white; padding:1rem; margin-top:1rem; border-radius:12px; box-shadow:0 6px 20px rgba(16,24,40,0.06); }
</style>
""", unsafe_allow_html=True)

st.title("⚡ Electricity Bill Analyzer & Complaint Letter Generator")

c1, c2 = st.columns([1,2])
with c1:
    if LOTTIE:
        st_lottie(LOTTIE, height=200)
    st.info("बिल स्पष्ट और हाई रेज़ोल्यूशन हो।")
with c2:
    f = st.file_uploader("बिल अपलोड करें (JPG/PNG)", type=["jpg","jpeg","png"])
    context = st.text_input("अतिरिक्त संदर्भ (optional)")

if 'data' not in st.session_state:
    st.session_state.data = None

if f:
    if st.button("डेटा निकालें (Gemini Vision)"):
        with st.spinner("डेटा निकाला जा रहा है…"):
            d, err = extract_with_gemini(f, context)
            if d:
                st.session_state.data = d
                st.success("डेटा सफलतापूर्वक निकला।")
            else:
                st.error("एक्सट्रैक्शन असफल: "+str(err))

if st.session_state.data:
    st.json(st.session_state.data)

if st.session_state.data:
    if st.button("बिल विश्लेषण करें"):
        with st.spinner("विश्लेषण हो रहा है…"):
            clean, iss = validate_data(st.session_state.data)
            mis, rec = analyze(clean)
            st.session_state.clean = clean
            st.session_state.mis = mis
            st.session_state.rec = rec
            st.session_state.iss = iss
            st.success("विश्लेषण पूरा।")

if 'mis' in st.session_state:
    st.subheader("पुनर्गणना")
    st.write(st.session_state.rec)
    if st.session_state.iss:
        st.warning(st.session_state.iss)
    if st.session_state.mis:
        st.warning("संभावित विसंगतियाँ पाई गईं:")
        sel = []
        for i, m in enumerate(st.session_state.mis):
            if st.checkbox(m['Description_Hindi'], value=True, key=f"m{i}"):
                sel.append(m)
        st.session_state.sel = sel
    else:
        st.success("कोई बड़ी त्रुटि नहीं पाई गई।")

if 'sel' in st.session_state and st.session_state.sel:
    st.subheader("शिकायत पत्र बनाएं")
    lang = st.selectbox("भाषा चुनें", ["Hindi","English"])
    more = st.text_area("अतिरिक्त संदर्भ जोड़ें")
    if st.button("पत्र तैयार करें"):
        t = letter(st.session_state.clean, st.session_state.sel, more, lang)
        st.session_state.letter = t
        st.success("पत्र तैयार।")

if 'letter' in st.session_state:
    st.text_area("पत्र", st.session_state.letter, height=350)
    p = pdf(st.session_state.letter)
    w = docx(st.session_state.letter)
    st.download_button("PDF डाउनलोड", p, "letter.pdf")
    st.download_button("DOCX डाउनलोड", w, "letter.docx")
