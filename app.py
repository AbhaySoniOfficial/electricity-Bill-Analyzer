import streamlit as st
import os
import io
from google import genai
from google.genai import types
from PIL import Image
from reportlab.pdfgen import canvas
from docx import Document
from streamlit_lottie import st_lottie
import json
import time

# --- कॉन्फ़िगरेशन और मॉडर्न UI सेटिंग्स ---
st.set_page_config(
    page_title="Electricity Bill Analyzer (बिजली बिल विश्लेषक)",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)

# API कुंजी सेटअप
# इसे Streamlit Secrets या Render Environment Variables से लोड करें
try:
    # 🔑 GEMINI_API_KEY को st.secrets या os.environ में सेट करें
    GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
except KeyError:
    GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
    if not GEMINI_API_KEY:
        st.error("Error: GEMINI_API_KEY environment variable not found. Please set it up.")
        st.stop()

# क्लाइंट इनिशियलाइज़ेशन
client = genai.Client(api_key=GEMINI_API_KEY)

# Lottie एनीमेशन लोडर (मॉडर्न UI के लिए)
def load_lottiefile(filepath: str):
    """Lottie JSON फ़ाइल को लोड करता है"""
    # आप इसे स्थानीय रूप से (local file) या URL से लोड कर सकते हैं
    # यहाँ हम एक डमी संरचना का उपयोग कर रहे हैं। आपको JSON डेटा डालना होगा।
    # उदाहरण के लिए, एक चेकिंग या रॉकेट एनीमेशन।
    # For this example, let's use a placeholder structure
    # Replace this with actual Lottie JSON data if available
    return {
        "v": "5.5.2",
        "fr": 60,
        "ip": 0,
        "op": 60,
        "w": 100,
        "h": 100,
        "assets": [],
        "layers": [
            {
                "op": 60,
                "ip": 0,
                "ty": 4,
                "nm": "Dummy Layer",
                "ks": {
                    "o": {
                        "a": 0,
                        "k": [
                            {"i": {"x": 0.833, "y": 0.833}, "o": {"x": 0.167, "y": 0.167}, "t": 0, "s": [100]},
                            {"i": {"x": 0.833, "y": 0.833}, "o": {"x": 0.167, "y": 0.167}, "t": 30, "s": [0]},
                            {"i": {"x": 0.833, "y": 0.833}, "o": {"x": 0.167, "y": 0.167}, "t": 60, "s": [100]}
                        ]
                    },
                    "p": {"a": 0, "k": [50, 50]},
                    "s": {"a": 0, "k": [100, 100]},
                    "r": {"a": 0, "k": [0]}
                },
                "shapes": [
                    {
                        "ty": "gr",
                        "it": [
                            {"d": 1, "ty": "el", "p": {"a": 0, "k": [0, 0]}, "s": {"a": 0, "k": [100, 100]}},
                            {"ty": "fl", "c": {"a": 0, "k": [1, 0, 0, 1]}},
                            {"ty": "tr"}
                        ]
                    }
                ]
            }
        ]
    }

lottie_analysis = load_lottiefile("path/to/analysis.json") # Replace with actual path or URL

# --- फ़ंक्शन्स ---

@st.cache_data(show_spinner=False)
def extract_bill_data(image_file, prompt_text):
    """Gemini Vision API का उपयोग करके बिल से डेटा एक्सट्रैक्ट करता है।"""
    image = Image.open(image_file)
    
    # एक्सट्रैक्शन के लिए विस्तृत प्रॉम्प्ट
    full_prompt = (
        "आप एक विशेषज्ञ डेटा एक्सट्रैक्टर हैं। इस बिजली बिल से निम्नलिखित जानकारी निकालें और इसे केवल एक JSON स्ट्रिंग के रूप में आउटपुट करें: "
        "1. Consumer_ID, 2. Consumer_Name, 3. Sanctioned_Load_kW, 4. Units_Consumed_kWh, 5. Billing_Date, "
        "6. Total_Amount_Payable_INR, 7. Discom_Name. "
        "प्रत्येक कुंजी (key) के लिए उचित डेटाटाइप का उपयोग करें (नंबर के लिए नंबर)। यदि कोई मान नहीं मिलता है, तो उसे 'N/A' सेट करें। "
        "यहां अतिरिक्त संदर्भ है: " + prompt_text
    )
    
    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=[full_prompt, image]
        )
        
        # आउटपुट को क्लीन करें (केवल JSON स्ट्रिंग रखें)
        json_str = response.text.strip()
        if json_str.startswith("```json"):
            json_str = json_str.strip("```json").strip("```").strip()
        
        return json.loads(json_str)
    except Exception as e:
        st.error(f"Gemini API Error during extraction: {e}")
        return None

