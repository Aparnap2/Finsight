"""P10-02 RED: sanitizer surface contracts (failing: no implementation).

Four purpose-specific entry points over the same classification-aware
core. Each surface has an independent contract — they must NOT be
assumed identical:

- log: strongest minimization, joinable tokens, injection-neutral.
- llm: minimum necessary context, evidence text kept but scrubbed.
- eval: deterministic + reproducible representation.
- ui: operator-safe masked display.

Plus cross-cutting invariants: determinism, non-mutation, tenant
separation, idempotent re-application, totality (never raises),
fail-closed unknowns, no secret leakage through errors.

Conventions under review (changeable before GREEN):
- PII tokens are full tenant-scoped sha256 hex (existing hash_pii).
- UI masks: email ``r***@domain``, phone keep-first-3+last-4,
  accounts/refs ``******last4``, names first-char + ``***``.
- Financial amounts preserved exactly (Decimal fidelity, no coercion);
  access control — not redaction — protects them.
- Bodies/snippets dropped on log/eval/ui; kept scrubbed+bounded on llm.
"""

from __future__ import annotations

from decimal import Decimal

import pytest


class TestLogSurface:
    def test_email_becomes_joinable_token(self) -> None:
        from shared.privacy.sanitize import sanitize_for_log

        out = sanitize_for_log({"email": "rahul@example.com"}, tenant_id="acme")
        token = out["email"]
        assert token != "rahul@example.com"
        assert "[REDACTED" not in token
        again = sanitize_for_log({"email": "rahul@example.com"}, tenant_id="acme")
        assert again["email"] == token

    def test_secret_key_and_value_redacted(self) -> None:
        from shared.privacy.sanitize import sanitize_for_log

        out = sanitize_for_log(
            {"api_key": "sk-live-abc123xyz", "note": "Bearer abc.def.ghi"},
            tenant_id="acme",
        )
        assert out["api_key"] == "[REDACTED]"
        assert "abc.def.ghi" not in out["note"]
        assert "sk-live-abc123xyz" not in out["note"]

    def test_body_dropped_in_logs(self) -> None:
        from shared.privacy.sanitize import sanitize_for_log

        out = sanitize_for_log(
            {"subject": "refund?", "body": "please refund rahul@example.com"},
            tenant_id="acme",
        )
        assert out["body"] == "[REDACTED]"
        assert "rahul@example.com" not in str(out)

    def test_payment_ids_preserved_with_classification(self) -> None:
        from shared.privacy.inventory import DataClassification
        from shared.privacy.sanitize import sanitize_for_log

        classifications = {
            "payment_id": DataClassification.INTERNAL,
            "charge": DataClassification.INTERNAL,
            "execution_id": DataClassification.INTERNAL,
        }
        out = sanitize_for_log(
            {"payment_id": "pay_123", "charge": "ch_001", "execution_id": "exec-1"},
            tenant_id="acme",
            classifications=classifications,
        )
        assert out == {
            "payment_id": "pay_123",
            "charge": "ch_001",
            "execution_id": "exec-1",
        }

    def test_amounts_masked_in_logs(self) -> None:
        from shared.privacy.inventory import DataClassification
        from shared.privacy.sanitize import sanitize_for_log

        out = sanitize_for_log(
            {"gross": Decimal("15000.00")},
            tenant_id="acme",
            classifications={"gross": DataClassification.FINANCIAL_SENSITIVE},
        )
        assert out["gross"] == "[FINANCIAL_SENSITIVE]"

    def test_unclassified_string_fails_closed(self) -> None:
        from shared.privacy.sanitize import sanitize_for_log

        out = sanitize_for_log({"note": "hello"}, tenant_id="acme")
        assert out["note"] == "[REDACTED]"

    def test_unclassified_number_fails_closed(self) -> None:
        from shared.privacy.sanitize import sanitize_for_log

        out = sanitize_for_log({"count": 3}, tenant_id="acme")
        assert out["count"] == "[REDACTED]"

    def test_explicit_preserve_opt_in(self) -> None:
        from shared.privacy.sanitize import sanitize_for_log

        out = sanitize_for_log({"note": "hello"}, tenant_id="acme", unknown="preserve")
        assert out["note"] == "hello"
        hostile = sanitize_for_log(
            {"note": "hello", "api_key": "sk-live-abc123xyz"},
            tenant_id="acme",
            unknown="preserve",
        )
        assert hostile["api_key"] != "sk-live-abc123xyz"

    def test_invalid_unknown_mode_rejected(self) -> None:
        from shared.privacy.sanitize import sanitize_for_log

        with pytest.raises(ValueError):
            sanitize_for_log(
                {"a": 1},
                tenant_id="acme",
                unknown="whatever",  # type: ignore[arg-type]
            )

    def test_log_injection_neutralized(self) -> None:
        from shared.privacy.sanitize import sanitize_for_log

        out = sanitize_for_log({"note": "a\nb\r\nc"}, tenant_id="acme", unknown="preserve")
        assert out["note"] == "a b c"

    def test_ui_neutralizes_newlines(self) -> None:
        from shared.privacy.sanitize import sanitize_for_ui

        out = sanitize_for_ui({"note": "a\nb"}, tenant_id="acme", unknown="preserve")
        assert out["note"] == "a b"


