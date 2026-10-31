# Specialist readers and models: evaluation status

## CS1

**Status: evaluation candidate only. Not installed, not called, not a dependency.**

No official release of CS1 has been verified in this project: its weights, code, licence and
commercial permissions are **unverified**, and nothing here should be read as saying they are
available. Before any evaluation, record the official release source (publisher, URL, version,
licence text) in this file.

## How any specialist is evaluated

A specialist plugs in as a `ClinicalRecordReader` (`services/api/app/research/readers.py`) or as
a provider for the interpretation step (`providers.py`). It is compared with the existing baseline
on the **same snapshot inputs** using `compare_readers`, which reports per-role agreement, items
found only by one reader, errors, abstentions, latency and cost. The baseline is the deterministic
reader plus the v0.1 rules; it stays in place whatever the result. Readers return observation IDs
only: values, units, dates and all arithmetic remain in ordinary code.

A specialist is adopted only if it is no worse than the baseline on agreement and errors for the
roles it is used for, and its data-processing terms are approved by the participant.
