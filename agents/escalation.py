"""Escalation node — hands off to a human, no LLM call needed."""

ESCALATION_MESSAGE = (
    "I'll connect you with our team right away. You can reach PRO FX directly at "
    "sales@profx.com or +91 88843 10123 (Bengaluru HQ), or share your city and I'll "
    "point you to your nearest branch — we're also in Chennai, Coimbatore, Hyderabad, "
    "Kochi, and Mysuru."
)


def escalation_node(state):
    return {"answer": ESCALATION_MESSAGE}
