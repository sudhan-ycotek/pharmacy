import pytest

from vendors import add_vendor, edit_vendor, get_vendor, list_vendors, search_vendors


def test_add_vendor_creates_and_returns_id(app):
    with app.app_context():
        vendor_id = add_vendor("ABC Vendors", "9800000000", "Kathmandu")
        vendor = get_vendor(vendor_id)
        assert vendor["name"] == "ABC Vendors"
        assert vendor["phone"] == "9800000000"
        assert vendor["address"] == "Kathmandu"


def test_add_vendor_requires_non_empty_name(app):
    with app.app_context():
        with pytest.raises(ValueError):
            add_vendor("   ")


def test_add_vendor_rejects_duplicate_name(app):
    with app.app_context():
        add_vendor("ABC Vendors")
        with pytest.raises(ValueError):
            add_vendor("ABC Vendors")


def test_add_vendor_phone_and_address_are_optional(app):
    with app.app_context():
        vendor_id = add_vendor("XYZ Traders")
        vendor = get_vendor(vendor_id)
        assert vendor["phone"] is None
        assert vendor["address"] is None


def test_list_vendors_returns_all_ordered_by_name(app):
    with app.app_context():
        add_vendor("Zenith Pharma")
        add_vendor("ABC Vendors")
        names = [v["name"] for v in list_vendors()]
        assert names == ["ABC Vendors", "Zenith Pharma"]


def test_get_vendor_returns_none_for_unknown_id(app):
    with app.app_context():
        assert get_vendor(999) is None


def test_add_vendor_assigns_sequential_sup_codes(app):
    with app.app_context():
        id1 = add_vendor("Alpha Distributors")
        id2 = add_vendor("Beta Distributors")
        assert get_vendor(id1)["code"] == "SUP-0001"
        assert get_vendor(id2)["code"] == "SUP-0002"


def test_add_vendor_code_overflows_past_9999_rather_than_blocking(app):
    with app.app_context():
        from db import get_db

        db = get_db()
        db.execute("INSERT INTO vendors (name, code) VALUES (?, ?)", ("Vendor 9999", "SUP-9999"))
        db.commit()
        vendor_id = add_vendor("Vendor 10000")
        assert get_vendor(vendor_id)["code"] == "SUP-10000"


def test_search_vendors_matches_by_name(app):
    with app.app_context():
        add_vendor("Cipla Distributors")
        add_vendor("Square Traders")
        results = search_vendors("cipla")
        assert len(results) == 1
        assert results[0]["name"] == "Cipla Distributors"


def test_search_vendors_matches_by_code(app):
    with app.app_context():
        vendor_id = add_vendor("Cipla Distributors")
        code = get_vendor(vendor_id)["code"]
        results = search_vendors(code)
        assert len(results) == 1
        assert results[0]["id"] == vendor_id


def test_search_vendors_view_returns_matches_json(admin_client, app):
    with app.app_context():
        add_vendor("Cipla Distributors")
        add_vendor("Square Traders")
    resp = admin_client.get("/vendors/search?q=square")
    assert resp.status_code == 200
    data = resp.get_json()
    assert len(data) == 1
    assert data[0]["name"] == "Square Traders"


def test_search_vendors_view_requires_admin(staff_client):
    resp = staff_client.get("/vendors/search?q=a")
    assert resp.status_code == 403


def test_list_vendors_view_shows_vendors(admin_client, app):
    with app.app_context():
        add_vendor("ABC Vendors", "9800000000")
    resp = admin_client.get("/vendors")
    assert resp.status_code == 200
    assert b"ABC Vendors" in resp.data


def test_list_vendors_view_shows_code_column(admin_client, app):
    with app.app_context():
        vendor_id = add_vendor("ABC Vendors")
        code = get_vendor(vendor_id)["code"]
    resp = admin_client.get("/vendors")
    assert resp.status_code == 200
    assert code.encode() in resp.data


def test_list_vendors_view_filters_by_query(admin_client, app):
    with app.app_context():
        add_vendor("ABC Vendors")
        add_vendor("Zenith Pharma")
    resp = admin_client.get("/vendors?q=zenith")
    assert resp.status_code == 200
    assert b"Zenith Pharma" in resp.data
    assert b"ABC Vendors" not in resp.data


def test_list_vendors_view_requires_admin(staff_client):
    resp = staff_client.get("/vendors")
    assert resp.status_code == 403


