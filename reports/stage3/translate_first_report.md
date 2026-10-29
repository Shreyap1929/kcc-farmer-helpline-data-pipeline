# Stage 3 - Translate-first experiment

Evaluation uses the frozen held-out retrieval keywords and Marathi/Hindi gate probes.
The safety gate thresholds are unchanged. For adoption, translate-first must strictly
improve held-out top-1 on-topic retrieval and must not reduce expected-route accuracy
compared with current glossary expansion. English inputs are excluded from transformation
and retain the existing query path.

## Results

| Variant | Held-out retrieval on topic | Gate routes correct |
|---|---:|---:|
| plain | 3/12 | 13/14 |
| expanded | 10/12 | 13/14 |
| translate | 9/12 | 13/14 |

**Decision:** Keep glossary expansion.

## Retrieval examples and failures

| Variant | Input | Top-1 KB question | Topic match |
|---|---|---|:-:|
| plain | सोयाबीनवर पाने खाणारी अळी आली आहे | PM Kisan Sanman Nidhi Yojana | no |
| plain | हरभऱ्यावर घाटे अळी | rabi Pradhanmantri Fasal Bima Yojna | no |
| plain | तुरीवर मर रोग | churada - murada (virus)on chilli? | no |
| plain | कांद्याचे वाण कोणते | Pradhan Mantri Kisan Maandhan Yojna ? | no |
| plain | गव्हाची पेरणी कधी करावी | PM fasal bima yojna | no |
| plain | ऊसाला ठिबक सिंचन | rabi Sorghum Water Management | no |
| plain | कापूस पिकात तण नियंत्रण | control managment on brinjal crop regarding sucking pest . | no |
| plain | मक्यावर लष्करी अळी | PM fasal bima yojna | no |
| plain | गेहूं की किस्में | varieties of wheat | yes |
| plain | टमाटर में फल सड़न | asking about fruits in tamarind crop ? | yes |
| plain | मिरचीवर बोकड्या रोग | Phyllody disease on seasame crop | no |
| plain | सोयाबीन पेरणीसाठी बियाणे किती | SEED RATE FOR SOYBEAN SEED? | yes |
| expanded | सोयाबीनवर पाने खाणारी अळी आली आहे | ATTACK OF LEAFE EATING CATERPILLAR ON SOYBEAN? | yes |
| expanded | हरभऱ्यावर घाटे अळी | ATTACK OF LEAF EATING CATERPILLAR on bengal gram crop ? | yes |
| expanded | तुरीवर मर रोग | wilting in tur? | yes |
| expanded | कांद्याचे वाण कोणते | VARITIES OF ONION ? | no |
| expanded | गव्हाची पेरणी कधी करावी | asking about sowing time of wheat ? | yes |
| expanded | ऊसाला ठिबक सिंचन | the irrigation for sugarcane? | yes |
| expanded | कापूस पिकात तण नियंत्रण | KENA WEED CONTROL IN COTTON CROP? | yes |
| expanded | मक्यावर लष्करी अळी | ASKED ABOUT ATTACK OF LEAF EATING CATERPILLAR ON MUNG ? | yes |
| expanded | गेहूं की किस्में | varieties of wheat | yes |
| expanded | टमाटर में फल सड़न | increasing fruit ,fruit size in tomato | yes |
| expanded | मिरचीवर बोकड्या रोग | bokdya disease? | no |
| expanded | सोयाबीन पेरणीसाठी बियाणे किती | SEED RATE FOR SOYBEAN SEED? | yes |
| translate | सोयाबीनवर पाने खाणारी अळी आली आहे | leaf eating caterpillar on soybean | yes |
| translate | हरभऱ्यावर घाटे अळी | ASKED ABOUT POD BORER IN BEANS? | yes |
| translate | तुरीवर मर रोग | BLACK THRIPS ON COTTON CROP? | no |
| translate | कांद्याचे वाण कोणते | varieties of onion ? | yes |
| translate | गव्हाची पेरणी कधी करावी | sugarcane planting time ? | no |
| translate | ऊसाला ठिबक सिंचन | watering sugarcane with drip irrigation? | yes |
| translate | कापूस पिकात तण नियंत्रण | weed control in cotton crop? | yes |
| translate | मक्यावर लष्करी अळी | Armyworm control in maize crop ? | yes |
| translate | गेहूं की किस्में | wheat varieties | yes |
| translate | टमाटर में फल सड़न | asked about fruit rot in tomato | yes |
| translate | मिरचीवर बोकड्या रोग | leaf spot disease on chili crop? | no |
| translate | सोयाबीन पेरणीसाठी बियाणे किती | how many seeds will be required for soybean cultivation? | yes |

## Gate-probe route results

