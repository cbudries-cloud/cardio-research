# packages/evidence-tools

Evidence-record format (`evidence_tools/schema.py`) and validator (`evidence_tools/validate.py`)
shared by the public notebook (`apps/notebook`) and the future research layer.

```bash
make research-validate   # schema + source-fidelity + chart-input checks on research/
```

Records live in `research/`. They contain published evidence only, never personal data.
