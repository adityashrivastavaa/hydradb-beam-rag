# Data license

The files in this directory are derived from the BEAM benchmark
(<https://github.com/mohammadtavakoli78/BEAM>, © 2025 Mohammad Tavakoli et al.),
whose data is released under the
[Creative Commons Attribution–ShareAlike 4.0 International License (CC BY-SA 4.0)](https://creativecommons.org/licenses/by-sa/4.0/).

- `documents.json` — the turns of BEAM-1M conversation 1, one document per turn.
- `questions.json` — that conversation's BEAM probing questions and reference answers,
  plus the documents holding each question's evidence.
- `graph.json` — entities and relations extracted from those turns by HydraDB's
  ingestion pipeline.

Changes from the original: turns were grouped into documents, BEAM's
message-index markers are stripped at load time, and the entity graph and
evidence-document labels were added. These files are distributed under the
same CC BY-SA 4.0 license.