def analyze_bill(bill_data):
    """Gemini Pro का उपयोग करके बिल की विसंगतियों (discrepancies) का पता लगाता है।"""
    
    # यह एक डमी टैरिफ डेटाबेस है (आपको इसे अपने Discom/Division के अनुसार अपडेट करना होगा)
    DUMMY_TARIFF = {
        "fixed_charge_per_kW": 150,
        "energy_rate_slab1_upto_150_kWh": 6.00,
        "energy_rate_slab2_above_150_kWh": 7.50,
        "duty_percentage": 0.05
    }
    
    # Analysis Prompt: डेटा और टैरिफ रेट्स को पास करें
    analysis_prompt = f"""
    एक बिजली बिल विश्लेषण विशेषज्ञ के रूप में कार्य करें। बिल का डेटा नीचे दिया गया है:
    {json.dumps(bill_data, indent=2)}

    क्षेत्र के लिए मान्य (valid) टैरिफ दरें (केवल उदाहरण के लिए):
    Fixed Charge: ₹{DUMMY_TARIFF['fixed_charge_per_kW']} प्रति kW
    Energy Rate (0-150 kWh): ₹{DUMMY_TARIFF['energy_rate_slab1_upto_150_kWh']}
    Energy Rate (Above 150 kWh): ₹{DUMMY_TARIFF['energy_rate_slab2_above_150_kWh']}
    Duty: {DUMMY_TARIFF['duty_percentage']*100}%

    निम्नलिखित संभावित त्रुटियों या विसंगतियों (discrepancies) की पहचान करें:
    1. **Calculation Error:** ऊपर दी गई दरों के आधार पर कुल बिल राशि की पुनर्गणना (re-calculate) करें और इसकी तुलना 'Total_Amount_Payable_INR' से करें। यदि 5% से अधिक अंतर है, तो इसे गलती मानें।
    2. **High Energy Use:** यदि 'Units_Consumed_kWh' (यूनिट खपत) 'Sanctioned_Load_kW' (सैंक्शनड लोड) के प्रति kW 250 यूनिट से अधिक है, तो इसे असामान्य रूप से उच्च खपत (High Consumption) के रूप में चिह्नित करें।
    3. **Missing Data:** बिल में कोई महत्वपूर्ण डेटा (जैसे सैंक्शनड लोड) गायब है।

    अपने निष्कर्षों को एक JSON सूची के रूप में आउटपुट करें, जहां प्रत्येक आइटम में 'Mistake_Code' (जैसे CALC_ERR, HIGH_USE, MISSING_DATA) और 'Description_Hindi' हो। यदि कोई गलती नहीं मिलती है, तो एक खाली सूची आउटपुट करें।
    """
    
    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=[analysis_prompt]
        )
        
        # आउटपुट को JSON सूची में पार्स करें
        json_str = response.text.strip()
        if json_str.startswith("```json"):
            json_str = json_str.strip("```json").strip("```").strip()
            
        return json.loads(json_str)
    except Exception as e:
        st.error(f"Gemini API Error during analysis: {e}")
        return [{"Mistake_Code": "API_FAIL", "Description_Hindi": "विश्लेषण के दौरान एक तकनीकी त्रुटि हुई।"}]