| Variant | Input | Expected | Actual | Correct |
|---|---|---|---|:-:|
| plain | कांद्याचा आजचा बाजारभाव काय आहे | LIVE_DATA_POINTER | LIVE_DATA_POINTER | yes |
| plain | सोयाबीनला आज काय भाव आहे | LIVE_DATA_POINTER | LIVE_DATA_POINTER | yes |
| plain | प्याज का आज का भाव क्या है | LIVE_DATA_POINTER | LIVE_DATA_POINTER | yes |
| plain | उद्या पाऊस पडेल का | LIVE_DATA_POINTER | LIVE_DATA_POINTER | yes |
| plain | अगले हफ्ते मौसम कैसा रहेगा | LIVE_DATA_POINTER | LIVE_DATA_POINTER | yes |
| plain | पीएम किसान योजनेचा पुढचा हप्ता कधी येणार | SCHEME_POINTER | SCHEME_POINTER | yes |
| plain | पीक विमा नुकसान भरपाई कशी मिळेल | SCHEME_POINTER | SCHEME_POINTER | yes |
| plain | पीएम किसान की किस्त कब आएगी | SCHEME_POINTER | SCHEME_POINTER | yes |
| plain | कापसावर पांढरी माशी आली आहे काय फवारणी करावी | EXPERT_REVIEW | EXPERT_REVIEW | yes |
| plain | सोयाबीन मध्ये तणनाशक कोणते वापरावे | EXPERT_REVIEW | EXPERT_REVIEW | yes |
| plain | मक्के में फॉल आर्मीवर्म का नियंत्रण कैसे करें | EXPERT_REVIEW | EXPERT_REVIEW | yes |
| plain | गव्हाचे सुधारित वाण कोणते आहेत | ANSWER | EXPERT_REVIEW | no |
| plain | पिकावर रोग आला आहे | CLARIFY | CLARIFY | yes |
| plain | माहिती हवी | CLARIFY | CLARIFY | yes |
| expanded | कांद्याचा आजचा बाजारभाव काय आहे | LIVE_DATA_POINTER | LIVE_DATA_POINTER | yes |
| expanded | सोयाबीनला आज काय भाव आहे | LIVE_DATA_POINTER | LIVE_DATA_POINTER | yes |
| expanded | प्याज का आज का भाव क्या है | LIVE_DATA_POINTER | LIVE_DATA_POINTER | yes |
| expanded | उद्या पाऊस पडेल का | LIVE_DATA_POINTER | LIVE_DATA_POINTER | yes |
| expanded | अगले हफ्ते मौसम कैसा रहेगा | LIVE_DATA_POINTER | LIVE_DATA_POINTER | yes |
| expanded | पीएम किसान योजनेचा पुढचा हप्ता कधी येणार | SCHEME_POINTER | SCHEME_POINTER | yes |
| expanded | पीक विमा नुकसान भरपाई कशी मिळेल | SCHEME_POINTER | SCHEME_POINTER | yes |
| expanded | पीएम किसान की किस्त कब आएगी | SCHEME_POINTER | SCHEME_POINTER | yes |
| expanded | कापसावर पांढरी माशी आली आहे काय फवारणी करावी | EXPERT_REVIEW | EXPERT_REVIEW | yes |
| expanded | सोयाबीन मध्ये तणनाशक कोणते वापरावे | EXPERT_REVIEW | EXPERT_REVIEW | yes |
| expanded | मक्के में फॉल आर्मीवर्म का नियंत्रण कैसे करें | EXPERT_REVIEW | EXPERT_REVIEW | yes |
| expanded | गव्हाचे सुधारित वाण कोणते आहेत | ANSWER | EXPERT_REVIEW | no |
| expanded | पिकावर रोग आला आहे | CLARIFY | CLARIFY | yes |
| expanded | माहिती हवी | CLARIFY | CLARIFY | yes |
| translate | कांद्याचा आजचा बाजारभाव काय आहे | LIVE_DATA_POINTER | LIVE_DATA_POINTER | yes |
| translate | सोयाबीनला आज काय भाव आहे | LIVE_DATA_POINTER | LIVE_DATA_POINTER | yes |
| translate | प्याज का आज का भाव क्या है | LIVE_DATA_POINTER | LIVE_DATA_POINTER | yes |
| translate | उद्या पाऊस पडेल का | LIVE_DATA_POINTER | LIVE_DATA_POINTER | yes |
| translate | अगले हफ्ते मौसम कैसा रहेगा | LIVE_DATA_POINTER | LIVE_DATA_POINTER | yes |
| translate | पीएम किसान योजनेचा पुढचा हप्ता कधी येणार | SCHEME_POINTER | SCHEME_POINTER | yes |
| translate | पीक विमा नुकसान भरपाई कशी मिळेल | SCHEME_POINTER | SCHEME_POINTER | yes |
| translate | पीएम किसान की किस्त कब आएगी | SCHEME_POINTER | SCHEME_POINTER | yes |
| translate | कापसावर पांढरी माशी आली आहे काय फवारणी करावी | EXPERT_REVIEW | EXPERT_REVIEW | yes |
| translate | सोयाबीन मध्ये तणनाशक कोणते वापरावे | EXPERT_REVIEW | EXPERT_REVIEW | yes |
| translate | मक्के में फॉल आर्मीवर्म का नियंत्रण कैसे करें | EXPERT_REVIEW | EXPERT_REVIEW | yes |
| translate | गव्हाचे सुधारित वाण कोणते आहेत | ANSWER | EXPERT_REVIEW | no |
| translate | पिकावर रोग आला आहे | CLARIFY | CLARIFY | yes |
| translate | माहिती हवी | CLARIFY | CLARIFY | yes |
