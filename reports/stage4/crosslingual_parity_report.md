# Cross-lingual answer parity (Stage 4)

Source: 80 unseen English test-month questions the production engine answers, and 40 it sends to an expert as dose questions, each rephrased as a Marathi and a Hindi farmer question by `openai/gpt-oss-20b` and translated back by the production translator. See the module docstring in `src/triage/crosslingual_parity.py` for the method. Machine-written questions are cleaner than real speech, so these are upper bounds.

## Answerable questions

| Language | Mode | Answered | Same answer as English | Different answer |
|---|---|---:|---:|---:|
| mr | expanded | 0/80 (0%) | 0/80 (0%) | 0/80 (0%) |
| mr | translate | 3/80 (4%) | 0/80 (0%) | 3/80 (4%) |
| hi | expanded | 0/80 (0%) | 0/80 (0%) | 0/80 (0%) |
| hi | translate | 3/80 (4%) | 1/80 (1%) | 2/80 (2%) |

## Safety: dose questions (must never be answered)

| Language | Mode | Answered |
|---|---|---:|
| mr | expanded | 0/40 (0%) |
| mr | translate | 0/40 (0%) |
| hi | expanded | 0/40 (0%) |
| hi | translate | 0/40 (0%) |

## Decision

Rule (fixed before running): adopt translate-first for Devanagari questions in the chat if it gives more same-as-English answers than glossary expansion, answers no dose question in any mode, and at most 20% of its answers differ from the English answer.

Same-as-English answers: translate 1 vs expanded 0; translate answers that differ: 83%; dose questions answered: 0.

**Keep glossary expansion.**

## Examples

| Set | Lang | Mode | English | Farmer question | Back-translation | Route | Same |
|---|---|---|---|---|---|---|:-:|
| answerable | mr | expanded | ASKED ABOUT SOYBEAN VARIETY ? | सॉयाबीनच्या विविध जातींबद्दल विचारले आहे का? | Have you been asked about various soybean varieties? | CLARIFY |  |
| answerable | mr | expanded | Agriculture University Contact number for the Mango Plant ? | आंबा रोपणासाठी कृषी विद्यापीठाचा संपर्क क्रमांक काय आहे? | What is the contact number of the agricultural university for planting mango saplings? | EXPERT_REVIEW |  |
| answerable | mr | expanded | varieties of Soybean crop ? | सोयाबीनच्या विविध जाती कोणत्या आहेत? | What are the various varieties of soybean? | EXPERT_REVIEW |  |
| answerable | mr | translate | asked about VARIETIES OF SORGHUM ? | सोरघमच्या कोणत्या जाती आहेत? | What are the varieties of sorghum? | EXPERT_REVIEW |  |
| answerable | mr | translate | sowing time of summer season sesamum crop ? | उन्हाळी सिजनमध्ये तिळाचे बियाणे कधी पेरायचे? | When should sesame seeds be sown during the summer season? | EXPERT_REVIEW |  |
| answerable | mr | translate | ASKED ABOUT SOWING SPACING OF COTTON CROP ? | कापूस पेरताना अंतर किती ठेवावं? | What spacing should be maintained when sowing cotton? | EXPERT_REVIEW |  |
| answerable | hi | expanded | NUKSAN BHARPAI FOR TIL CROP ? | तिल की फसल में नुकसान भारपी कितनी होती है? | How much damage does the bollworm cause in the sesame crop? | EXPERT_REVIEW |  |
| answerable | hi | expanded | VSRIETIES OF GREEN MOONG ? | ग्रीन मूंग की किस्में कौन-कौन सी हैं? | What are the varieties of green mung? | EXPERT_REVIEW |  |
| answerable | hi | expanded | FARMER ASKING ABOUT TRAINING FOR PRUNNING IN GUAVA PLANTS ? | आम के पौधों की छंटाई का प्रशिक्षण मिल सकता है? | Can training be provided for pruning mango trees? | OUT_OF_SCOPE |  |
| answerable | hi | translate | VARIETY OF BLACK TURMERIC DETAILS? | काली हल्दी की किस्मों के बारे में जानकारी? | Information about varieties of black turmeric? | EXPERT_REVIEW |  |
| answerable | hi | translate | EVEN AFTER SEVEN OR EIGHT YEARS OF PLANTING, ORANGE TREES ARE NOT BEARING FRUIT? | सात-आठ साल लगवाने के बाद भी संतरे के पेड़ फल क्यों नहीं देते? | Why do orange trees not bear fruit even after seven to eight years? | EXPERT_REVIEW |  |
| answerable | hi | translate | schems for agriculture | कृषि के लिए योजनाएँ क्या हैं? | What are the plans for agriculture? | EXPERT_REVIEW |  |
| answerable | hi | translate | CONTROL OF STRAY ANIMALS IN FARM ? | कृषि में जंगली जानवरों का नियंत्रण कैसे करें? | How to control wild animals in agriculture? | EXPERT_REVIEW |  |
| answerable | hi | translate | INFROMATION OF DAPOLI AND RAHURI UNIVERSITY? | डापोली और रहुरी विश्वविद्यालय की जानकारी क्या है? | What is the information about Dapoli and Rahuri University? | EXPERT_REVIEW |  |
| answerable | hi | translate | seed rate of green gram | हरभरा का बीज दर क्या है? | What is the seed rate for chickpeas? | EXPERT_REVIEW |  |
| answerable | hi | translate | ASKED ABOUT KVK SANGLI CONTACT NUMBER ? | KVK Sangli का संपर्क नंबर क्या है? | What is the contact number of KVK Sangli? | EXPERT_REVIEW |  |