def test_add_vendor_view_creates_vendor_via_json(admin_client):
    resp = admin_client.post("/vendors", json={"name": "New Vendor", "phone": "111"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["name"] == "New Vendor"
    assert "id" in data


def test_add_vendor_view_rejects_duplicate_name(admin_client, app):
    with app.app_context():
        add_vendor("ABC Vendors")
    resp = admin_client.post("/vendors", json={"name": "ABC Vendors"})
    assert resp.status_code == 400
    assert "error" in resp.get_json()


def test_vendor_detail_view_shows_vendor_and_balance(admin_client, app):
    with app.app_context():
        vendor_id = add_vendor("ABC Vendors")
    resp = admin_client.get(f"/vendors/{vendor_id}")
    assert resp.status_code == 200
    assert b"ABC Vendors" in resp.data


def test_vendor_detail_view_404_for_unknown_vendor(admin_client):
    resp = admin_client.get("/vendors/999")
    assert resp.status_code == 404


def test_add_vendor_stores_email_pan_bank_and_pay_mode(app):
    with app.app_context():
        vendor_id = add_vendor(
            "ABC Vendors", phone="9800000000", address="Kathmandu",
            email="abc@vendors.com", pan_number="123456789",
            bank_account_number="00112233", pay_mode="bank_transfer",
        )
        vendor = get_vendor(vendor_id)
        assert vendor["email"] == "abc@vendors.com"
        assert vendor["pan_number"] == "123456789"
        assert vendor["bank_account_number"] == "00112233"
        assert vendor["pay_mode"] == "bank_transfer"


def test_add_vendor_new_fields_are_optional(app):
    with app.app_context():
        vendor_id = add_vendor("XYZ Traders")
        vendor = get_vendor(vendor_id)
        assert vendor["email"] is None
        assert vendor["pan_number"] is None
        assert vendor["bank_account_number"] is None
        assert vendor["pay_mode"] is None


def test_add_vendor_rejects_invalid_pay_mode(app):
    with app.app_context():
        with pytest.raises(ValueError):
            add_vendor("ABC Vendors", pay_mode="crypto")


def test_edit_vendor_updates_fields(app):
    with app.app_context():
        vendor_id = add_vendor("ABC Vendors", phone="111")
        edit_vendor(
            vendor_id, "ABC Vendors Renamed", phone="222", address="Pokhara",
            email="new@vendors.com", pan_number="999", bank_account_number="555",
            pay_mode="cheque",
        )
        vendor = get_vendor(vendor_id)
        assert vendor["name"] == "ABC Vendors Renamed"
        assert vendor["phone"] == "222"
        assert vendor["address"] == "Pokhara"
        assert vendor["email"] == "new@vendors.com"
        assert vendor["pan_number"] == "999"
        assert vendor["bank_account_number"] == "555"
        assert vendor["pay_mode"] == "cheque"


def test_edit_vendor_keeps_code_unchanged(app):
    with app.app_context():
        vendor_id = add_vendor("ABC Vendors")
        code_before = get_vendor(vendor_id)["code"]
        edit_vendor(vendor_id, "ABC Vendors Renamed")
        assert get_vendor(vendor_id)["code"] == code_before


def test_edit_vendor_raises_for_unknown_vendor(app):
    with app.app_context():
        with pytest.raises(ValueError):
            edit_vendor(999, "Nope")


def test_edit_vendor_rejects_invalid_pay_mode(app):
    with app.app_context():
        vendor_id = add_vendor("ABC Vendors")
        with pytest.raises(ValueError):
            edit_vendor(vendor_id, "ABC Vendors", pay_mode="crypto")


def test_add_vendor_form_view_get_renders_form(admin_client):
    resp = admin_client.get("/vendors/add")
    assert resp.status_code == 200
    assert b"Pay Mode" in resp.data


def test_add_vendor_form_view_requires_admin(staff_client):
    resp = staff_client.get("/vendors/add")
    assert resp.status_code == 403


def test_add_vendor_form_view_post_creates_vendor_and_redirects(admin_client, app):
    resp = admin_client.post("/vendors/add", data={
        "name": "New Vendor", "phone": "123", "address": "Ktm",
        "email": "a@b.com", "pan_number": "PAN1", "bank_account_number": "ACC1",
        "pay_mode": "cash",
    })
    assert resp.status_code == 302
    with app.app_context():
        vendors = list_vendors()
        assert any(v["name"] == "New Vendor" and v["email"] == "a@b.com" for v in vendors)


def test_edit_vendor_view_get_renders_form(admin_client, app):
    with app.app_context():
        vendor_id = add_vendor("ABC Vendors")
    resp = admin_client.get(f"/vendors/{vendor_id}/edit")
    assert resp.status_code == 200


def test_edit_vendor_view_get_404_for_unknown_vendor(admin_client):
    resp = admin_client.get("/vendors/999/edit")
    assert resp.status_code == 404


def test_edit_vendor_view_requires_admin(staff_client, app):
    with app.app_context():
        vendor_id = add_vendor("ABC Vendors")
    resp = staff_client.get(f"/vendors/{vendor_id}/edit")
    assert resp.status_code == 403


def test_edit_vendor_view_post_updates_vendor(admin_client, app):
    with app.app_context():
        vendor_id = add_vendor("ABC Vendors")
    resp = admin_client.post(f"/vendors/{vendor_id}/edit", data={
        "name": "Renamed Vendor", "phone": "999", "address": "Pokhara",
        "email": "x@y.com", "pan_number": "PAN2", "bank_account_number": "ACC2",
        "pay_mode": "digital_wallet",
    })
    assert resp.status_code == 302
    with app.app_context():
        vendor = get_vendor(vendor_id)
        assert vendor["name"] == "Renamed Vendor"
        assert vendor["pay_mode"] == "digital_wallet"
