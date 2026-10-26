"""ChartItem, DrugInfo, SickMessage: verbatim text and required sources."""

from datetime import date, datetime, timedelta, timezone

import pytest

from curaai.domain.chart_item import ChartItem
from curaai.domain.drug_info import DrugInfo
from curaai.domain.errors import MissingSourceReference
from curaai.domain.lookback import LookbackWindow
from curaai.domain.sick_message import SickMessage
from curaai.domain.values import ChartItemKind, ItemId, MessageId, Origin, PatientId

TZ = timezone(timedelta(hours=-4))
WINDOW = LookbackWindow(date(2026, 9, 18), date(2026, 10, 16))


def med(start, end=None, **kw):
    defaults = dict(item_id=ItemId("m1"), kind=ChartItemKind.MEDICATION, date=start, end_date=end,
                    title="Lisinopril", detail="40 mg PO daily · Increased from 20 mg",
                    source_ref="MedicationRequest/p1-mr1")
    return ChartItem(**{**defaults, **kw})


def test_chart_item_without_source_is_rejected():
    with pytest.raises(MissingSourceReference):
        med(date(2026, 9, 22), source_ref="  ")


def test_chart_item_detail_is_kept_byte_for_byte():
    detail = "  BP 148/92, home log elevated.  Increase lisinopril to 40 mg daily.  "
    assert med(date(2026, 9, 22), detail=detail).detail == detail


def test_change_counts_if_started_or_stopped_inside_window():
    assert med(date(2026, 9, 22)).is_change_within(WINDOW)                       # dose increase
    assert med(date(2025, 2, 10), end=date(2026, 9, 22)).is_change_within(WINDOW)  # old dose stopped
    assert not med(date(2024, 6, 3)).is_change_within(WINDOW)                   # long-standing metformin


def test_active_medication_check():
    today = date(2026, 10, 16)
    assert med(date(2026, 9, 22)).is_active_medication_on(today)
    assert not med(date(2025, 2, 10), end=date(2026, 9, 22)).is_active_medication_on(today)


def test_drug_info_requires_source_and_some_text():
    with pytest.raises(MissingSourceReference):
        DrugInfo(drug_name="lisinopril", source_ref="", adverse_text="Dry cough")
    with pytest.raises(ValueError):
        DrugInfo(drug_name="lisinopril", source_ref="mockdrug:lisinopril")
    info = DrugInfo(drug_name="ferrous", source_ref="mockdrug:ferrous", adverse_text="Constipation")
    assert info.matches("Ferrous sulfate")


def test_sick_message_is_patient_originated_and_timezone_aware():
    sent = datetime(2026, 10, 16, 7, 42, tzinfo=TZ)
    msg = SickMessage(MessageId("m1"), PatientId("p1"), sent, "I have a cough")
    assert msg.origin is Origin.PATIENT
    with pytest.raises(ValueError):
        SickMessage(MessageId("m1"), PatientId("p1"), sent.replace(tzinfo=None), "I have a cough")
    with pytest.raises(ValueError):
        SickMessage(MessageId("m1"), PatientId("p1"), sent, "I have a cough", origin=Origin.CHART)
