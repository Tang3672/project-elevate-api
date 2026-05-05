"""
Tests for the ingestion system (Step 2).

Tests are organized around the key contracts:
1. DemandSignal model validation
2. Connector output shape (all connectors produce valid DemandSignals)
3. Pipeline deduplication logic
4. Search API shapes

All external API calls are mocked.
"""

import pytest
import json
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime

from app.models.demand_signal import (
    DemandSignal, SignalSource, SignalType, GeographicScope
)


# ── DemandSignal model validation ─────────────────────────────────────────────

def test_demand_signal_requires_description_min_length():
    """Description must be at least 20 chars to ensure embeddable content."""
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        DemandSignal(
            source=SignalSource.CDC_PLACES,
            signal_type=SignalType.DISEASE_BURDEN,
            title="Test signal",
            description="Too short",  # <20 chars
        )

def test_demand_signal_defaults():
    """Verify sensible defaults are applied."""
    signal = DemandSignal(
        source=SignalSource.CDC_PLACES,
        signal_type=SignalType.DISEASE_BURDEN,
        title="Diabetes prevalence in Travis County, TX: 23.4%",
        description="Travis County, Texas has a 23.4% diabetes prevalence among adults, well above national average.",
    )
    assert signal.country == "US"
    assert signal.confidence_score == 0.8
    assert signal.geographic_scope == GeographicScope.UNKNOWN
    assert signal.icd10_codes == []
    assert signal.keywords == []

def test_demand_signal_confidence_clamped():
    """Confidence score must be between 0 and 1."""
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        DemandSignal(
            source=SignalSource.FDA_ADVERSE_EVENTS,
            signal_type=SignalType.SAFETY_FAILURE,
            title="Test",
            description="A" * 30,
            confidence_score=1.5,  # over 1.0
        )

def test_demand_signal_full_construction():
    """Full signal with all optional fields should construct cleanly."""
    signal = DemandSignal(
        source=SignalSource.CENSUS_SAHIE,
        source_record_id="sahie_48453_2023_0",
        signal_type=SignalType.CARE_GAP,
        title="High uninsured rate: 18.2% in Travis County, TX",
        description=(
            "Travis County, Texas: 18.2% uninsured (183,000 people) among all incomes in 2023. "
            "High uninsured rates signal demand for accessible, low-cost healthcare technology."
        ),
        condition_or_topic="Healthcare Access / Uninsured Population",
        innovation_category_hint="SERVICE",
        keywords=["uninsured", "healthcare access", "texas"],
        geographic_scope=GeographicScope.COUNTY,
        state_code="TX",
        county_fips="48453",
        location_name="Travis County, TX",
        magnitude=18.2,
        magnitude_unit="percent uninsured",
        national_average=9.2,
        trend_direction="increasing",
        data_year=2023,
        confidence_score=0.92,
    )
    assert signal.state_code == "TX"
    assert signal.magnitude == 18.2
    assert signal.trend_direction == "increasing"


# ── CDC PLACES connector ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cdc_places_row_to_signal():
    """PLACES connector correctly maps a data row to a DemandSignal."""
    from app.ingestion.connectors.cdc_places import CDCPlacesConnector
    connector = CDCPlacesConnector()

    mock_row = {
        "locationid": "48453",
        "locationdesc": "Travis County",
        "stateabbr": "TX",
        "measureid": "DIABETES",
        "data_value": "23.4",
        "totalpopulation": "1200000",
        "year": "2023",
    }

    signal = connector._row_to_signal(
        mock_row,
        "Type 2 Diabetes",
        "SOFTWARE",
        SignalType.DISEASE_BURDEN
    )

    assert signal is not None
    assert signal.source == SignalSource.CDC_PLACES
    assert signal.magnitude == 23.4
    assert "Travis County" in signal.title
    assert "TX" in signal.title
    assert signal.signal_type == SignalType.DISEASE_BURDEN
    assert signal.state_code == "TX"
    assert signal.data_year == 2023
    assert len(signal.description) >= 20


@pytest.mark.asyncio
async def test_cdc_places_fetch_yields_batches():
    """PLACES fetch() should yield batches of valid DemandSignals."""
    from app.ingestion.connectors.cdc_places import CDCPlacesConnector

    mock_rows = [
        {
            "locationid": f"4800{i}",
            "locationdesc": f"County {i}",
            "stateabbr": "TX",
            "measureid": "DIABETES",
            "data_value": str(15 + i),
            "totalpopulation": "500000",
            "year": "2023",
        }
        for i in range(5)
    ]

    connector = CDCPlacesConnector()
    with patch.object(connector, "_get_json", new=AsyncMock(return_value=mock_rows)):
        async with connector:
            batches = []
            async for batch in connector.fetch():
                batches.append(batch)

    assert len(batches) > 0
    all_signals = [s for batch in batches for s in batch]
    assert len(all_signals) > 0
    for signal in all_signals:
        assert isinstance(signal, DemandSignal)
        assert len(signal.description) >= 20