class TestLlmSurface:
    def test_evidence_text_kept_but_scrubbed(self) -> None:
        from shared.privacy.inventory import DataClassification
        from shared.privacy.sanitize import sanitize_for_llm

        out = sanitize_for_llm(
            {"evidence": "invoice total $100, contact rahul@example.com, key sk-live-abc123xyz"},
            tenant_id="acme",
            classifications={"evidence": DataClassification.INTERNAL},
        )
        assert "invoice total $100" in out["evidence"]
        assert "rahul@example.com" not in out["evidence"]
        assert "sk-live-abc123xyz" not in out["evidence"]

    def test_bodies_bounded_not_dropped(self) -> None:
        from shared.privacy.sanitize import sanitize_for_llm

        out = sanitize_for_llm({"snippet": "x" * 5000}, tenant_id="acme")
        assert len(out["snippet"]) <= 500
        assert out["snippet"] != "[REDACTED]"

    def test_llm_preserves_semantic_newlines(self) -> None:
        from shared.privacy.inventory import DataClassification
        from shared.privacy.sanitize import sanitize_for_llm

        out = sanitize_for_llm(
            {"evidence": "line one\nline two"},
            tenant_id="acme",
            classifications={"evidence": DataClassification.INTERNAL},
        )
        assert out["evidence"] == "line one\nline two"

    def test_amounts_preserved_exactly_on_permit_surfaces(self) -> None:
        from shared.privacy.inventory import DataClassification
        from shared.privacy.sanitize import sanitize_for_eval, sanitize_for_llm, sanitize_for_ui

        classifications = {"gross": DataClassification.FINANCIAL_SENSITIVE}
        for fn in (sanitize_for_llm, sanitize_for_eval, sanitize_for_ui):
            out = fn(
                {"gross": Decimal("15000.00")},
                tenant_id="acme",
                classifications=classifications,
            )
            assert out["gross"] == Decimal("15000.00")

    def test_explicit_name_classification_tokenizes(self) -> None:
        from shared.privacy.inventory import DataClassification
        from shared.privacy.sanitize import sanitize_for_llm

        out = sanitize_for_llm(
            {"customer_name": "Rahul Sharma"},
            tenant_id="acme",
            classifications={"customer_name": DataClassification.PERSONAL},
        )
        assert out["customer_name"] != "Rahul Sharma"

    def test_secret_classification_excludes_value(self) -> None:
        from shared.privacy.inventory import DataClassification
        from shared.privacy.sanitize import sanitize_for_llm

        out = sanitize_for_llm(
            {"webhook_secret": "whsec_abc"},
            tenant_id="acme",
            classifications={"webhook_secret": DataClassification.SECRET},
        )
        assert out["webhook_secret"] != "whsec_abc"


class TestEvalSurface:
    def test_eval_is_deterministic_and_canonical(self) -> None:
        from shared.privacy.sanitize import sanitize_for_eval

        payload = {"b": "rahul@example.com", "a": [1, None, {"c": "x@y.zz"}]}
        first = sanitize_for_eval(payload, tenant_id="acme")
        second = sanitize_for_eval(payload, tenant_id="acme")
        assert first == second
        assert list(first) == sorted(first)
        assert "rahul@example.com" not in str(first)

    def test_eval_matches_llm_transforms(self) -> None:
        from shared.privacy.sanitize import sanitize_for_eval, sanitize_for_llm

        payload = {"email": "rahul@example.com", "amount": Decimal("10.50")}
        assert sanitize_for_eval(payload, tenant_id="acme") == sanitize_for_llm(
            payload, tenant_id="acme"
        )


