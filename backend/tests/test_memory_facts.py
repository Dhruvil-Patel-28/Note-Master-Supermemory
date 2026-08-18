"""Pure-logic tests for the supermemory fact extractors (no LLM, no network)."""

from app.memory.facts import (
    _institute,
    _resume_name,
    facts_for_capture,
    resume_facts,
    transcript_facts,
)

TRANSCRIPT = (
    "Digitally signed on 12/08/2025\tIndian\tInstitute\tOf\tInformation\tTechnology,\tNagpur\t"
    "TRANSCRIPT BACHELOR OF TECHNOLOGY (CSE) 2026 2023-2027 "
    "Regn. No.(Enrol. No.) BT23CSE129 Name DHRUVIL GIRISHKUMAR PATEL "
    "College/Deptt COMPUTER SCIENCE AND ENGINEERING "
    "I MAL103 CALCULUS FOR ENGINEERS AB 4 BEL102 ELEMENTS OF ELECTRICAL ENGINEERING BC 4 "
    "CSL101 PROGRAMMING FOR PROBLEM SOLVING AB 4 "
    "II MAL104 DIFFERENTIAL EQUATIONS BC 4 CSL102 DATA STRUCTURES AND ALGORITHMS AB 4 "
    "Grand Total Credit : 122 CGPA : 7.57"
)

RESUME = (
    "Dhruvil Patel\n"
    "dhruvil.patel@gmail.com | +91 9665693997\n"
    "EDUCATION\n"
    "Indian Institute of Information T echnology (IIIT), Nagpur | B.Tech CSE | CGPA: 7.57 / 10\n"
    "PROJECTS\n"
    "Note Master — local-first memory app\n"
    "SKILLS\n"
    "Python, FastAPI, SQLite, React"
)


def test_transcript_institute():
    facts = transcript_facts(TRANSCRIPT)
    assert any("Indian Institute Of Information Technology, Nagpur" in f for f in facts)


def test_transcript_semester_courses():
    facts = transcript_facts(TRANSCRIPT)
    sem1 = [f for f in facts if "1st semester" in f]
    assert sem1
    assert "MAL103 CALCULUS FOR ENGINEERS" in sem1[0]
    assert "BEL102 ELEMENTS OF ELECTRICAL ENGINEERING" in sem1[0]


def test_transcript_credits_and_cgpa():
    facts = transcript_facts(TRANSCRIPT)
    assert any("122 credits" in f for f in facts)
    assert any("7.57" in f for f in facts)


def test_resume_facts():
    facts = resume_facts(RESUME)
    text = "\n".join(facts)
    assert "Dhruvil Patel" in text
    assert "dhruvil.patel@gmail.com" in text
    assert "9665693997" in text
    assert "Indian Institute of Information T echnology" in text
    assert "7.57" in text


def test_resume_name_skips_headers():
    assert _resume_name("EDUCATION\nDhruvil Patel\n") == "Dhruvil Patel"


def test_institute_widens_around_keyword():
    assert _institute("line before\nIndian Institute of Technology, Bombay | B.Tech\nline after")
    assert _institute("just random shopping list text with no keywords") is None


def test_doc_facts_routing():
    assert facts_for_capture("doc", TRANSCRIPT) == transcript_facts(TRANSCRIPT)
    assert facts_for_capture("doc", RESUME) == resume_facts(RESUME)
    assert facts_for_capture("doc", "receipt from kirana store for 250 rupees") == []


def test_note_facts_offline_is_empty():
    assert facts_for_capture("text", "") == []