"""Blank e-way transporter names must be rejected (#814 follow-up)."""


def test_transporter_name_rejects_blank_or_whitespace(client, db, company):
    """Spaces-only names must not create or overwrite a transporter."""
    for content in ("", "   ", "\t"):
        resp = client.post("/api/eway-bill/transporters", json={"transporter_name": content})
        assert resp.status_code == 422, resp.text
    assert client.get("/api/eway-bill/transporters").json() == []

    created = client.post(
        "/api/eway-bill/transporters",
        json={"transporter_name": "  Keep Me  "},
    )
    assert created.status_code == 200, created.text
    assert created.json()["transporter_name"] == "Keep Me"
    transporter_id = created.json()["id"]

    for content in ("", "   "):
        resp = client.put(
            f"/api/eway-bill/transporters/{transporter_id}",
            json={"transporter_name": content},
        )
        assert resp.status_code == 422, resp.text
    still = client.get("/api/eway-bill/transporters").json()
    assert len(still) == 1
    assert still[0]["transporter_name"] == "Keep Me"
