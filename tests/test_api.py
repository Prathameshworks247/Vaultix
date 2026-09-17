def test_create_payment_requires_api_key(client):
    resp = client.post("/payments", json={"amount": "10.00"})
    assert resp.status_code == 401


def test_create_payment_rejects_bad_api_key(client, merchant):
    resp = client.post("/payments", json={"amount": "10.00"}, headers={"X-API-Key": "wrong"})
    assert resp.status_code == 401


def test_create_payment_rejects_negative_amount(client, auth_headers):
    resp = client.post("/payments", json={"amount": "-5.00"}, headers=auth_headers)
    assert resp.status_code == 422


def test_create_payment_rejects_unsupported_currency(client, auth_headers):
    resp = client.post("/payments", json={"amount": "5.00", "currency": "XYZ"}, headers=auth_headers)
    assert resp.status_code == 422


def test_create_payment_idempotency_key_dedupes(client, auth_headers):
    body = {"amount": "10.00"}
    headers = {**auth_headers, "Idempotency-Key": "dupe-key-1"}

    first = client.post("/payments", json=body, headers=headers)
    second = client.post("/payments", json=body, headers=headers)

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] == second.json()["id"]


def test_idempotency_key_scoped_per_merchant(client, db, auth_headers):
    # A second merchant using the exact same key string must NOT collide with (or see) the
    # first merchant's payment - this is what the (merchant_id, idempotency_key) unique
    # constraint replaced the old bare-unique column for.
    from app.models.payments import Merchant

    other = Merchant(name="Other Merchant", api_key="other-key")
    db.add(other)
    db.commit()

    headers = {"Idempotency-Key": "shared-key"}
    first = client.post("/payments", json={"amount": "10.00"}, headers={**auth_headers, **headers})
    second = client.post("/payments", json={"amount": "20.00"}, headers={"X-API-Key": "other-key", **headers})

    assert first.status_code == 201 and second.status_code == 201
    assert first.json()["id"] != second.json()["id"]


def test_create_payment_idempotency_key_race_no_duplicate(client, auth_headers):
    # Two requests with the same key, fired concurrently, must still settle on one payment
    # row - covers the IntegrityError-on-commit fallback in create_payment, not just the
    # sequential dedupe path above.
    import threading

    body = {"amount": "10.00"}
    headers = {**auth_headers, "Idempotency-Key": "race-key-1"}
    responses = []

    def post():
        responses.append(client.post("/payments", json=body, headers=headers))

    threads = [threading.Thread(target=post) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert all(r.status_code == 201 for r in responses)
    ids = {r.json()["id"] for r in responses}
    assert len(ids) == 1


def test_refund_unknown_payment_404(client, auth_headers):
    resp = client.post("/payments/00000000-0000-0000-0000-000000000000/refund", json={}, headers=auth_headers)
    assert resp.status_code == 404


def test_refund_rejects_non_succeeded_payment(client, auth_headers):
    created = client.post("/payments", json={"amount": "10.00"}, headers=auth_headers)
    payment_id = created.json()["id"]  # freshly created payment is PENDING, not SUCCEEDED

    resp = client.post(f"/payments/{payment_id}/refund", json={}, headers=auth_headers)
    assert resp.status_code == 409


def test_cannot_refund_another_merchants_payment(client, db, auth_headers):
    from app.models.payments import Merchant

    other = Merchant(name="Other Merchant", api_key="other-key")
    db.add(other)
    db.commit()

    created = client.post("/payments", json={"amount": "10.00"}, headers=auth_headers)
    payment_id = created.json()["id"]

    resp = client.post(f"/payments/{payment_id}/refund", json={}, headers={"X-API-Key": "other-key"})
    assert resp.status_code == 404  # not "not eligible" - it isn't even visible to this merchant


def test_webhook_register_and_clear(client, merchant, auth_headers):
    put = client.put(f"/merchants/{merchant.id}/webhook", json={"url": "http://example.com/hook", "secret": "s3cr3t"}, headers=auth_headers)
    assert put.status_code == 200
    assert put.json()["secret"] == "s3cr3t"

    get = client.get(f"/merchants/{merchant.id}/webhook", headers=auth_headers)
    assert get.json()["secret"] is None  # never echoed back after registration

    client.delete(f"/merchants/{merchant.id}/webhook", headers=auth_headers)
    assert client.get(f"/merchants/{merchant.id}/webhook", headers=auth_headers).json()["url"] is None


def test_cannot_register_another_merchants_webhook(client, db, merchant, auth_headers):
    from app.models.payments import Merchant

    other = Merchant(name="Other Merchant", api_key="other-key")
    db.add(other)
    db.commit()

    resp = client.put(f"/merchants/{other.id}/webhook", json={"url": "http://example.com/hook"}, headers=auth_headers)
    assert resp.status_code == 403


def test_create_merchant_issues_api_key(client):
    resp = client.post("/merchants", json={"name": "New Merchant"})
    assert resp.status_code == 201
    body = resp.json()
    assert body["api_key"]


def test_admin_stats_requires_admin_key(client):
    assert client.get("/admin/stats").status_code == 401
    assert client.get("/admin/stats", headers={"X-Admin-Key": "wrong"}).status_code == 401


def test_admin_stats_with_valid_key(client, admin_headers):
    resp = client.get("/admin/stats", headers=admin_headers)
    assert resp.status_code == 200
    assert "total_in_base_currency" in resp.json()["payments"]
