"""
Seed script: hospital needs grounded in publicly documented problems.

Every need here references a real, verifiable source:
- Joint Commission 2024 Sentinel Event Data Report (1,575 events)
- ECRI Top 10 Patient Safety Concerns 2024 and 2025
- Johns Hopkins patient safety research
- CMS Hospital Readmissions Reduction Program data
- ISMP medication safety findings

Run from ProjectElevate directory with server running:
    python seed_needs.py
"""

import asyncio
import httpx

API = "http://localhost:8000/api/v1/needs"

NEEDS = [
    # PATIENT FALLS — Joint Commission #1 sentinel event 2024: 776 events, up 15% from 2023
    {
        "raw_text": "Patient falls are our single biggest sentinel event. We had 14 last quarter, three resulting in serious injury. Fall prevention still depends entirely on nursing vigilance — yellow wristbands and bed alarms that get turned off because they alarm constantly. By the time a nurse responds to an alarm the patient is already on the floor. We need predictive monitoring, not reactive alarms.",
        "submitted_by": "Patient Safety Officer",
        "hospital_id": "Regional Medical Center"
    },
    {
        "raw_text": "Falls from the toilet are our second most common fall type after walking falls per our Joint Commission data. Patients press the call button, wait 8-10 minutes, give up and try to transfer themselves. We don't have adequate staffing to respond quickly. We need either faster response systems or sensors that detect when a high-fall-risk patient is attempting to transfer without assistance.",
        "submitted_by": "Med-Surg Nurse Manager",
        "hospital_id": "Community Hospital"
    },
    {
        "raw_text": "Post-op elderly patients are at extreme fall risk from anesthesia confusion and opioids, yet we manage them the same as every other patient. Our fall risk assessment flags them correctly but the intervention is just a sign on the door. We need continuous monitoring specific to this population — the Joint Commission data shows falls nearly tripled since 2019 and we are part of that trend.",
        "submitted_by": "Orthopedic Surgery NP",
        "hospital_id": "Academic Medical Center"
    },

    # COMMUNICATION / HANDOFFS — Joint Commission: 80% of serious errors involve communication
    {
        "raw_text": "Shift handoffs are where critical information disappears. The outgoing nurse gives a verbal report while the incoming nurse logs in, answers a call light, and tries to take notes simultaneously. Things that matter — a fall risk that increased overnight, a pending result the physician was waiting on, a family concern — don't survive the transition. The Joint Commission attributes 80% of serious errors to communication failures exactly like this.",
        "submitted_by": "ICU Charge Nurse",
        "hospital_id": "Teaching Hospital"
    },
    {
        "raw_text": "Critical lab results fall through the cracks constantly. A potassium of 6.8 or a rising troponin generates a page but there is no loop closure. We have no way to confirm the page was received, that the physician reviewed the result, or that any action was taken. Nurses call back to verify, consuming more time, and sometimes nobody answers. This is the mechanism behind our delay-in-treatment sentinel events.",
        "submitted_by": "Hospitalist Attending",
        "hospital_id": "Community Medical Center"
    },
    {
        "raw_text": "ED to floor transfers are communication failures waiting to happen. The receiving nurse gets a verbal report and a paper printout, often before the ED note is even finalized. She is starting care on a patient she barely knows. We need a structured transfer tool that pulls the past 4 hours of vitals, active medications, pending orders, and any clinical concerns into a single verified document before the patient moves.",
        "submitted_by": "ED Charge Nurse",
        "hospital_id": "Level II Trauma Center"
    },

    # WRONG SURGERY — Joint Commission 2024: 127 events, up 13%
    {
        "raw_text": "Wrong-site surgery is still happening despite universal protocol checklists. The timeout gets rushed — the surgeon is scrubbed in, the team is ready, and the timeout feels like bureaucratic delay. People check boxes without actually verifying. We need a workflow where the timeout cannot be bypassed or retroactively documented. The 13% increase in wrong surgery events in 2024 Joint Commission data is unacceptable.",
        "submitted_by": "OR Safety Coordinator",
        "hospital_id": "Academic Medical Center"
    },
    {
        "raw_text": "Patient identification errors happen weekly. Wrong patient gets a medication, wrong patient gets a procedure, wrong patient's blood gets drawn. Two-identifier verification is required but in practice the nurse says the name and the patient nods — confused patients nod at everything. Barcode scanning helps but compliance is inconsistent, especially nights and weekends when supervision is lower.",
        "submitted_by": "Quality Improvement Director",
        "hospital_id": "Regional Hospital System"
    },

    # DELAY IN TREATMENT — Joint Commission 2024: 126 events, 60% result in death
    {
        "raw_text": "Sepsis is killing patients because recognition happens 6-8 hours too late. Early signs are subtle — mild fever, slight tachycardia, mild confusion. None alone triggers concern. By the time a lactate comes back elevated and someone puts it together the patient is in septic shock. We need a background algorithm that aggregates these signals continuously and flags the patient before anyone thinks to order the sepsis workup.",
        "submitted_by": "Emergency Medicine Attending",
        "hospital_id": "Regional Medical Center"
    },
    {
        "raw_text": "Our door-to-needle time for stroke is 68 minutes against a 60-minute target. The delay is in the handoff from EMS, the CT scanner queue, and reaching neurology by phone. Every minute costs 1.9 million neurons. Pre-hospital notification from EMS that automatically activates the stroke team and reserves the scanner before the patient arrives would close most of this gap.",
        "submitted_by": "Vascular Neurology Attending",
        "hospital_id": "Comprehensive Stroke Center"
    },
    {
        "raw_text": "Floor patients deteriorate and we catch it too late. The rapid response team exists but gets called after the patient is already crashing. Early warning scores like NEWS are supposed to be calculated every shift but nurses calculate them manually and don't update when vitals change between assessments. We need automated EWS that recalculates every time a vital sign is documented.",
        "submitted_by": "Rapid Response Team Lead",
        "hospital_id": "Community Hospital"
    },

    # MEDICATION ERRORS — ECRI #2 concern 2024: barcode workarounds
    {
        "raw_text": "Nurses are scanning the barcode on the medication cabinet instead of the patient wristband before administering. The workaround takes 2 seconds vs the correct scan taking 10 seconds. Everyone knows it is happening and everyone knows why — the correct workflow is slow and the wristband scanner often fails. This completely defeats the barcode medication administration system. ECRI flagged this as a top safety concern and we see it daily.",
        "submitted_by": "Medication Safety Pharmacist",
        "hospital_id": "ISMP-reporting hospital"
    },
    {
        "raw_text": "High-alert medication double-checks exist on paper but are not independent in practice. One nurse prepares the dose and the second nurse signs off without truly verifying — they trust their colleague. We have had near-misses with insulin and anticoagulants. We need a double-check system where the second verifier sees only the patient weight, the ordered dose, and the acceptable range — not what the first nurse calculated.",
        "submitted_by": "ICU Clinical Pharmacist",
        "hospital_id": "Academic Medical Center"
    },

    # DIAGNOSTIC ERRORS — Johns Hopkins 2023: 795,000 deaths or permanent disabilities annually
    {
        "raw_text": "Diagnostic errors are the most underreported patient safety problem we have. When a patient is misdiagnosed, it often surfaces weeks later at a different facility or on readmission — by then the connection to the original encounter is rarely made. Johns Hopkins research estimates 795,000 Americans are killed or permanently disabled by diagnostic errors every year. We have no systematic way to track our own diagnostic accuracy.",
        "submitted_by": "Internal Medicine Attending",
        "hospital_id": "Teaching Hospital"
    },
    {
        "raw_text": "Radiology critical findings are being missed or delayed regularly. When a radiologist identifies a PE or a new mass, they call the ordering physician and the documentation trail ends there. No confirmation the message was received, no escalation if the physician does not respond, no tracking of whether action was taken. We have found cases in our morbidity review where cancer diagnoses sat in radiology reports for weeks before anyone acted.",
        "submitted_by": "Radiology Department Chair",
        "hospital_id": "Academic Medical Center"
    },

    # DISMISSING PATIENT CONCERNS — ECRI #1 safety concern 2025: 55% of dismissed patients worsened
    {
        "raw_text": "ECRI named dismissing patient and family concerns the number one patient safety threat for 2025. Their data shows 55% of patients whose concerns were dismissed had worsened outcomes. We see this in our own adverse event reviews — patients who reported pain or symptoms that were minimized and later found to have serious pathology. We have no structured mechanism for a patient to escalate a concern that staff have not addressed.",
        "submitted_by": "Chief Medical Officer",
        "hospital_id": "Regional Health System"
    },

    # HOSPITAL READMISSIONS — CMS HRRP penalizes hospitals for excess readmissions
    {
        "raw_text": "We are being penalized by CMS for excess heart failure readmissions. These patients leave without truly understanding fluid restriction, stop diuretics when they feel better, gain 5 kilograms in a week, and come back in crisis. Remote daily weight monitoring with an automatic alert at 2kg gain in 48 hours would identify these patients during the compensated phase before they decompensate. The technology is commercially available, the care model is not in place.",
        "submitted_by": "Heart Failure Program Director",
        "hospital_id": "Heart Failure Center"
    },
    {
        "raw_text": "COPD readmissions are driven by exacerbations that patients manage at home until they cannot breathe, then call 911. If we had remote monitoring of oxygen saturation and respiratory rate we could intervene during the early exacerbation phase and prevent the hospitalization. CMS is penalizing us for readmission rates we could reduce with a remote monitoring program we currently do not have.",
        "submitted_by": "Pulmonology Attending",
        "hospital_id": "Regional Medical Center"
    },
    {
        "raw_text": "Discharge instructions are handed to patients who are exhausted, in pain, and on medications that affect cognition. Research shows patients retain almost nothing from verbal discharge teaching. We give them a 12-page document and tell them to follow up in a week. The ones who do not understand their instructions and do not make follow-up appointments are exactly the ones who come back to the ED.",
        "submitted_by": "Discharge Planning Nurse",
        "hospital_id": "Community Hospital"
    },

    # ALARM FATIGUE — Johns Hopkins nursing leadership: "a national problem"
    {
        "raw_text": "Alarm fatigue is a patient safety emergency. We generate 40 to 50 alarms per ICU patient per day and more than 95% are false positives. Nurses have become desensitized — they do not look up when an alarm fires. Johns Hopkins nursing leadership has publicly called this a national problem. When a real desaturation or a real arrhythmia fires, it is treated the same as the 49 that were nothing. We need AI-based alarm triage, not more audits.",
        "submitted_by": "ICU Medical Director",
        "hospital_id": "Johns Hopkins-affiliated hospital"
    },

    # MATERNAL SAFETY — ECRI: 1 in 3 counties are maternity care deserts
    {
        "raw_text": "We are a rural hospital and one of the only delivery facilities within 90 miles. We do not have 24-hour OB coverage on site. For a postpartum hemorrhage or shoulder dystocia, our on-call physician is 20 minutes away. Twenty minutes is fatal in those emergencies. We need telemedicine connection to a tertiary obstetric center that can guide our nursing staff in real time during an obstetric emergency — ECRI data shows 1 in 3 counties are now maternity care deserts.",
        "submitted_by": "Rural Hospital CNO",
        "hospital_id": "Critical Access Hospital"
    },

    # INPATIENT SUICIDE — Joint Commission 2024: 122 events
    {
        "raw_text": "We had two inpatient suicides in 18 months, both on suicide precautions. In both cases the staff believed the patient was sleeping. Continuous observation requires a staff member outside every door — a model we cannot sustain with current staffing. The Joint Commission reported 122 inpatient suicide events in 2024. We need a monitoring technology that provides true continuous observation without requiring one-to-one staffing.",
        "submitted_by": "Behavioral Health Medical Director",
        "hospital_id": "Inpatient Psychiatric Unit"
    },
    {
        "raw_text": "Post-discharge suicide risk peaks in the first 30 days after psychiatric hospitalization. We discharge patients with an outpatient appointment scheduled two weeks out and nothing in between. No daily check-in, no safety monitoring, no way to know if they are deteriorating. This is the highest-risk period and we are completely blind to it.",
        "submitted_by": "Inpatient Psychiatry Attending",
        "hospital_id": "Behavioral Health Center"
    },

    # HEALTHCARE ASSOCIATED INFECTIONS
    {
        "raw_text": "Central line infections are preventable but we still have them. The bundle requires cap, gown, sterile drape, chlorhexidine prep — but when a resident inserts a line at 2am with an unstable patient, steps get skipped. Compliance is audited retrospectively after the infection has already occurred. We need real-time checklist tracking at the bedside during line insertion, not a chart review three days later.",
        "submitted_by": "Infection Prevention Specialist",
        "hospital_id": "Academic Medical Center"
    },
    {
        "raw_text": "Foley catheters stay in longer than clinically necessary because nobody removes them. The physician does not remember the catheter is there, the nurse does not prompt for removal, and the catheter stays for days past its indication. Catheter-associated UTIs are our most common hospital-acquired infection and almost entirely preventable. An automatic day 2 reminder asking whether the catheter is still indicated would cut our CAUTI rate significantly.",
        "submitted_by": "Urology NP",
        "hospital_id": "Community Hospital"
    },

    # SOCIAL DETERMINANTS / HEALTH EQUITY
    {
        "raw_text": "We screen patients for food insecurity, housing instability, and transportation barriers — and then nothing happens. The positive screens go into a field in the EHR that nobody reads. We have no closed-loop referral to community resources and no follow-up to confirm the patient received help. Screening without action may actually harm patients by creating the impression we addressed their social needs when we did not.",
        "submitted_by": "Community Health Navigator",
        "hospital_id": "Safety Net Hospital"
    },
    {
        "raw_text": "Language barriers are a direct patient safety issue. We serve a large non-English-speaking population but interpretation services are only reliably available business hours. At night and weekends, clinical staff use family members including children to interpret complex medical situations. Informed consent obtained through a family interpreter is ethically and legally problematic, and the accuracy of clinical information transfer is unreliable.",
        "submitted_by": "Patient Rights Advocate",
        "hospital_id": "Urban Safety Net Hospital"
    },
]


