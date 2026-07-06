from app.services.profile_service import classify_profile_level


def test_classify_profile_level():
    assert classify_profile_level(59) == "beginner"
    assert classify_profile_level(60) == "intermediate"
    assert classify_profile_level(85) == "advanced"
