"""
Unit tests for the content-policy detectors and crop detection.
No data files needed.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.triage.crops import detect_crops
from src.triage.expansion import expand_query
from src.triage.policy import (
    answer_signals,
    numbers_in,
    question_signals,
    tokenize,
    ungrounded_numbers,
)


# --- question intent ---------------------------------------------------------

@pytest.mark.parametrize("text", [
    "MARKET RATE OF ONION ?",
    "What is the cotton price in Akola mandi today",
    "कांद्याचा आजचा बाजारभाव काय आहे",
    "सोयाबीनला आज काय भाव आहे",
    "प्याज का आज का भाव क्या है",
    "MARKETRATE OF CORIANDER CROP ?",
])
def test_live_market_intent(text):
    assert question_signals(text).live_market


@pytest.mark.parametrize("text", ["seed rate of soybean per acre", "fertilizer rate for wheat"])
def test_agronomy_rate_is_not_market(text):
    assert not question_signals(text).live_market


@pytest.mark.parametrize("text", ["Weather forecast for next week", "उद्या पाऊस पडेल का", "अगले हफ्ते मौसम कैसा रहेगा"])
def test_live_weather_intent(text):
    assert question_signals(text).live_weather


@pytest.mark.parametrize("text", [
    "Status of installment in PM Kisan Samman Nidhi Yojana",
    "पीएम किसान योजनेचा पुढचा हप्ता कधी येणार",
    "पीएम किसान की किस्त कब आएगी",
    "crop insurance helpline number",
])
def test_scheme_intent(text):
    assert question_signals(text).scheme


@pytest.mark.parametrize("text", [
    "ASKING ABOUT PM KISAN SAMMAN NIDHI NEXT INSTALLMENT DATE.",
    "ASKED ABOUT LAST DATE FOR PRADHANMANTRI KHARIB CROP INSURANCE SCHEME 2024 ?",
    "FARMER ASKING ABOUT STATUS OF UPCOMING INSTALLMENT OF PMKISAN SCHEME ?",
])
def test_scheme_timing_questions(text):
    s = question_signals(text)
    assert s.scheme and s.scheme_timing


def test_scheme_eligibility_question_is_not_timing():
    assert not question_signals("Eligibility for drip irrigation subsidy scheme").scheme_timing


@pytest.mark.parametrize("text", [
    "Fertilizer dose for sugarcane",
    "Coragen spraying dose for brinjal",
    "कापसावर काय फवारणी करावी",
    "सोयाबीन मध्ये तणनाशक कोणते वापरावे",
    "गेहूं में कितना यूरिया डालें",
])
def test_dose_intent(text):
    assert question_signals(text).dose


def test_pest_question_without_chemical_words_is_not_dose_intent():
    # Routed by the *answer* side instead (chemical answers go to experts).
    assert not question_signals("Attack of whitefly on cotton crop").dose


@pytest.mark.parametrize("text", ["information", "माहिती हवी", "please tell me", "जानकारी चाहिए"])
def test_vague_questions_have_no_content_tokens(text):
    assert question_signals(text).content_tokens == []


@pytest.mark.parametrize("text", ["पिकावर रोग आला आहे", "my crop has a disease", "फसल में कीट लगे हैं"])
def test_farm_vocabulary(text):
    assert question_signals(text).agri


@pytest.mark.parametrize("text", ["Book a train ticket to Mumbai", "Recharge my mobile phone"])
def test_off_topic_has_no_farm_vocabulary(text):
    assert not question_signals(text).agri


def test_tokenize_keeps_devanagari_words_whole():
    # Python's \b would split these at vowel signs.
    assert tokenize("कापसावर पांढरी माशी!") == ["कापसावर", "पांढरी", "माशी"]


# --- answer content ------------------------------------------------------------

def test_pesticide_dose_in_digits():
    a = "तूर पिकावरील अळी नियंत्रणासाठी कोराजन १०० मिली /२०० लिटर पाण्यात घेवून फवारणी करावी"
    s = answer_signals(a)
    assert s.dose_advice and s.chemical and not s.time_sensitive


def test_dose_written_in_words():
    assert answer_signals("निंबोळी अर्काची चाळीस मिली प्रति पंधरा लिटर पाण्यातून फवारणी घ्यावी").dose_advice


def test_unlisted_active_ingredient_still_caught_by_ml_quantity():
    assert answer_signals("टेबुकोनाझोल २०० लिटर पाणी मध्ये २००-२५० मिली द्या.").dose_advice


def test_named_pesticide_without_dose_is_chemical():
    s = answer_signals("तुर पिकातील अळी नियंत्रणासाठी प्रोफेक्स सुपर या कीटकनाशकाची फवारणी करावी")
    assert not s.dose_advice and s.agrochemical and s.chemical


def test_fertiliser_npk_dose():
    assert answer_signals("१२:३२:१६ हे दाणेदार खत एकरी १ बॅग त्याबरोबर यूरिया २० किलो").dose_advice


def test_seed_rate_is_not_chemical():
    s = answer_signals("सोयाबीनचे फुले संगम वाण घ्यावे. बियाणे 30 किलो प्रति एकर वापरावे.")
    assert not s.chemical


def test_weather_forecast_is_time_sensitive_but_wind_km_is_not_a_dose():
    s = answer_signals("हवामान विभागाच्या अंदाजानुसार आजचे तापमान कमाल 30 अंश सेल्सिअस, वाऱ्याचा वेग ताशी 15 किलोमीटर")
    assert s.live_weather and s.time_sensitive and not s.dose_advice


def test_crop_temperature_requirement_is_not_a_forecast():
    assert not answer_signals("या पिकाला २१ ते २५ से.ग्रे. तापमान चांगले मानवते.").live_weather


@pytest.mark.parametrize("answer", [
    "कांदा पिकाचे बाजार भाव = कमीत कमी 500 रुपये प्रतिक्विंटल",
    "मका पिकाचे पुणे बाजारभाव– किमान - 3000 रु/क्विटल",
    "SAVNER ---- QUINTAL 2800 6650 6725 6700",
    # Found in the KB through a console screenshot: per-piece prices slipped through.
    "कापूस सोलापूर बाजार समिती : दिनांक- ०९/०७/२०२५ कमीत कमी ३०० रु/नग , जास्तीत जास्त ८०० रु/नग , सरासरी ५००",
    "country chicken - 450-600 rs / kg broyler - 220 rs / kg",
])
def test_mandi_prices_are_time_sensitive(answer):
    assert answer_signals(answer).live_price


@pytest.mark.parametrize("answer", [
    "नमो शेतकरी योजनेचा चौथा हप्ता हा लवकरात लवकर जमा होण्याची शक्यता आहे",
    # Found in the KB through a console screenshot: month/date phrasings slipped through.
    "प्रधानमंत्री किसान सन्मान निधी योजना या योजनेतील पुढील हप्त्याची रक्कम डिसेंबर ते मार्च या महिन्यांमध्ये येऊ शकतो",
    "प्रधानमंत्री किसान सन्मान निधीचा विसावा हप्ता 24 जून रोजी जमा करण्यात येणार आहे",
    "पंतप्रधान किसान सन्मान योजना अंतर्गत 18 वा हप्ता ऑक्टोबर महिन्याचे शेवटपर्यंत आपल्याला भेटू शकतो",
    # Timing word before the instalment word, Hindi months, insurance deadlines.
    "माननीय पंतप्रधान २४ फेब्रुवारी २०२५ रोजी पंतप्रधान किसान योजनेचा १९ वा हप्ता जारी करतील.",
    "PM किसान सम्मान निधि योजना ... अगली किस्त जुलाई में आने की संभावना है",
    "रब्बी पिक विमा भरण्यासाठी शेवटची तारीख 30 नोव्हेंबर ही आहे",
])
def test_scheme_instalment_date_claim_is_time_sensitive(answer):
    assert answer_signals(answer).scheme_timebound


@pytest.mark.parametrize("answer", [
    # "हप्ता" = split fertiliser dose; "मुदत" = crop duration. Neither is a scheme date.
    "खोडवा उसाची चांगली फूट होण्यासाठी रासायनिक खतांचा पहिला हप्ता जून महिन्यात द्यावा",
    "मध्यम मुदतीच्या विपुला व ऐ.के.टी – ८८११ या वाणास हेक्टरी २० किलो बियाणे लागते",
])
def test_agronomy_uses_of_scheme_words_are_not_time_bound(answer):
    assert not answer_signals(answer).scheme_timebound


def test_scheme_process_answer_is_not_time_bound():
    a = "शेतकरी साहेब पीएम किसान सन्मान निधी योजनेचे लाभ घेण्यासाठी आपण महा-ई-सेवा केंद्रावर भेट देऊन मोबाईल नंबर अपडेट करून घ्यावा"
    assert not answer_signals(a).scheme_timebound


def test_helpline_numbers_are_not_prices_or_doses():
    s = answer_signals("प्रधानमंत्री पीक विम्याबद्दल अधिक माहितीसाठी 1800 266 0700 या टोल फ्री क्रमांकावर संपर्क करा")
    assert not s.live_price and not s.chemical


# --- grounding -------------------------------------------------------------------

def test_numbers_in_maps_devanagari_digits():
    assert numbers_in("कोराजन १०० मिली / 200 लिटर") == {"100", "200"}


def test_ungrounded_numbers():
    src = ["कोराजन १०० मिली /२०० लिटर पाण्यात"]
    assert ungrounded_numbers("Use 100 ml in 200 litres", src) == set()
    assert ungrounded_numbers("Use 150 ml in 200 litres", src) == {"150"}


# --- crops -------------------------------------------------------------------------

@pytest.mark.parametrize("text,crop", [
    ("ATTACK OF WHITE FLY ON COTTON CROP ?", "Cotton (Kapas)"),
    ("कापसावर पांढरी माशी आली आहे", "Cotton (Kapas)"),
    ("HOW TO CONTROL WILT ATTACK IN GRAM CROP ?", "Bengal Gram (Gram/Chick Pea/Kabuli/Chana)"),
    ("green gram variety", "Green Gram (Moong Bean/ Moong)"),
    ("red gram pod borer", "Pigeon pea (red gram/arhar/tur)"),
    ("मक्के में फॉल आर्मीवर्म", "Maize (Makka)"),
    ("गव्हाचे सुधारित वाण", "Wheat"),
])
def test_detect_crops(text, crop):
    assert detect_crops(text)[0] == crop


def test_green_gram_does_not_also_count_as_bengal_gram():
    assert detect_crops("green gram variety") == ["Green Gram (Moong Bean/ Moong)"]


@pytest.mark.parametrize("text", ["tell us about the scheme", "माशी आले आहे", "my crop has a disease"])
def test_no_false_crop_mentions(text):
    assert detect_crops(text) == []


# --- query expansion ---------------------------------------------------------------

def test_expansion_adds_english_terms_to_marathi():
    out = expand_query("कापसावर पांढरी माशी आली आहे काय फवारणी करावी")
    assert out.startswith("कापसावर पांढरी माशी")
    assert {"whitefly", "spray", "cotton"} <= set(out.split(" | ")[1].split())


def test_expansion_never_changes_english_questions():
    # English must embed exactly as the KB and the threshold calibration did.
    for q in ["Varieties of wheat", "ATTACK OF WHITE FLY ON COTTON CROP ?", ""]:
        assert expand_query(q) == q


def test_expansion_leaves_unknown_devanagari_alone():
    assert expand_query("नमस्कार") == "नमस्कार"