def generate_application(bill_data, selected_mistakes, extra_context, language):
    """Gemini Pro का उपयोग करके शिकायत पत्र जनरेट करता है।"""
    
    mistake_descriptions = "\n- " + "\n- ".join([m['Description_Hindi'] for m in selected_mistakes])
    
    app_prompt = f"""
    आप एक पेशेवर और औपचारिक पत्र लेखक हैं। कृपया निम्नलिखित डिटेल्स के आधार पर संबंधित बिजली विभाग के अधिकारी को एक शिकायत/अनुरोध पत्र तैयार करें।
    
    **उपभोक्ता विवरण:**
    नाम: {bill_data.get('Consumer_Name', 'N/A')}
    उपभोक्ता ID: {bill_data.get('Consumer_ID', 'N/A')}
    डिस्कोम: {bill_data.get('Discom_Name', 'N/A')}
    
    **शिकायत के मुख्य बिंदु:**
    {mistake_descriptions}
    
    **अतिरिक्त संदर्भ (Additional Context):**
    "{extra_context}"
    
    **पत्र की भाषा:** "{'हिंदी' if language == 'Hindi' else 'English'}" होनी चाहिए।
    
    पत्र विनम्र, औपचारिक और कार्रवाई की मांग करने वाला होना चाहिए। केवल पत्र का मुख्य भाग (Body of the letter) आउटपुट करें, अभिवादन (Salutation) और समापन (Closing) सहित।
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
    """टेक्स्ट से PDF बनाता है (ReportLab)"""
    buffer = io.BytesIO()
    p = canvas.Canvas(buffer)
    # ReportLab हिंदी फोंट को सीधे सपोर्ट नहीं करता, इसलिए यह केवल डमी टेक्स्ट के लिए है
    p.drawString(100, 750, "Generated Application:")
    text_lines = text_content.split('\n')
    y_position = 730
    for line in text_lines:
        p.drawString(100, y_position, line)
        y_position -= 15
        if y_position < 50:
            p.showPage()
            y_position = 780
    
    p.save()
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
        background-color: #f0f2f6; /* Light gray background */
        color: #1f2937; /* Dark text */
    }
    /* Header/Title styling */
    h1 {
        color: #0b7a74; /* Primary Teal Color */
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
    /* Success/Error/Info boxes */
    div[data-testid="stAlert"] {
        border-left: 6px solid #0b7a74 !important;
        border-radius: 8px;
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
    st_lottie(
        lottie_analysis,
        height=200,
        key="analysis_animation",
    )
    
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

# --- 1. OCR एक्सट्रैक्शन ---
bill_data = {}
if uploaded_file is not None:
    # फाइल को Image.open() के लिए in-memory buffer में पास करें
    with st.spinner("⏳ बिल से डेटा निकाला जा रहा है... (Gemini Vision)"):
        bill_data = extract_bill_data(uploaded_file, extra_ocr_context)

    if bill_data and bill_data.get('Consumer_ID'):
        st.success("✅ डेटा सफलतापूर्वक निकाला गया!")
        st.markdown("### 🔍 निकाले गए बिल की डिटेल्स")
        st.json(bill_data)
        st.session_state.bill_data = bill_data
    elif bill_data is not None:
        st.warning("⚠️ डेटा नहीं निकाला जा सका। कृपया स्पष्ट तस्वीर अपलोड करें।")

# --- 2. बिल एनालिसिस ---
if 'bill_data' in st.session_state and st.session_state.bill_data:
    st.markdown("---")
    st.markdown("### ⚙️ चरण 2: बिल विसंगति (Error) विश्लेषण")
    
    if st.button("🚀 बिल का विश्लेषण करें"):
        with st.spinner("🧠 विसंगतियों की जाँच की जा रही है... (Gemini Pro)"):
            mistakes = analyze_bill(st.session_state.bill_data)
            st.session_state.mistakes = mistakes

# --- 3. एप्लीकेशन जनरेशन ---
if 'mistakes' in st.session_state and st.session_state.mistakes is not None:
    st.markdown("---")
    st.markdown("### ✍️ चरण 3: शिकायत पत्र जनरेट करें")
    
    if st.session_state.mistakes:
        st.warning("🚨 निम्नलिखित संभावित विसंगतियाँ पाई गई हैं:")
        
        selected_mistakes = []
        st.session_state.selected_mistakes = []
        
        # यूज़र को चुनने की अनुमति
        for i, mistake in enumerate(st.session_state.mistakes):
            key = f"mistake_{i}"
            checked = st.checkbox(
                f"**[{mistake['Mistake_Code']}]** {mistake['Description_Hindi']}",
                key=key,
                value=True # डिफ़ॉल्ट रूप से सभी चुनें
            )
            if checked:
                selected_mistakes.append(mistake)
        
        st.session_state.selected_mistakes = selected_mistakes
        
        if selected_mistakes:
            col_lang, col_go = st.columns([1, 3])
            
            with col_lang:
                app_language = st.selectbox(
                    "पत्र की भाषा चुनें", 
                    ['Hindi', 'English'],
                    key='app_lang'
                )
            
            app_extra_context = st.text_area(
                "📝 पत्र के लिए अतिरिक्त संदर्भ (Additional Context)",
                placeholder="जैसे: मुझे इस बिल के कारण नोटिस मिला है। कृपया इसे जल्द से जल्द ठीक करें।"
            )
            
            if col_go.button("📝 शिकायत पत्र जनरेट करें", key="generate_app_btn"):
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
    
    col_pdf, col_docx, col_copy = st.columns(3)
    
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
    
    # Text कॉपी करने के लिए Streamlit का उपयोग नहीं होता, पर यूज़र text_area से कॉपी कर सकता है।
    col_copy.markdown("<span></span>", unsafe_allow_html=True)  # स्पेस होल्डर