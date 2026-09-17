def test_create_payment_unknown_merchant_400(client):
    resp = client.post("/payments", json={"merchant_id": "00000000-0000-0000-0000-000000000000", "amount": "10.00"})
    assert resp.status_code == 400


def test_create_payment_rejects_negative_amount(client, merchant):
    resp = client.post("/payments", json={"merchant_id": str(merchant.id), "amount": "-5.00"})
    assert resp.status_code == 422


def test_create_payment_rejects_unsupported_currency(client, merchant):
    resp = client.post("/payments", json={"merchant_id": str(merchant.id), "amount": "5.00", "currency": "XYZ"})
    assert resp.status_code == 422


def test_create_payment_idempotency_key_dedupes(client, merchant):
    body = {"merchant_id": str(merchant.id), "amount": "10.00"}
    headers = {"Idempotency-Key": "dupe-key-1"}

    first = client.post("/payments", json=body, headers=headers)
    second = client.post("/payments", json=body, headers=headers)

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] == second.json()["id"]


def test_create_payment_idempotency_key_race_no_duplicate(client, merchant):
    # Two requests with the same key, fired concurrently, must still settle on one payment
    # row - covers the IntegrityError-on-commit fallback in create_payment, not just the
    # sequential dedupe path above.
    import threading

    body = {"merchant_id": str(merchant.id), "amount": "10.00"}
    headers = {"Idempotency-Key": "race-key-1"}
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


def test_refund_unknown_payment_404(client):
    resp = client.post("/payments/00000000-0000-0000-0000-000000000000/refund", json={})
    assert resp.status_code == 404


def test_refund_rejects_non_succeeded_payment(client, merchant):
    created = client.post("/payments", json={"merchant_id": str(merchant.id), "amount": "10.00"})
    payment_id = created.json()["id"]  # freshly created payment is PENDING, not SUCCEEDED

    resp = client.post(f"/payments/{payment_id}/refund", json={})
    assert resp.status_code == 409


def test_webhook_register_and_clear(client, merchant):
    put = client.put(f"/merchants/{merchant.id}/webhook", json={"url": "http://example.com/hook", "secret": "s3cr3t"})
    assert put.status_code == 200
    assert put.json()["secret"] == "s3cr3t"

    get = client.get(f"/merchants/{merchant.id}/webhook")
    assert get.json()["secret"] is None  # never echoed back after registration

    client.delete(f"/merchants/{merchant.id}/webhook")
    assert client.get(f"/merchants/{merchant.id}/webhook").json()["url"] is None
