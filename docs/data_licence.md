# Data licence and attribution

**Dataset:** Kisan Call Centre (KCC) - Transcripts of farmers queries & answers,
Ministry of Agriculture and Farmers Welfare, published on data.gov.in (Maharashtra,
2023-11 to 2025-07 monthly CSVs).

**Licence:** Government Open Data License - India (GODL-India, notified 2017), the
licence data.gov.in applies to its catalogue. The KCC transcript catalogue is listed
under the Open Government License, India on the IndiaAI AIKosh portal, and a KCC
resource on the India Data Platform mirror is listed under GODL.

What GODL-India allows and requires (from the published licence text):

| Point | What it says | How this project complies |
|---|---|---|
| Use | Use, adapt and redistribute for lawful commercial and non-commercial purposes | Research/demo use; code and derived reports published |
| Attribution | Every user must publish an attribution statement naming the provider, source and licence | Statement below, also in the README |
| No endorsement | Must not suggest the provider endorses the user or the use | Stated in the README and the final report |
| Personal information | Not covered by the licence | Stage 1 redacts phone numbers (2,364 rows); raw and cleaned files are never committed (gitignored); reports show call IDs, districts and dates, not names |
| Liability | Provider not liable for errors or for losses from use | The system is decision support and never claims agronomic verification |

**Attribution statement:**

> Kisan Call Centre (KCC) - Transcripts of farmers queries & answers. Ministry of
> Agriculture and Farmers Welfare, Government of India. Source: Open Government Data
> (OGD) Platform India, https://data.gov.in. Licensed under the Government Open Data
> License - India (https://data.gov.in/government-open-data-license-india). This project
> is not endorsed by the Ministry or by data.gov.in.

**How this was checked (2026-10-29):** data.gov.in refuses automated access (HTTP 403),
so the licence text was read from published copies of the GODL-India notification and
the dataset listings above, not from the data.gov.in page itself. Before any public or
commercial deployment, open the dataset page in a browser and confirm the licence field.
