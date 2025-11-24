import streamlit as st
import os
import io
import json
import time
from google import genai
from PIL import Image
from docx import Document
from streamlit_lottie import st_lottie
import requests

# --- PDF Generation (Unicode Support) ---
# FIX: Using fpdf2 for better Hindi/Unicode support over reportlab
from fpdf import FPDF
# NOTE: For fpdf2 to support Hindi, you must include a TTF font file (e.g., 'NotoSans-Regular.ttf')
# in your project and reference it correctly. We assume 'NotoSans-Regular.ttf' is in the project root.

# --- कॉन्फ़िगरेशन और मॉडर्न UI सेटिंग्स ---
st.set_page_config(
    page_title="Electricity Bill Analyzer (बिजली बिल विश्लेषक)",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)

# API कुंजी सेटअप (FIX: Using os.environ for Render)
try:
    # 🔑 Render Environment Variables से सीधे कुंजी एक्सेस करें
    GEMINI_API_KEY = os.environ["GEMINI_API_KEY"] 
except KeyError:
    # Local या Streamlit Secrets का fallback
    try:
        GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
    except Exception:
        st.error("Error: GEMINI_API_KEY environment variable not found. Please set it in Render or Streamlit Secrets.")
        st.stop()
    
# क्लाइंट इनिशियलाइज़ेशन
client = genai.Client(api_key=GEMINI_API_KEY)

# Lottie एनीमेशन लोडर (FIX: Using URL loading for simpler setup)
@st.cache_data
def load_lottieurl(url: str):
    """URL से Lottie JSON डेटा लोड करता है।"""
    r = requests.get(url)
    if r.status_code != 200:
        return None
    return r.json()

# Lottie URLs for analysis and success
LOTTIE_ANALYSIS_URL = "https://lottie.host/75231c50-8916-43b8-89c5-34440807f4ac/2q36b7G1gT.json" # Checking/Loading animation
LOTTIE_ANALYSIS = load_lottieurl(LOTTIE_ANALYSIS_URL)

# --- फ़ंक्शन्स ---

@st.cache_data(show_spinner=False)
def extract_bill_data(image_file, prompt_text):
    """Gemini Vision API का उपयोग करके बिल से डेटा एक्सट्रैक्ट करता है।"""
    image = Image.open(image_file)
    
    # एक्सट्रैक्शन के लिए विस्तृत प्रॉम्प्ट
    full_prompt = (
        "आप एक विशेषज्ञ डेटा एक्सट्रैक्टर हैं। इस बिजली बिल से निम्नलिखित जानकारी निकालें और इसे केवल एक JSON स्ट्रिंग के रूप में आउटपुट करें: "
        "1. Consumer_ID (string), 2. Consumer_Name (string), 3. Sanctioned_Load_kW (number), 4. Units_Consumed_kWh (number), "
        "5. Billing_Date (string, format YYYY-MM-DD), 6. Total_Amount_Payable_INR (number), 7. Discom_Name (string). "
        "यदि कोई मान नहीं मिलता है, तो उसे 'N/A' सेट करें। JSON के बाहर कोई अतिरिक्त टेक्स्ट न डालें। "
        "यहां अतिरिक्त संदर्भ है: " + prompt_text
    )
    
    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=[full_prompt, image]
        )
        
        # आउटपुट को क्लीन करें (केवल JSON स्ट्रिंग रखें)
        json_str = response.text.strip()
        
        # प्रॉम्प्ट इंजीनियरिंग सुरक्षा: कभी-कभी Gemini अतिरिक्त टेक्स्ट जोड़ता है
        if json_str.startswith("```json"):
            json_str = json_str.strip("```json").strip("```").strip()
            
        return json.loads(json_str)
    except Exception as e:
        st.error(f"Gemini API Error or JSON Parsing Error during extraction: {e}")
        return None