async def seed():
    async with httpx.AsyncClient(timeout=90.0) as client:
        succeeded = 0
        failed = 0
        for i, need in enumerate(NEEDS, 1):
            try:
                res = await client.post(API, json=need)
                if res.status_code == 201:
                    data = res.json()
                    print(f"[{i:02d}/{len(NEEDS)}] ✓  {data['department']:20s} | {data['category']:15s} | urgency {data['urgency_score']}/5")
                    succeeded += 1
                else:
                    print(f"[{i:02d}/{len(NEEDS)}] ✗  HTTP {res.status_code}: {res.text[:120]}")
                    failed += 1
            except Exception as e:
                print(f"[{i:02d}/{len(NEEDS)}] ✗  Error: {e}")
                failed += 1
            await asyncio.sleep(0.8)

        print(f"\n{'='*60}")
        print(f"Seeding complete: {succeeded} inserted, {failed} failed")
        print(f"\nData sources:")
        print(f"  Joint Commission 2024 Sentinel Event Report (1,575 events)")
        print(f"  ECRI Top 10 Patient Safety Concerns 2024 + 2025")
        print(f"  Johns Hopkins: 795,000 diagnostic error deaths/yr")
        print(f"  CMS Hospital Readmissions Reduction Program")
        print(f"  ISMP medication safety data")


if __name__ == "__main__":
    asyncio.run(seed())
