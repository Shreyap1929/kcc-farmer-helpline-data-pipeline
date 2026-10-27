"""
Embedding-model probe: which multilingual model ranks a Marathi/Hindi/English
farmer question closest to the right English KCC question summary?

    python -m src.triage.embedding_probe intfloat/multilingual-e5-base sentence-transformers/LaBSE

Results are recorded in reports/stage2/embedding_model_probe.md.
"""
from __future__ import annotations

import sys
import time

import numpy as np

# English call-taker summaries, as they appear in the KCC data.
DOCS = [
    "MARKET RATE OF ONION ?",
    "ATTACK OF WHITE FLY ON COTTON CROP ?",
    "STATUS OF INSTALLMENT IN PRADHANMANTRI KISAN SANMAN NIDHI YOJANA ?",
    "WEED MANAGEMENT IN SOYBEAN ?",
    "FERTILIZER DOSE FOR SUGARCANE ?",
    "HOW TO CONTROL WILT ATTACK IN BENGAL GRAM CROP ?",
    "WEATHER FORECAST ?",
    "CROP LOSS & CROP INSURANCE RELATED INFORMATION & THEIR HELPLINE NUMBER ?",
    "VARIETY OF WHEAT ?",
    "ATTACK OF LEAF EATING CATERPILLAR ON SOYBEAN ?",
    "FLOWER DROP IN COTTON ?",
    "SOWING TIME OF MAIZE ?",
    "HOW TO CONTROL FALL ARMYWORM IN MAIZE ?",
    "GROWTH SPRAY FOR ONION CROP ?",
    "DRIP IRRIGATION SUBSIDY INFORMATION ?",
]

# (farmer-style question, index of the correct DOCS entry)
QUERIES = [
    ("कांद्याचा बाजार भाव काय आहे", 0),
    ("कापसावर पांढरी माशी आली आहे", 1),
    ("पीएम किसान हप्ता कधी येणार", 2),
    ("सोयाबीन मध्ये तण नियंत्रण कसे करावे", 3),
    ("ऊसाला खताची मात्रा किती द्यावी", 4),
    ("हरभरा पिकात मर रोग", 5),
    ("उद्या पाऊस पडेल का", 6),
    ("पीक विमा माहिती हवी", 7),
    ("गव्हाचे वाण कोणते", 8),
    ("सोयाबीन वर पाने खाणारी अळी", 9),
    ("कपास में फूल गिर रहे हैं", 10),
    ("मक्का की बुवाई का समय", 11),
    ("मक्के में फॉल आर्मीवर्म का नियंत्रण", 12),
    ("प्याज की बढ़वार के लिए छिड़काव", 13),
    ("ठिबक सिंचन अनुदान", 14),
    ("onion price today", 0),
    ("white flies in cotton", 1),
]


def probe(model_name: str) -> dict:
    from sentence_transformers import SentenceTransformer

    prefix = "query: " if "e5" in model_name else ""
    model = SentenceTransformer(model_name, device="cpu")
    d = model.encode([prefix + t for t in DOCS], normalize_embeddings=True)
    q = model.encode([prefix + t for t, _ in QUERIES], normalize_embeddings=True)
    sims = q @ d.T
    gold = [g for _, g in QUERIES]
    ranks = np.array([int((sims[i] > sims[i, g]).sum()) + 1 for i, g in enumerate(gold)])
    margin = np.mean([sims[i, g] - np.max(np.delete(sims[i], g)) for i, g in enumerate(gold)])

    start = time.time()
    model.encode([prefix + t for t in DOCS * 40], batch_size=128)
    return {
        "model": model_name,
        "top1": float(np.mean(ranks == 1)),
        "mrr": float(np.mean(1 / ranks)),
        "margin": float(margin),
        "per_second": len(DOCS) * 40 / (time.time() - start),
        "ranks": ranks.tolist(),
    }


if __name__ == "__main__":
    for name in sys.argv[1:]:
        r = probe(name)
        print(f"{r['model']}: top1={r['top1']:.2f} mrr={r['mrr']:.2f} margin={r['margin']:.3f} "
              f"speed={r['per_second']:.0f}/s ranks={r['ranks']}")
