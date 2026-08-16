import pytest

from companies import (
    add_company,
    edit_company,
    get_company,
    get_company_vendors,
    list_companies,
    search_companies,
    set_company_vendors,
)


def test_add_company_creates_and_returns_id(app):
    with app.app_context():
        company_id = add_company("ABC Pharma", "9800000000", "Kathmandu")
        company = get_company(company_id)
        assert company["name"] == "ABC Pharma"
        assert company["phone"] == "9800000000"
        assert company["address"] == "Kathmandu"


def test_add_company_requires_non_empty_name(app):
    with app.app_context():
        with pytest.raises(ValueError):
            add_company("   ")


def test_add_company_rejects_duplicate_name(app):
    with app.app_context():
        add_company("ABC Pharma")
        with pytest.raises(ValueError):
            add_company("ABC Pharma")


def test_add_company_phone_and_address_are_optional(app):
    with app.app_context():
        company_id = add_company("XYZ Labs")
        company = get_company(company_id)
        assert company["phone"] is None
        assert company["address"] is None


def test_add_company_assigns_sequential_zero_padded_codes(app):
    with app.app_context():
        id1 = add_company("Alpha Pharma")
        id2 = add_company("Beta Pharma")
        assert get_company(id1)["code"] == "001"
        assert get_company(id2)["code"] == "002"


def test_add_company_code_overflows_from_999_to_1000_rather_than_blocking(app):
    with app.app_context():
        from db import get_db

        db = get_db()
        db.execute("INSERT INTO companies (code, name) VALUES (?, ?)", ("999", "Company 999"))
        db.commit()
        company_id = add_company("Company 1000")
        assert get_company(company_id)["code"] == "1000"


def test_list_companies_returns_all_ordered_by_name(app):
    with app.app_context():
        add_company("Zenith Pharma")
        add_company("ABC Pharma")
        names = [c["name"] for c in list_companies()]
        assert names == ["ABC Pharma", "Zenith Pharma"]


def test_get_company_returns_none_for_unknown_id(app):
    with app.app_context():
        assert get_company(999) is None


def test_search_companies_matches_by_name(app):
    with app.app_context():
        add_company("Cipla Nepal")
        add_company("Square Pharma")
        results = search_companies("cipla")
        assert len(results) == 1
        assert results[0]["name"] == "Cipla Nepal"


def test_search_companies_view_returns_matches_json(admin_client, app):
    with app.app_context():
        add_company("Cipla Nepal")
        add_company("Square Pharma")
    resp = admin_client.get("/companies/search?q=square")
    assert resp.status_code == 200
    data = resp.get_json()
    assert len(data) == 1
    assert data[0]["name"] == "Square Pharma"


def test_search_companies_view_requires_admin(staff_client):
    resp = staff_client.get("/companies/search?q=a")
    assert resp.status_code == 403


def test_add_company_view_creates_company_via_json(admin_client):
    resp = admin_client.post("/companies", json={"name": "New Company", "phone": "111"})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["name"] == "New Company"
    assert "id" in data
    assert data["code"] == "001"


def test_add_company_view_rejects_duplicate_name(admin_client, app):
    with app.app_context():
        add_company("ABC Pharma")
    resp = admin_client.post("/companies", json={"name": "ABC Pharma"})
    assert resp.status_code == 400
    assert "error" in resp.get_json()


def test_add_company_view_requires_admin(staff_client):
    resp = staff_client.post("/companies", json={"name": "New Company"})
    assert resp.status_code == 403


def test_add_company_stores_contact_person(app):
    with app.app_context():
        company_id = add_company("ABC Pharma", contact_person="Ram Sharma")
        assert get_company(company_id)["contact_person"] == "Ram Sharma"


def test_add_company_contact_person_is_optional(app):
    with app.app_context():
        company_id = add_company("ABC Pharma")
        assert get_company(company_id)["contact_person"] is None


def test_edit_company_updates_fields(app):
    with app.app_context():
        company_id = add_company("ABC Pharma", "111", "Ktm")
        edit_company(company_id, "ABC Pharma Renamed", phone="222", address="Pokhara",
                     contact_person="Hari Thapa")
        company = get_company(company_id)
        assert company["name"] == "ABC Pharma Renamed"
        assert company["phone"] == "222"
        assert company["address"] == "Pokhara"
        assert company["contact_person"] == "Hari Thapa"


def test_edit_company_keeps_code_unchanged(app):
    with app.app_context():
        company_id = add_company("ABC Pharma")
        code_before = get_company(company_id)["code"]
        edit_company(company_id, "ABC Pharma Renamed")
        assert get_company(company_id)["code"] == code_before