class TestUiSurface:
    def test_email_masked_for_display(self) -> None:
        from shared.privacy.sanitize import sanitize_for_ui

        out = sanitize_for_ui({"email": "rahul@example.com"}, tenant_id="acme")
        assert out["email"] == "r***@example.com"

    def test_phone_masked_for_display(self) -> None:
        from shared.privacy.sanitize import sanitize_for_ui

        out = sanitize_for_ui({"phone": "+919876543210"}, tenant_id="acme")
        assert out["phone"] == "+91******3210"
        assert "987654" not in out["phone"]

    def test_account_masked_for_display(self) -> None:
        from shared.privacy.sanitize import sanitize_for_ui

        out = sanitize_for_ui({"account": "123456789012"}, tenant_id="acme")
        assert out["account"] == "******9012"

    def test_name_masked_for_display(self) -> None:
        from shared.privacy.inventory import DataClassification
        from shared.privacy.sanitize import sanitize_for_ui

        out = sanitize_for_ui(
            {"customer_name": "Rahul Sharma"},
            tenant_id="acme",
            classifications={"customer_name": DataClassification.PERSONAL},
        )
        assert out["customer_name"] == "R***"
        assert "Rahul" not in out["customer_name"]

    def test_amounts_visible_to_operators(self) -> None:
        from shared.privacy.inventory import DataClassification
        from shared.privacy.sanitize import sanitize_for_ui

        out = sanitize_for_ui(
            {"gross": Decimal("15000.00")},
            tenant_id="acme",
            classifications={"gross": DataClassification.FINANCIAL_SENSITIVE},
        )
        assert out["gross"] == Decimal("15000.00")


class TestCrossCutting:
    def test_nested_lists_and_none(self) -> None:
        from shared.privacy.sanitize import sanitize_for_log

        payload = {"a": [{"email": "x@y.zz"}, None, ["nobody@nowhere.io"]], "b": None}
        out = sanitize_for_log(payload, tenant_id="acme")
        assert out["b"] is None
        assert out["a"][1] is None
        assert "x@y.zz" not in str(out)
        assert "nobody@nowhere.io" not in str(out)

    def test_input_never_mutated(self) -> None:
        import copy

        from shared.privacy.sanitize import sanitize_for_log

        payload = {"email": "a@b.co", "nested": {"k": "sk-live-abc123xyz"}}
        snapshot = copy.deepcopy(payload)
        sanitize_for_log(payload, tenant_id="acme")
        assert payload == snapshot

    def test_tenant_separation(self) -> None:
        from shared.privacy.sanitize import sanitize_for_log

        a = sanitize_for_log({"email": "same@example.com"}, tenant_id="acme")
        b = sanitize_for_log({"email": "same@example.com"}, tenant_id="beta")
        assert a["email"] != b["email"]

    def test_blank_tenant_rejected(self) -> None:
        from shared.privacy.sanitize import sanitize_for_log

        with pytest.raises(ValueError):
            sanitize_for_log({"a": 1}, tenant_id="  ")

    def test_unknown_secret_like_key_fails_closed(self) -> None:
        from shared.privacy.sanitize import sanitize_for_log

        out = sanitize_for_log({"mystery_credential_blob": "hunter2-hunter2"}, tenant_id="acme")
        assert out["mystery_credential_blob"] != "hunter2-hunter2"

    def test_already_sanitized_stable(self) -> None:
        from shared.privacy.sanitize import sanitize_for_log

        once = sanitize_for_log({"email": "a@b.co"}, tenant_id="acme")
        twice = sanitize_for_log(once, tenant_id="acme")
        assert twice == once

    def test_never_raises_and_never_leaks_in_errors(self) -> None:
        from shared.privacy import sanitize as mod

        hostile = {"k": object(), "sk": "sk-live-abc123xyz", "n": None}
        for fn in (
            mod.sanitize_for_log,
            mod.sanitize_for_llm,
            mod.sanitize_for_eval,
            mod.sanitize_for_ui,
        ):
            try:
                out = fn(hostile, tenant_id="acme")
            except ValueError:
                continue
            assert "sk-live-abc123xyz" not in str(out)
