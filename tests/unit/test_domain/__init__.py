"""Unit tests for the domain layer — Issue #7 (A2: Domain Validation).

Each module in this package proves one or more domain aggregates across
construction, invariants, serialization, validation, migration, edge cases,
negative cases, and (in :mod:`test_property`) invariant checks over generated
inputs. All monetary values are ``decimal.Decimal`` — never ``float``.
"""
