import pytest

from vendors import add_vendor, get_vendor, list_vendors


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


def test_list_vendors_view_shows_vendors(admin_client, app):
    with app.app_context():
        add_vendor("ABC Vendors", "9800000000")
    resp = admin_client.get("/vendors")
    assert resp.status_code == 200
    assert b"ABC Vendors" in resp.data


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