@st.cache_data(show_spinner=False)
def analyze_bill(bill_data):
    """Gemini Pro का उपयोग करके बिल की विसंगतियों (discrepancies) का पता लगाता है।"""
    
    # यह एक डमी टैरिफ डेटाबेस है - वास्तविक दरें डालें
    DUMMY_TARIFF = {
        "fixed_charge_per_kW": 120,
        "energy_rate_slab1_upto_100_kWh": 5.50,
        "energy_rate_slab2_above_100_kWh": 7.00,
        "duty_percentage": 0.05
    }
    
    analysis_prompt = f"""
    एक बिजली बिल विश्लेषण विशेषज्ञ के रूप में कार्य करें। बिल का डेटा नीचे दिया गया है:
    {json.dumps(bill_data, indent=2)}

    क्षेत्र के लिए मान्य अनुमानित टैरिफ दरें:
    Fixed Charge: ₹{DUMMY_TARIFF['fixed_charge_per_kW']} प्रति kW
    Energy Rate (0-100 kWh): ₹{DUMMY_TARIFF['energy_rate_slab1_upto_100_kWh']}
    Energy Rate (Above 100 kWh): ₹{DUMMY_TARIFF['energy_rate_slab2_above_100_kWh']}
    Duty: {DUMMY_TARIFF['duty_percentage']*100}%

    निम्नलिखित संभावित त्रुटियों या विसंगतियों (discrepancies) की पहचान करें:
    1. **Calculation Error:** ऊपर दी गई दरों के आधार पर कुल बिल राशि की पुनर्गणना (re-calculate) करें और इसकी तुलना 'Total_Amount_Payable_INR' से करें। यदि 3% से अधिक अंतर है, तो इसे गलती मानें।
    2. **High Energy Use (असामान्य खपत):** यदि 'Units_Consumed_kWh' (यूनिट खपत) 'Sanctioned_Load_kW' (सैंक्शनड लोड) के प्रति kW 200 यूनिट से अधिक है, तो इसे असामान्य रूप से उच्च खपत के रूप में चिह्नित करें।
    3. **Missing Data:** बिल में कोई महत्वपूर्ण डेटा (जैसे Sanctioned Load) गायब है।

    अपने निष्कर्षों को एक JSON सूची के रूप में आउटपुट करें, जहां प्रत्येक आइटम में 'Mistake_Code' (जैसे CALC_ERR, HIGH_USE, MISSING_DATA) और 'Description_Hindi' हो। यदि कोई गलती नहीं मिलती है, तो एक खाली सूची आउटपुट करें। केवल JSON सूची ही आउटपुट करें।
    """
    
    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=[analysis_prompt]
        )
        json_str = response.text.strip()
        
        if json_str.startswith("```json"):
            json_str = json_str.strip("```json").strip("```").strip()
            
        return json.loads(json_str)
    except Exception as e:
        return [{"Mistake_Code": "API_FAIL", "Description_Hindi": f"विश्लेषण के दौरान एक तकनीकी त्रुटि हुई: {e}"}]

def generate_application(bill_data, selected_mistakes, extra_context, language):
    """Gemini Pro का उपयोग करके शिकायत पत्र जनरेट करता है।"""
    
    mistake_descriptions = "\n- " + "\n- ".join([m['Description_Hindi'] for m in selected_mistakes])
    
    app_prompt = f"""
    आप एक पेशेवर और औपचारिक पत्र लेखक हैं। कृपया निम्नलिखित डिटेल्स के आधार पर संबंधित बिजली विभाग के अधिकारी को एक शिकायत/अनुरोध पत्र तैयार करें।
    
    **उपभोक्ता विवरण:**
    नाम: {bill_data.get('Consumer_Name', 'N/A')}
    उपभोक्ता ID: {bill_data.get('Consumer_ID', 'N/A')}
    डिस्कोम: {bill_data.get('Discom_Name', 'N/A')}
    बिल राशि: {bill_data.get('Total_Amount_Payable_INR', 'N/A')}
    
    **शिकायत के मुख्य बिंदु:**
    {mistake_descriptions}
    
    **अतिरिक्त संदर्भ (Additional Context):**
    "{extra_context}"
    
    **पत्र की भाषा:** "{'हिंदी' if language == 'Hindi' else 'English'}" होनी चाहिए।
    
    पत्र विनम्र, औपचारिक और कार्रवाई की मांग करने वाला होना चाहिए।
    """
    
    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=[app_prompt]
        )
        return response.text
    except Exception as e:
        return f"Gemini API Error: पत्र जनरेट नहीं हो सका। त्रुटि: {e}"

