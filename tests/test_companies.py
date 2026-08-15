import pytest

from companies import add_company, get_company, list_companies, search_companies


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
