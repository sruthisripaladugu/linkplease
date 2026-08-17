import pytest
from app.db import get_matching_rules


@pytest.mark.asyncio
async def test_create_rule_success(client):
    response = await client.post("/rules", json={
        "keyword": "PRICE",
        "dm_message": "Here is the price list: $99/mo"
    })
    assert response.status_code == 201
    data = response.json()
    assert "rule_id" in data
    assert data["keyword"] == "PRICE"
    assert data["dm_message"] == "Here is the price list: $99/mo"


@pytest.mark.asyncio
async def test_create_rule_empty_keyword(client):
    response = await client.post("/rules", json={
        "keyword": "",
        "dm_message": "Some message"
    })
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_matching_rules_case_insensitive(client, temp_db):
    await client.post("/rules", json={"keyword": "PRICE", "dm_message": "Price list"})
    await client.post("/rules", json={"keyword": "DISCOUNT", "dm_message": "Discount code"})

    # Check case-insensitive match
    matches = await get_matching_rules("can you give me the price please?", db_path=temp_db)
    assert len(matches) == 1
    assert matches[0].keyword == "PRICE"

    # Check multiple keywords
    matches2 = await get_matching_rules("I want a PRICE and DISCOUNT", db_path=temp_db)
    assert len(matches2) == 2

    # Check non-matching
    matches3 = await get_matching_rules("Nice post!", db_path=temp_db)
    assert len(matches3) == 0
