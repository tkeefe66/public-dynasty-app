from app.models.rating_scope import RatingScope


def test_provisional_scope_serializes_coverage():
    # Mutation: reject provisional status or drop coverage fields from the API model.
    scope = RatingScope(
        status="provisional",
        basis="season_end",
        label="Provisional franchise rating",
        included_seasons=[2022, 2024],
        excluded_seasons=[{"season": 2023, "reason": "Standings unresolved."}],
    )
    assert scope.model_dump()["included_seasons"] == [2022, 2024]
    assert scope.model_dump()["excluded_seasons"] == [
        {"season": 2023, "reason": "Standings unresolved."}
    ]


def test_existing_scope_defaults_to_empty_coverage():
    # Mutation: make coverage required and break cached ready/unavailable payloads.
    scope = RatingScope(status="ready", basis="current", label="Career rating")
    assert scope.model_dump()["included_seasons"] == []
    assert scope.model_dump()["excluded_seasons"] == []
