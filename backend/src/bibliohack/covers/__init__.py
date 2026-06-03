"""Covers context — cover-image enrichment (ARCHITECTURE.md §7.5).

Resolves book covers by ISBN through an ordered provider chain, stores them
content-addressed, and (later slices) serves them immutably. Deliberately
decoupled from catalog ingest: never on the OPAC politeness path, never
hotlinked at request time.
"""
