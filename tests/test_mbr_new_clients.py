"""MBR new-business clients: retainers are won clients and count (Jason, Oct 2026)."""
from shared import mbr

U = "u1"


def placement(client, *, retainer=False, nb=True, cro=U, start="2026-04-20"):
    return {"_crimson_clientname_value": client, "crimson_startdate": start,
            "crimson_specialinstructionsclient": "New Business" if nb else "",
            "_mercury_clientrelationshipowner_value": cro, "_crimson_consultant_value": U,
            "_mercury_assignmentowner_value": U, "recruit_truegrossprofit": 10000.0,
            "_recruit_candidatecontact_value": mbr.RETAINER_CONTACT if retainer else "cand"}


def test_a_retainer_counts_as_a_new_business_client_but_not_as_gp(monkeypatch):
    rows = [placement("retained", retainer=True), placement("normal"),
            placement("not-nb", nb=False), placement("someone-elses", cro="other")]
    monkeypatch.setattr(mbr, "_placements", lambda uid, s, e: rows)
    monkeypatch.setattr(mbr, "_placements_created", lambda uid, s, e: [])
    out = mbr.compute_ytd_headline(U, 2026, 9, {"GBP": 1.0})
    assert out["new_clients"] == 2                     # retained + normal
    rows.pop(0)                                        # the same, without the retainer
    without = mbr.compute_ytd_headline(U, 2026, 9, {"GBP": 1.0})
    assert out["revenue"] == without["revenue"]        # its fee stays out of GP
    assert out["deals"] == without["deals"]
