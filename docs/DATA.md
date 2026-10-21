# Data and source boundaries

Runtime data under `data/processed/` is a historical, versioned analytical
snapshot. Metric provenance is stored in the metric catalog and dictionary;
retrieval provenance is retained in the chunk metadata and
`knowledge/rag/source_catalog.csv`. The existing Arabic catalog is retained at
[DATA_CATALOG_AR.md](DATA_CATALOG_AR.md).

Full source PDFs, raw spreadsheets, and the local client ZIP are excluded from
this publication copy. The application and offline tests use the included
runtime tables and prepared retrieval index. To rebuild source extraction or
the RAG index, obtain the original source documents, check their terms, and put
them at the relative paths recorded in the source catalog. The original local
archives remain outside this repository.

Document passages are source-attributed excerpts. Inclusion does not establish
a new license for the original works. See [license status](../LICENSE_NOTICE.md).