# --- PDF और DOCX जनरेशन फंक्शन्स ---
def create_pdf(text_content):
    """टेक्स्ट से PDF बनाता है (fpdf2 के साथ यूनिकोड सपोर्ट)"""
    pdf = FPDF()
    try:
        # हिंदी सपोर्ट के लिए फ़ॉन्ट जोड़ें (यह फ़ाइल आपके रेपो में होनी चाहिए)
        pdf.add_font("NotoSans", style="", fname="NotoSans-Regular.ttf", uni=True)
        pdf.set_font("NotoSans", size=10)
    except RuntimeError:
        # यदि फ़ॉन्ट फ़ाइल नहीं मिलती है, तो एक डिफ़ॉल्ट फ़ॉन्ट का उपयोग करें
        pdf.set_font("Arial", size=10)
        
    pdf.add_page()
    pdf.multi_cell(0, 5, text_content)
    
    buffer = io.BytesIO(pdf.output(dest='S').encode('latin-1')) # 'S' returns as bytes
    buffer.seek(0)
    return buffer

def create_docx(text_content):
    """टेक्स्ट से DOCX बनाता है (python-docx)"""
    document = Document()
    document.add_paragraph(text_content)
    buffer = io.BytesIO()
    document.save(buffer)
    buffer.seek(0)
    return buffer

# --- स्ट्रीमलिट UI ---

# Custom CSS for Modern UI
st.markdown("""
<style>
    /* Main container styling */
    .stApp {
        background-color: #f0f2f6; 
        color: #1f2937;
    }
    /* Header/Title styling */
    h1 {
        color: #0b7a74; 
        text-align: center;
        margin-bottom: 0.5em;
        font-weight: 700;
    }
    /* Section Headers */
    h2, h3 {
        color: #1f2937;
        border-bottom: 2px solid #e5e7eb;
        padding-bottom: 5px;
        margin-top: 1.5em;
    }
    /* Primary buttons */
    div.stButton > button:first-child {
        background-color: #0b7a74;
        color: white;
        border-radius: 12px;
        border: none;
        padding: 10px 24px;
        font-size: 16px;
        transition: background-color 0.3s;
    }
    div.stButton > button:first-child:hover {
        background-color: #0d9488;
    }
    /* File Uploader styling */
    .stFileUploader {
        border: 2px dashed #0b7a74;
        border-radius: 10px;
        padding: 20px;
    }
    /* Main Content Area Padding */
    .block-container {
        padding-top: 2rem;
        padding-bottom: 2rem;
    }
</style>
""", unsafe_allow_html=True)

# --- 🎯 मुख्य UI लेआउट ---
st.title("⚡️ Electricity Bill Analyzer & Application Generator")
st.markdown("### बिजली बिल का विश्लेषण करें और शिकायत/अनुरोध पत्र जनरेट करें।")

col1, col2 = st.columns([1, 2])

with col1:
    if LOTTIE_ANALYSIS:
        st_lottie(
            LOTTIE_ANALYSIS,
            height=200,
            key="analysis_animation",
        )
    else:
        st.header("Upload")
    
    st.info("💡 **पहला चरण:** अपना बिजली बिल (PNG/JPG) अपलोड करें।")

with col2:
    uploaded_file = st.file_uploader(
        "**बिल अपलोड करें (JPG या PNG)**", 
        type=["jpg", "png"],
        help="उच्च रिज़ॉल्यूशन (high resolution) वाला बिल बेहतर परिणाम देगा।"
    )
    
    extra_ocr_context = st.text_input(
        "बिल OCR अतिरिक्त जानकारी",
        placeholder="जैसे: मेरा डिस्कॉम UPPCL है, यह वाणिज्यिक (Commercial) बिल है।"
    )

# Session state initialization
if 'bill_data' not in st.session_state:
    st.session_state.bill_data = None
if 'mistakes' not in st.session_state:
    st.session_state.mistakes = None

# --- 1. OCR एक्सट्रैक्शन ---
if uploaded_file is not None:
    # यदि नई फ़ाइल अपलोड की गई है, तो सत्र स्थिति रीसेट करें
    if st.session_state.bill_data is None or st.session_state.uploaded_filename != uploaded_file.name:
        st.session_state.uploaded_filename = uploaded_file.name
        
        with st.spinner("⏳ बिल से डेटा निकाला जा रहा है... (Gemini Vision)"):
            bill_data = extract_bill_data(uploaded_file, extra_ocr_context)
            st.session_state.bill_data = bill_data
            st.session_state.mistakes = None # विश्लेषण को रीसेट करें

    if st.session_state.bill_data and st.session_state.bill_data.get('Consumer_ID'):
        st.success("✅ डेटा सफलतापूर्वक निकाला गया!")
        st.markdown("### 🔍 निकाले गए बिल की डिटेल्स")
        st.json(st.session_state.bill_data)
    elif st.session_state.bill_data is not None:
        st.warning("⚠️ डेटा नहीं निकाला जा सका। कृपया स्पष्ट तस्वीर अपलोड करें।")