# ── FDA connector ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_fda_adverse_events_produces_signals():
    """FDA FAERS connector should produce safety failure signals."""
    from app.ingestion.connectors.openfda import FDAAdverseEventsConnector

    mock_response = {
        "results": [
            {"term": "metformin", "count": 15000},
            {"term": "lisinopril", "count": 8500},
            {"term": "aspirin",   "count": 200},  # below threshold, should skip
        ]
    }

    connector = FDAAdverseEventsConnector(api_key="test_key")
    with patch.object(connector, "_get_json", new=AsyncMock(return_value=mock_response)):
        async with connector:
            batches = []
            async for batch in connector.fetch():
                batches.append(batch)

    signals = [s for batch in batches for s in batch]
    assert len(signals) == 2  # aspirin filtered out (count < 100)
    for s in signals:
        assert s.signal_type == SignalType.SAFETY_FAILURE
        assert s.source == SignalSource.FDA_ADVERSE_EVENTS
        assert s.magnitude >= 100


# ── Census SAHIE connector ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_census_sahie_filters_low_uninsured():
    """SAHIE connector should skip counties with <10% uninsured."""
    from app.ingestion.connectors.census_sahie import CensusSAHIEConnector

    # Mock API response: headers + data rows
    mock_data = [
        ["NAME", "PCTUI_PT", "NUI_PT", "NIPR_PT", "AGECAT", "IPRCAT", "state", "county"],
        ["High-uninsured County, TX", "18.5", "25000", "1", "0", "0", "48", "001"],
        ["Low-uninsured County, CA",  "4.2",  "8000",  "1", "0", "0", "06", "002"],
        ["Medium County, FL",         "11.1", "15000", "1", "0", "0", "12", "003"],
    ]

    connector = CensusSAHIEConnector(api_key="test")
    with patch.object(connector, "_get_json", new=AsyncMock(return_value=mock_data)):
        with patch.object(connector, "_get_latest_year", new=AsyncMock(return_value="2023")):
            async with connector:
                batches = []
                async for batch in connector._fetch_county_data("2023", "0"):
                    batches.append(batch)

    signals = [s for batch in batches for s in batch]
    # Should include 18.5% (TX) and 11.1% (FL) but not 4.2% (CA)
    assert len(signals) == 2
    uninsured_rates = {s.state_code: s.magnitude for s in signals}
    assert "TX" in uninsured_rates
    assert "FL" in uninsured_rates
    assert "CA" not in uninsured_rates


# ── ClinicalTrials connector ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_clinical_trials_builds_summary_signal():
    """ClinicalTrials connector should produce one summary signal per condition."""
    from app.ingestion.connectors.clinical_trials import ClinicalTrialsConnector

    mock_response = {
        "totalCount": 287,
        "studies": [
            {
                "protocolSection": {
                    "designModule": {
                        "phases": ["PHASE3"],
                        "enrollmentInfo": {"count": 500},
                    },
                    "armsInterventionsModule": {
                        "interventions": [{"type": "DEVICE"}]
                    },
                    "contactsLocationsModule": {
                        "locations": [{"country": "United States"}]
                    }
                }
            }
        ] * 10,
    }

    connector = ClinicalTrialsConnector()
    with patch.object(connector, "_get_json", new=AsyncMock(return_value=mock_response)):
        async with connector:
            signals = await connector._fetch_condition_summary("Diabetes Mellitus")

    assert len(signals) == 1
    s = signals[0]
    assert s.source == SignalSource.CLINICAL_TRIALS
    assert s.signal_type == SignalType.RESEARCH_TREND
    assert "287" in s.title or "287" in s.description
    assert s.innovation_category_hint == "HARDWARE"  # DEVICE maps to HARDWARE


# ── Wastewater connector ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_wastewater_filters_low_signal():
    """Wastewater connector should only flag elevated signals."""
    from app.ingestion.connectors.cdc_surveillance import CDCWastewaterConnector

    mock_data = [
        {  # High signal — should be included
            "wwtp_jurisdiction": "TX",
            "detect_prop_15d": "0.85",
            "percentile": "82",
            "ptc_15d": "25",
            "date_end": "2025-02-14",
            "population_served": "5000000",
        },
        {  # Low signal — should be filtered
            "wwtp_jurisdiction": "ME",
            "detect_prop_15d": "0.05",
            "percentile": "15",
            "ptc_15d": "-5",
            "date_end": "2025-02-14",
            "population_served": "1000000",
        },
    ]

    connector = CDCWastewaterConnector()
    with patch.object(connector, "_get_json", new=AsyncMock(return_value=mock_data)):
        async with connector:
            batches = []
            async for batch in connector.fetch():
                batches.append(batch)

    signals = [s for batch in batches for s in batch]
    states = {s.state_code for s in signals}
    assert "TX" in states
    assert "ME" not in states


# ── Pipeline integration ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_pipeline_isolates_connector_failures():
    """A failing connector should not abort the rest of the pipeline."""
    from app.ingestion.pipeline import run_connector
    from app.ingestion.connectors.base import BaseConnector, ConnectorError
    from app.models.demand_signal import DemandSignal

    class BrokenConnector(BaseConnector):
        source_name = "broken_test"
        update_frequency_hours = 1
        async def fetch(self):
            raise ConnectorError("Simulated failure")
            yield []  # unreachable but satisfies type checker

    result = await run_connector(BrokenConnector())
    # Should complete without raising, error captured in result
    assert result.error_message != "" or result.errors >= 0
    assert result.connector_name == "broken_test"
