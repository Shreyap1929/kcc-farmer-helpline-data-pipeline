"""
Content-policy detectors shared by the corpus builder and the runtime gate.

Two families of signals:
- Question intent (English, Marathi, Hindi, romanised): live market price,
  live weather, scheme status, chemical/fertiliser dose.
- Answer content (historical KccAns, Marathi-heavy): chemical dose advice,
  dated weather forecasts, dated mandi prices, time-bound scheme claims.

Stage 1 only flags the two exact weather/mandi template questions. These
detectors widen that net, because many dated answers sit behind free-text
questions such as "MARKET RATE OF ONION ?".

Matching is token based, not \\b based: Python's \\b splits Devanagari words at
vowel signs, so it cannot be trusted for Marathi/Hindi.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from src.cleaning.constants import DEV_TO_ASCII_DIGITS

_PUNCT_RE = re.compile(r"[^\wऀ-ॿ%:+./]+")
_TOKEN_SPLIT_RE = re.compile(r"[\s,;!?()\[\]{}\"'|&_*#=<>-]+")


def normalize_for_matching(text: str | None) -> str:
    """NFC, lowercase, ASCII digits, punctuation to spaces, single spaces."""
    if not text or not isinstance(text, str):
        return ""
    t = unicodedata.normalize("NFC", text).lower().translate(DEV_TO_ASCII_DIGITS)
    t = _TOKEN_SPLIT_RE.sub(" ", t)
    t = re.sub(r"(?<![\d])[./:](?![\d])", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def tokenize(text: str | None) -> list[str]:
    return normalize_for_matching(text).split()


class Lexicon:
    """
    A list of terms matched against normalised tokens.
    - "word"        exact token
    - "two words"   exact phrase (token boundaries)
    - "stem*"       any token starting with stem (handles Marathi inflection)
    """

    def __init__(self, terms: list[str]):
        self.exact: set[str] = set()
        self.phrases: list[str] = []
        self.stems: list[str] = []
        for term in terms:
            term = normalize_for_matching(term.rstrip("*")) + ("*" if term.endswith("*") else "")
            if term.endswith("*"):
                self.stems.append(term[:-1])
            elif " " in term:
                self.phrases.append(term)
            else:
                self.exact.add(term)

    def find(self, tokens: list[str]) -> list[str]:
        hits: list[str] = []
        for tok in tokens:
            if tok in self.exact:
                hits.append(tok)
            else:
                for stem in self.stems:
                    if tok.startswith(stem):
                        hits.append(tok)
                        break
        if self.phrases:
            padded = f" {' '.join(tokens)} "
            hits.extend(p for p in self.phrases if f" {p} " in padded)
        return hits


# ---------------------------------------------------------------------------
# Question-intent lexicons
# ---------------------------------------------------------------------------

# Bare "rate" is deliberately absent: "seed rate" and "fertilizer rate" are
# agronomy, not market questions.
LIVE_MARKET = Lexicon([
    "market rate", "market rates", "market price", "market prices", "market information",
    "market info", "market details", "market committee", "market bhav", "price", "prices",
    "mandi*", "apmc", "bajar bhav", "bajarbhav", "bazar bhav", "bazaar bhav", "bhav",
    "today rate", "todays rate", "current rate", "aajcha bhav", "marketrate*", "marketprice*",
    "बाजारभाव*", "बाजार भाव", "बाजार समिती", "भाव*", "मंडी*", "दाम", "कीमत", "रेट",
])

LIVE_WEATHER = Lexicon([
    "weather", "forecast", "forcast", "forecasting", "rain", "rains", "rainfall", "raining",
    "monsoon", "mansoon", "temperature", "humidity", "hawaman",
    "हवामान*", "पाऊस", "पावसाची", "पावसाचा", "पावसाचे", "पर्जन्यमान", "तापमान", "मौसम",
    "बारिश", "बरसात", "गारपीट",
])

SCHEME = Lexicon([
    "scheme", "schemes", "yojana", "yojna", "yojane", "pm kisan", "pmkisan", "kisan samman",
    "kisan sanman", "samman nidhi", "sanman nidhi", "installment", "installments", "instalment",
    "hafta", "hapta", "ekyc", "e kyc", "kyc", "beneficiary", "subsidy", "anudan", "registration",
    "farmer id", "agristack", "crop insurance", "pmfby", "fasal bima", "pik vima", "insurance",
    "namo shetkari", "kisan credit card", "loan", "compensation", "helpline number",
    "योजना", "योजने*", "हप्ता", "हप्त्या*", "हफ्ता", "किस्त", "अनुदान*", "सबसिडी", "सब्सिडी",
    "विमा", "बीमा", "केवायसी", "नमो", "सन्मान", "लाभार्थी", "कर्ज*", "नुकसान भरपाई",
    "पीएम किसान", "फार्मर आयडी",
])

# A scheme question asking about timing or personal status is time-sensitive
# whatever its answer says (answers phrase dates in endless ways; the English
# call-taker questions do not).
SCHEME_TIMING = Lexicon([
    "date", "dates", "status", "upcoming", "next", "last date", "when", "deadline",
    "installment*", "instalment*", "instalmant*", "hapta", "hafta", "kist",
    "तारीख", "दिनांक", "कधी", "हप्ता", "हप्त्या*", "स्टेटस", "किस्त", "कब",
])

DOSE_QUESTION = Lexicon([
    "dose", "dosage", "doses", "quantity", "how much", "spray", "spraying", "sprey", "sprays",
    "pesticide*", "insecticide*", "fungicide*", "herbicide*", "weedicide*", "chemical*",
    "fertilizer*", "fertiliser*", "urea", "dap", "npk", "potash",
    "फवारणी*", "औषध*", "कीटकनाशक*", "किटकनाशक*", "तणनाशक*", "बुरशीनाशक*", "खत*",
    "डोस", "मात्रा", "युरिया", "यूरिया", "डीएपी",
    "छिड़काव", "छिडकाव", "दवा*", "दवाई", "कीटनाशक*", "खरपतवारनाशक*", "फफूंदनाशक*",
    "खाद", "उर्वरक", "कितना", "कितनी", "nutrient*", "micronutrient*",
])

# General farming vocabulary. A question containing any of these is never
# called out of scope, however low its retrieval similarity (Marathi and Hindi
# questions score lower than English ones against the English KB).
AGRI = Lexicon([
    "crop", "crops", "farm", "farming", "field", "soil", "seed", "seeds", "sowing", "plant", "plants",
    "leaf", "leaves", "disease", "pest", "pests", "insect*", "worm*", "caterpillar*", "weed", "weeds",
    "fruit*", "flower*", "irrigation", "drip", "yield", "harvest*", "cultivation", "variety", "varieties",
    "nursery", "cattle", "cow", "buffalo", "goat", "poultry", "organic", "compost", "manure", "tractor",
    "agriculture", "agricultural", "kisan", "farmer", "farmers", "orchard", "fungus", "wilt", "rot",
    "पीक", "पिक*", "शेत*", "माती", "बियाण*", "पेरणी", "लागवड", "रोग", "कीड", "किड*", "अळी", "तण",
    "पाने", "फुल*", "फळ*", "सिंचन", "ठिबक", "उत्पादन", "वाण", "गाय", "म्हैस", "शेळी", "कोंबड*",
    "सेंद्रिय", "शेणखत", "नांगरणी", "करपा", "मर",
    "फसल", "खेत*", "मिट्टी", "बीज", "बुवाई", "बोवाई", "कीट", "कीड़ा", "इल्ली", "खरपतवार", "पत्त*",
    "फूल", "फल", "सिंचाई", "उपज", "किस्म", "भैंस", "बकरी", "जैविक", "खेती", "किसान",
])

# Words that carry no topic on their own; used to spot vague questions.
FILLER = Lexicon([
    "farmer", "farmers", "asked", "asking", "ask", "about", "query", "on", "information", "info",
    "the", "a", "an", "of", "in", "for", "to", "is", "are", "what", "how", "my", "me", "i",
    "please", "sir", "madam", "tell", "want", "need", "help", "regarding", "related", "give",
    "detail", "details", "and", "or", "it", "this", "that", "do", "can", "you", "?",
    "शेतकरी", "माहिती", "आहे", "काय", "कसे", "कशी", "सांगा", "हवी", "हवे", "पाहिजे", "मला",
    "माझ्या", "माझे", "साहेब", "बद्दल", "विषयी", "द्या", "मदत",
    "क्या", "है", "हैं", "कैसे", "जानकारी", "बताइए", "बताओ", "मेरे", "मेरा", "मुझे", "चाहिए",
    "के", "की", "का", "में", "मदद",
])


# ---------------------------------------------------------------------------
# Answer-content patterns (applied to ans_digits_ascii, i.e. ASCII digits)
# ---------------------------------------------------------------------------

# Advisors often write quantities as words ("चाळीस मिली" = forty ml).
_NUMBER_WORDS = (
    "अर्धा|अर्धी|पाव|दीड|अडीच|एक|दोन|तीन|चार|पाच|सहा|सात|आठ|नऊ|दहा|बारा|पंधरा|वीस|पंचवीस|"
    "तीस|पस्तीस|चाळीस|पन्नास|साठ|पंच्याहत्तर|शंभर|दो|पांच|छह|आधा|डेढ़|ढाई|बीस|पच्चीस|"
    "चालीस|पचास|सौ"
)
_NUM = rf"(?:\d+(?:\.\d+)?|{_NUMBER_WORDS})"
_QTY = "(?<![ऀ-ॿ])" + _NUM + rf"\s*(?:(?:ते|-|to|–)\s*{_NUM}\s*)?"
# Millilitre/gram/ppm amounts are spray or seed-treatment doses in this corpus,
# whatever the product is called (active-ingredient spellings vary endlessly).
SMALL_QTY_RE = re.compile(
    _QTY + r"(?:मि\.?\s?ली|मिलि|मिली|मिलीलीटर|ml|एमएल|ग्रॅम|ग्राम|ग्रॉम|ग्रा\.|gm|grams?|"
    r"g(?![a-z])|पीपीएम|ppm)",
    re.IGNORECASE,
)
# Kilogram/litre/bag amounts are also seed rates and irrigation volumes, so they
# count as a dose only next to a fertiliser or agrochemical word.
# "किलो" must not match "किलोमीटर" (wind speed in forecasts).
BULK_QTY_RE = re.compile(
    _QTY + r"(?:किलो(?!\s*मी)|किग्रॅ|kg|लिटर|लीटर|ltr|litre|liter|lit(?![a-z])|बॅग|bags?)",
    re.IGNORECASE,
)
NPK_RATIO_RE = re.compile(r"(?<![\d:])\d{1,2}\s*:\s*\d{1,2}\s*:\s*\d{1,2}(?![\d:])")
FORMULATION_RE = re.compile(
    rf"{_NUM}\s*%\s*(?:w/w|w/v|डब्ल्यू/डब्ल्यू)?\s*"
    r"(?:ec|sc|wp|wg|wdg|sg|sl|cs|fs|gr|od|zc|se|ई\.?\s?सी|एस\.?\s?सी|डब्ल्यू\.?\s?पी|डब्लू\.?\s?पी|एस\.?\s?जी|एस\.?\s?एल)"
    r"(?![a-z])",
    re.IGNORECASE,
)

# Fertiliser words only matter next to a quantity ("शेणखत" alone is just manure).
FERTILISER = Lexicon([
    "खत*", "युरिया", "यूरिया", "डीएपी", "पोटॅश", "सल्फेट", "फॉस्फेट", "urea", "dap",
])

# Pesticides, sprays and active ingredients: chemical advice even without a dose.
AGROCHEMICAL = Lexicon([
    "फवारणी*", "फवारा*", "फवारावे", "कीटकनाशक*", "किटकनाशक*", "तणनाशक*", "बुरशीनाशक*",
    "औषध*", "ड्रेंचिंग", "आळवणी", "आळणी", "मोरचूद", "इमामेक्टिन*", "इमामेक्टीन*",
    "क्लोरँट्रानिलीप्रोल*", "क्लोराँट्रानिलिप्रोल*", "कोराजन",
    "थायामेथॉक्झाम*", "थायोमेथाक्झाम*", "इमिडाक्लोप्रिड*", "अॅसिटामिप्रीड*", "ॲसिटामिप्रिड*",
    "मॅन्कोझेब*", "कार्बेन्डाझिम*", "ग्लायफोसेट*", "क्विझालोफॉप*", "प्रोफेनोफॉस*",
    "क्लोरपायरीफॉस*", "सायपरमेथ्रिन*", "डायमेथोएट*", "हेक्साकोनाझोल*", "टेब्युकोनाझोल*",
    "टेबुकोनाझोल*", "स्ट्रेप्टोसायक्लिन*", "पेंडीमेथालीन*", "अॅट्राझिन*", "इमॅझेथापायर*",
    "फिप्रोनिल*", "spray*", "insecticide*", "pesticide*", "herbicide*", "fungicide*",
    "mancozeb", "imidacloprid", "emamectin", "chlorantraniliprole", "glyphosate", "thiamethoxam",
])

# Forecast phrasing only: a crop's temperature *requirement* is stable agronomy.
ANS_WEATHER_RE = re.compile(
    r"अंदाजानुसार|हवामान अंदाज|आजचे तापमान|आजचा तापमान|वाऱ्याचा वेग|पावसाची शक्यता|आद्रता"
)
ANS_PRICE_RE = re.compile(
    r"बाजारभाव|बाजार भाव|(?:रु|रुपये|₹|rs)\.?\s*/?\s*(?:प्रति\s*)?क्वि|"
    r"कमीत कमी दर|जास्तीत जास्त दर|सर्वसाधारण दर|quintal\s+\d|"
    # Per-piece / per-kg prices ("३०० रु/नग", "220 rs / kg") and min-max-average quotes.
    r"(?:रु|रुपये|₹|rs)\.?\s*/\s*(?:नग|किलो|kg|डझन|टन)|"
    r"(?:कमीत कमी|किमान).{0,60}(?:जास्तीत जास्त|कमाल).{0,60}सरासरी",
    re.IGNORECASE,
)
# Scheme timing claims, order-independent: an instalment word, a timing word and
# a scheme word anywhere in the answer ("हप्ता" alone is also a split fertiliser
# dose), or an explicit deadline ("मुदत" alone is also crop duration).
_MONTHS = (
    "जानेवारी|फेब्रुवारी|मार्च|एप्रिल|मे महिन्या|जून|जुलै|ऑगस्ट|सप्टेंबर|ऑक्टोबर|ऑक्टोंबर|नोव्हेंबर|"
    "डिसेंबर|जनवरी|फरवरी|अप्रैल|मई|जुलाई|अगस्त|सितंबर|अक्टूबर|नवंबर|दिसंबर"
)
ANS_INSTALMENT_RE = re.compile(r"हप्त|हप्ते|हफ्त|किस्त|installment|instalment", re.IGNORECASE)
ANS_TIMING_RE = re.compile(
    r"तारीख|तारखे|शक्यता|संभावना|लवकर|जमा होणार|जमा होण्यास|जमा झाला|जाहीर|घोषित|येऊ शकतो|येणार|"
    r"रोजी|जारी कर|आने की|महिन्या|आठवड्या|महीने|सप्ताह|" + _MONTHS
)
ANS_SCHEME_WORD_RE = re.compile(r"योजन|सन्मान|सम्मान|किसान|नमो|पीएम|pm|प्रधानमंत्री|पंतप्रधान|विमा|बीमा", re.IGNORECASE)
ANS_DEADLINE_RE = re.compile(
    r"अंतिम तारीख|अंतिम दिनांक|शेवटची तारीख|शेवटचा दिनांक|मुदत\s*(?:आहे|पर्यंत|संपली|संपत)|मुदतवाढ|पर्यंत मुदत|"
    r"last date|deadline|(?:फॉर्म|अर्ज).{0,40}(?:सुरुवात|सुरू)",
    re.IGNORECASE,
)
_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

@dataclass
class QuestionSignals:
    live_market: list[str] = field(default_factory=list)
    live_weather: list[str] = field(default_factory=list)
    scheme: list[str] = field(default_factory=list)
    scheme_timing: list[str] = field(default_factory=list)
    dose: list[str] = field(default_factory=list)
    agri: list[str] = field(default_factory=list)
    content_tokens: list[str] = field(default_factory=list)

    @property
    def is_live(self) -> bool:
        return bool(self.live_market or self.live_weather)


@dataclass
class AnswerSignals:
    dose_advice: bool
    agrochemical: bool
    live_weather: bool
    live_price: bool
    scheme_timebound: bool

    @property
    def chemical(self) -> bool:
        return self.dose_advice or self.agrochemical

    @property
    def time_sensitive(self) -> bool:
        return self.live_weather or self.live_price or self.scheme_timebound


def question_signals(text: str | None) -> QuestionSignals:
    tokens = tokenize(text)
    filler = set(FILLER.find(tokens))
    return QuestionSignals(
        live_market=LIVE_MARKET.find(tokens),
        live_weather=LIVE_WEATHER.find(tokens),
        scheme=SCHEME.find(tokens),
        scheme_timing=SCHEME_TIMING.find(tokens),
        dose=DOSE_QUESTION.find(tokens),
        agri=AGRI.find(tokens),
        content_tokens=[t for t in tokens if t not in filler and len(t) > 1 and not t.isdigit()],
    )


def answer_signals(answer: str | None) -> AnswerSignals:
    a = (answer or "").translate(DEV_TO_ASCII_DIGITS)
    small_qty = bool(SMALL_QTY_RE.search(a))
    bulk_qty = bool(BULK_QTY_RE.search(a))
    formulation = bool(FORMULATION_RE.search(a))
    npk = bool(NPK_RATIO_RE.search(a))
    tokens = tokenize(a)
    agrochem = bool(AGROCHEMICAL.find(tokens))
    fertiliser = bool(FERTILISER.find(tokens))
    return AnswerSignals(
        dose_advice=formulation or small_qty or (bulk_qty and (agrochem or fertiliser or npk)),
        agrochemical=agrochem,
        live_weather=bool(ANS_WEATHER_RE.search(a)),
        live_price=bool(ANS_PRICE_RE.search(a)),
        scheme_timebound=bool(
            (ANS_INSTALMENT_RE.search(a) and ANS_TIMING_RE.search(a) and ANS_SCHEME_WORD_RE.search(a))
            or ANS_DEADLINE_RE.search(a)
        ),
    )


def numbers_in(text: str | None) -> set[str]:
    """Numbers in a text (Devanagari digits mapped to ASCII), for grounding checks."""
    t = (text or "").translate(DEV_TO_ASCII_DIGITS)
    return {n.rstrip(".") for n in _NUMBER_RE.findall(t)}


def ungrounded_numbers(reply: str, sources: list[str]) -> set[str]:
    """
    Source-of-truth rule 6: every number in a reply must appear in a source
    answer. Returns the offending numbers (empty set means the reply passes).
    """
    allowed: set[str] = set()
    for s in sources:
        allowed |= numbers_in(s)
    return numbers_in(reply) - allowed
