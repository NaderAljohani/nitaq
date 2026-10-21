# Publication preparation

The publication copy is based on the existing local Nitaq application. It keeps
runtime data, retrieval metadata, application code, and offline tests.

- Excluded credentials, Git history, environments, caches, full source PDFs, and the client handoff archive.
- Replaced machine-specific onboarding with repository-relative commands.
- Corrected AppTest entrypoint paths for the installed Streamlit test API.
- Added a resolved dependency file, release checks, and Windows/Linux CI configuration.
- Kept analytical behavior and existing evaluation cases.

Validation results are recorded outside the repository in the preparation
report. Live provider calls and a hosted deployment were not part of the offline
verification. No new open-source license was selected.
