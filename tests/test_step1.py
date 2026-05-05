"""
Tests for Step 1 services.

Run with: pytest tests/ -v

These tests mock the OpenAI API so they don't require a real key to run.
For integration tests (real API calls), set INTEGRATION=1 in your environment.
"""

import pytest
import json
from unittest.mock import AsyncMock, patch, MagicMock
import os

# ── Unit tests: classification service ────────────────────────────────────────

@pytest.mark.asyncio
async def test_classify_need_software():
    """Classification should identify EHR pain points as SOFTWARE category."""
    mock_response = {
        "department": "Emergency",
        "category": "SOFTWARE",
        "subcategory": "Electronic Health Records (EHR/EMR)",
        "urgency_score": 4,
        "patient_impact_score": 4,
        "keywords": ["EHR", "handoff", "patient safety", "vitals", "shift change"],
        "reasoning": "This describes a workflow gap in EHR during shift handoffs."
    }

    with patch("app.services.classification_service.client") as mock_client:
        mock_client.chat.completions.create = AsyncMock(return_value=MagicMock(
            choices=[MagicMock(message=MagicMock(content=json.dumps(mock_response)))]
        ))

        from app.services.classification_service import classify_need
        from app.models.needs import InnovationCategory

        result = await classify_need(
            "We lose track of patient vitals during shift handoffs. "
            "Nurses spend 20 min per handoff manually transferring notes."
        )

        assert result.category == InnovationCategory.SOFTWARE
        assert result.department == "Emergency"
        assert result.urgency_score == 4
        assert result.patient_impact_score == 4
        assert "EHR" in result.keywords


@pytest.mark.asyncio
async def test_classify_need_hardware():
    """Classification should identify equipment needs as HARDWARE."""
    mock_response = {
        "department": "Radiology",
        "category": "HARDWARE",
        "subcategory": "Diagnostic Imaging Equipment",
        "urgency_score": 5,
        "patient_impact_score": 5,
        "keywords": ["MRI", "downtime", "wait times", "diagnostic", "equipment failure"],
        "reasoning": "Equipment failure directly impacts diagnostic capability."
    }

    with patch("app.services.classification_service.client") as mock_client:
        mock_client.chat.completions.create = AsyncMock(return_value=MagicMock(
            choices=[MagicMock(message=MagicMock(content=json.dumps(mock_response)))]
        ))

        from app.services.classification_service import classify_need
        from app.models.needs import InnovationCategory

        result = await classify_need(
            "Our MRI machine breaks down 3-4 times a month causing critical delays."
        )

        assert result.category == InnovationCategory.HARDWARE
        assert result.urgency_score == 5


@pytest.mark.asyncio
async def test_classify_handles_unknown_category():
    """Should fall back to UNCATEGORIZED for unexpected LLM output."""
    mock_response = {
        "department": "Unknown",
        "category": "SOMETHING_WEIRD",  # not a valid category
        "subcategory": "Unknown",
        "urgency_score": 3,
        "patient_impact_score": 3,
        "keywords": [],
        "reasoning": "."
    }

    with patch("app.services.classification_service.client") as mock_client:
        mock_client.chat.completions.create = AsyncMock(return_value=MagicMock(
            choices=[MagicMock(message=MagicMock(content=json.dumps(mock_response)))]
        ))

        from app.services.classification_service import classify_need
        from app.models.needs import InnovationCategory

        result = await classify_need("Some vague need.")
        assert result.category == InnovationCategory.UNCATEGORIZED


# ── Unit tests: embedding service ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_embed_text_returns_correct_dimensions():
    """Embedding should return a list of 1536 floats."""
    mock_embedding = [0.1] * 1536

    with patch("app.services.embedding_service.client") as mock_client:
        mock_client.embeddings.create = AsyncMock(return_value=MagicMock(
            data=[MagicMock(embedding=mock_embedding)]
        ))

        from app.services.embedding_service import embed_text
        result = await embed_text("test text")

        assert len(result) == 1536
        assert all(isinstance(v, float) for v in result)


@pytest.mark.asyncio
async def test_embed_text_truncates_long_input():
    """Long inputs should be truncated to 8000 chars without error."""
    long_text = "a" * 20000
    mock_embedding = [0.1] * 1536

    with patch("app.services.embedding_service.client") as mock_client:
        mock_client.embeddings.create = AsyncMock(return_value=MagicMock(
            data=[MagicMock(embedding=mock_embedding)]
        ))

        from app.services.embedding_service import embed_text
        result = await embed_text(long_text)

        # Verify that the API was called with truncated text
        call_args = mock_client.embeddings.create.call_args
        assert len(call_args.kwargs["input"]) <= 8000
        assert len(result) == 1536


# ── Model validation tests ────────────────────────────────────────────────────

def test_need_submission_rejects_short_text():
    """Should reject submissions under 20 characters."""
    from pydantic import ValidationError
    from app.models.needs import NeedSubmissionRequest

    with pytest.raises(ValidationError):
        NeedSubmissionRequest(raw_text="too short")


def test_need_submission_accepts_valid_text():
    """Should accept valid free-text submissions."""
    from app.models.needs import NeedSubmissionRequest

    req = NeedSubmissionRequest(
        raw_text="We need better medication reconciliation tools during patient admissions.",
        hospital_id="HOSP_001",
        submitted_by="Charge Nurse"
    )
    assert req.raw_text.startswith("We need")
    assert req.hospital_id == "HOSP_001"
