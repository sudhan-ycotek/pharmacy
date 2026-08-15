import pytest

from vendors import add_vendor, get_vendor, list_vendors, search_vendors


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
