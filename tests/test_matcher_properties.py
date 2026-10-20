from hypothesis import given, settings, strategies as st

from jobscout.matcher import score_job
from jobscout.models import Job

BASE_PROFILE = {
    "name": "Amit Kumar Sahu",
    "title": "Senior Data Engineer",
    "years_experience": 9,
    "remote_ok": True,
    "target_titles": ["data engineer"],
    "skills": [
        "python", "pyspark", "sql", "aws glue", "aws dms", "redshift",
        "athena", "kinesis", "lake formation", "airflow", "apache iceberg",
        "cube cloud", "row-level security", "multi-tenant",
    ],
    "locations": ["bengaluru", "bangalore", "blr", "remote", "india"],
    "industries": ["pharma", "saas", "fintech"],
}

# Arbitrary-ish text: empty, unicode, emoji, very long, numbers-only, etc.
text_strategy = st.text(min_size=0, max_size=500)


def _job(**overrides) -> Job:
    base = dict(id="1", title="", company="", location="", url="https://example.com/1",
                source="greenhouse", description="")
    base.update(overrides)
    return Job(**base)


@given(title=text_strategy, company=text_strategy, location=text_strategy,
       description=text_strategy)
@settings(max_examples=300)
def test_score_is_always_within_0_and_100(title, company, location, description):
    job = _job(title=title, company=company, location=location, description=description)
    result = score_job(job, BASE_PROFILE)
    assert 0 <= result["score"] <= 100
    assert isinstance(result["score"], int)


@given(years_required=st.integers(min_value=0, max_value=60))
@settings(max_examples=100)
def test_score_is_always_within_0_and_100_across_year_requirements(years_required):
    job = _job(
        title="Senior Data Engineer",
        description=f"Python, SQL, Airflow. {years_required}+ years required.",
        location="Bengaluru",
    )
    result = score_job(job, BASE_PROFILE)
    assert 0 <= result["score"] <= 100


@given(candidate_years=st.integers(min_value=0, max_value=50))
@settings(max_examples=50)
def test_score_is_always_within_0_and_100_across_candidate_experience(candidate_years):
    profile = dict(BASE_PROFILE, years_experience=candidate_years)
    job = _job(title="Senior Data Engineer", description="Python, SQL. 20+ years required.",
               location="Bengaluru")
    result = score_job(job, profile)
    assert 0 <= result["score"] <= 100


# --------------------------------------------------------------------------
# Title variants
# --------------------------------------------------------------------------

SENIOR_TITLE_VARIANTS = [
    "Sr. Data Engineer",
    "Senior Data Engineer",
    "Lead Data Engineer",
    "Staff Data Engineer",
    "Principal Data Engineer",
    "Data Engineer II",
    "Data Engineer III",
    "Big Data Engineer",
    "Analytics Engineer",
    "Data Platform Engineer",
]


def _strong_job(title: str) -> Job:
    return _job(
        title=title,
        company="Acme Pharma",
        location="Bengaluru, India",
        description=(
            "Build Python and PySpark pipelines on AWS Glue, Redshift, "
            "Athena, Kinesis and Lake Formation with Airflow and Apache "
            "Iceberg. 6+ years experience required."
        ),
    )


def test_senior_level_title_variants_all_score_well():
    for title in SENIOR_TITLE_VARIANTS:
        result = score_job(_strong_job(title), BASE_PROFILE)
        assert result["score"] >= 60, f"{title!r} scored too low: {result}"


def test_data_engineer_ii_iii_are_not_penalised_as_junior():
    for title in ("Data Engineer II", "Data Engineer III"):
        result = score_job(_strong_job(title), BASE_PROFILE)
        assert result["breakdown"]["title"] >= 40, f"{title!r}: {result}"


# --------------------------------------------------------------------------
# Generic SWE/frontend/mobile/QA/DevOps roles score below 40
# --------------------------------------------------------------------------

GENERIC_NON_DATA_TITLES = [
    "Software Engineer",
    "Frontend Engineer",
    "Mobile Engineer, iOS",
    "QA Engineer",
    "DevOps Engineer",
    "Site Reliability Engineer",
]


def test_generic_non_data_roles_score_below_40():
    for title in GENERIC_NON_DATA_TITLES:
        job = _job(
            title=title,
            company="Acme SaaS",
            location="Bengaluru, India",
            description="Build and ship features. 3+ years experience required.",
        )
        result = score_job(job, BASE_PROFILE)
        assert result["score"] < 40, f"{title!r} scored too high: {result}"


# --------------------------------------------------------------------------
# Bengaluru spelling / format variants
# --------------------------------------------------------------------------

BENGALURU_LOCATION_VARIANTS = [
    "Bengaluru",
    "Bangalore",
    "Bengaluru, Karnataka",
    "Bengaluru, Karnataka, India",
    "Bangalore, India",
    "BLR",
    "India - Remote",
    "Remote (APAC)",
    "Hybrid - Bengaluru",
]


def test_bengaluru_spelling_variants_all_score_the_location_bonus():
    # Uses BASE_PROFILE unmodified - this is exactly the locations list
    # shipped in profiles/amit.yaml. "BLR" alone used to fail here (no
    # "bengaluru"/"bangalore" substring present) until "blr" was added
    # as an explicit alias.
    for location in BENGALURU_LOCATION_VARIANTS:
        job = _strong_job("Senior Data Engineer")
        job.location = location
        result = score_job(job, BASE_PROFILE)
        assert result["breakdown"]["location"] > 0, f"{location!r} got no location credit: {result}"