# --- 2. बिल एनालिसिस ---
if st.session_state.bill_data:
    st.markdown("---")
    st.markdown("### ⚙️ चरण 2: बिल विसंगति (Error) विश्लेषण")
    
    if st.button("🚀 बिल का विश्लेषण करें"):
        with st.spinner("🧠 विसंगतियों की जाँच की जा रही है... (Gemini Pro)"):
            mistakes = analyze_bill(st.session_state.bill_data)
            st.session_state.mistakes = mistakes

# --- 3. एप्लीकेशन जनरेशन ---
if st.session_state.mistakes is not None:
    st.markdown("---")
    st.markdown("### ✍️ चरण 3: शिकायत पत्र जनरेट करें")
    
    if st.session_state.mistakes:
        st.warning("🚨 निम्नलिखित संभावित विसंगतियाँ पाई गई हैं:")
        
        selected_mistakes = []
        
        # यूज़र को चुनने की अनुमति
        for i, mistake in enumerate(st.session_state.mistakes):
            key = f"mistake_{i}"
            checked = st.checkbox(
                f"**[{mistake.get('Mistake_Code', 'N/A')}]** {mistake.get('Description_Hindi', 'विवरण उपलब्ध नहीं')}",
                key=key,
                value=True # डिफ़ॉल्ट रूप से सभी चुनें
            )
            if checked:
                selected_mistakes.append(mistake)
        
        st.session_state.selected_mistakes = selected_mistakes
        
        if selected_mistakes:
            col_lang, _ = st.columns([1, 3])
            
            with col_lang:
                app_language = st.selectbox(
                    "पत्र की भाषा चुनें", 
                    ['Hindi', 'English'],
                    key='app_lang'
                )
            
            app_extra_context = st.text_area(
                "📝 पत्र के लिए अतिरिक्त संदर्भ (Add Extra Context)",
                placeholder="जैसे: मुझे इस बिल के कारण नोटिस मिला है और मीटर खराब हो सकता है।"
            )
            
            if st.button("📝 शिकायत पत्र जनरेट करें", key="generate_app_btn"):
                with st.spinner("⏳ पत्र तैयार किया जा रहा है... (Gemini Pro)"):
                    application_text = generate_application(
                        st.session_state.bill_data,
                        st.session_state.selected_mistakes,
                        app_extra_context,
                        app_language
                    )
                    st.session_state.application_text = application_text
        else:
            st.info("सभी विसंगतियों को अनचेक किया गया है। जनरेट करने के लिए कम से कम एक विसंगति चुनें।")
            
    else:
        st.success("🎉 आपके बिल में कोई बड़ी विसंगति नहीं पाई गई।")

# --- 4. आउटपुट डिस्प्ले और सेविंग ---
if 'application_text' in st.session_state and st.session_state.application_text:
    st.markdown("---")
    st.markdown("### 📄 जनरेटेड एप्लीकेशन/पत्र")
    
    st.text_area(
        "पत्र का ड्राफ्ट (Copy Text)",
        st.session_state.application_text,
        height=400
    )
    
    col_pdf, col_docx, _ = st.columns([1, 1, 2])
    
    # PDF सेव करें
    pdf_file = create_pdf(st.session_state.application_text)
    col_pdf.download_button(
        label="📥 PDF में सेव करें",
        data=pdf_file,
        file_name=f"Complaint_Letter_{st.session_state.bill_data.get('Consumer_ID', 'N-A')}.pdf",
        mime="application/pdf"
    )

    # DOCX सेव करें
    docx_file = create_docx(st.session_state.application_text)
    col_docx.download_button(
        label="📄 Word (DOCX) में सेव करें",
        data=docx_file,
        file_name=f"Complaint_Letter_{st.session_state.bill_data.get('Consumer_ID', 'N-A')}.docx",
        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