def test_edit_company_raises_for_unknown_company(app):
    with app.app_context():
        with pytest.raises(ValueError):
            edit_company(999, "Nope")


def test_set_company_vendors_links_vendors_to_company(app):
    with app.app_context():
        from vendors import add_vendor

        company_id = add_company("ABC Pharma")
        vendor1 = add_vendor("Vendor One")
        vendor2 = add_vendor("Vendor Two")
        set_company_vendors(company_id, [vendor1, vendor2])
        linked = {v["id"] for v in get_company_vendors(company_id)}
        assert linked == {vendor1, vendor2}


def test_set_company_vendors_replaces_previous_links(app):
    with app.app_context():
        from vendors import add_vendor

        company_id = add_company("ABC Pharma")
        vendor1 = add_vendor("Vendor One")
        vendor2 = add_vendor("Vendor Two")
        set_company_vendors(company_id, [vendor1])
        set_company_vendors(company_id, [vendor2])
        linked = {v["id"] for v in get_company_vendors(company_id)}
        assert linked == {vendor2}


def test_set_company_vendors_empty_list_clears_links(app):
    with app.app_context():
        from vendors import add_vendor

        company_id = add_company("ABC Pharma")
        vendor1 = add_vendor("Vendor One")
        set_company_vendors(company_id, [vendor1])
        set_company_vendors(company_id, [])
        assert get_company_vendors(company_id) == []


def test_set_company_vendors_rejects_unknown_vendor_id(app):
    with app.app_context():
        company_id = add_company("ABC Pharma")
        with pytest.raises(ValueError):
            set_company_vendors(company_id, [999])


def test_get_company_vendors_empty_for_unlinked_company(app):
    with app.app_context():
        company_id = add_company("ABC Pharma")
        assert get_company_vendors(company_id) == []


def test_list_companies_view_shows_companies(admin_client, app):
    with app.app_context():
        add_company("ABC Pharma")
    resp = admin_client.get("/companies")
    assert resp.status_code == 200
    assert b"ABC Pharma" in resp.data


def test_list_companies_view_requires_admin(staff_client):
    resp = staff_client.get("/companies")
    assert resp.status_code == 403


def test_add_company_form_view_get_renders_form(admin_client):
    resp = admin_client.get("/companies/add")
    assert resp.status_code == 200
    assert b"Contact Person" in resp.data


def test_add_company_form_view_requires_admin(staff_client):
    resp = staff_client.get("/companies/add")
    assert resp.status_code == 403


def test_add_company_form_view_post_creates_company_with_vendors(admin_client, app):
    with app.app_context():
        from vendors import add_vendor
        vendor_id = add_vendor("Vendor One")
    resp = admin_client.post("/companies/add", data={
        "name": "New Company", "phone": "123", "address": "Ktm",
        "contact_person": "Ram Sharma", "vendor_ids": [str(vendor_id)],
    })
    assert resp.status_code == 302
    with app.app_context():
        companies = list_companies()
        company = next(c for c in companies if c["name"] == "New Company")
        assert company["contact_person"] == "Ram Sharma"
        linked = {v["id"] for v in get_company_vendors(company["id"])}
        assert linked == {vendor_id}


def test_edit_company_view_get_renders_form(admin_client, app):
    with app.app_context():
        company_id = add_company("ABC Pharma")
    resp = admin_client.get(f"/companies/{company_id}/edit")
    assert resp.status_code == 200


def test_edit_company_view_get_404_for_unknown_company(admin_client):
    resp = admin_client.get("/companies/999/edit")
    assert resp.status_code == 404


def test_edit_company_view_requires_admin(staff_client, app):
    with app.app_context():
        company_id = add_company("ABC Pharma")
    resp = staff_client.get(f"/companies/{company_id}/edit")
    assert resp.status_code == 403


def test_edit_company_view_post_updates_company_and_vendors(admin_client, app):
    with app.app_context():
        from vendors import add_vendor
        company_id = add_company("ABC Pharma")
        vendor_id = add_vendor("Vendor One")
    resp = admin_client.post(f"/companies/{company_id}/edit", data={
        "name": "Renamed Pharma", "phone": "999", "address": "Pokhara",
        "contact_person": "Hari Thapa", "vendor_ids": [str(vendor_id)],
    })
    assert resp.status_code == 302
    with app.app_context():
        company = get_company(company_id)
        assert company["name"] == "Renamed Pharma"
        assert company["contact_person"] == "Hari Thapa"
        linked = {v["id"] for v in get_company_vendors(company_id)}
        assert linked == {vendor_id}
