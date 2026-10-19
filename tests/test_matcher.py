from jobscout.matcher import score_job
from jobscout.models import Job

PROFILE = {
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
    "locations": ["bengaluru", "bangalore", "remote", "india"],
    "industries": ["pharma", "saas", "fintech"],
}


def _job(**overrides) -> Job:
    base = dict(
        id="1", title="Senior Data Engineer", company="Acme", location="Remote",
        url="https://example.com/1", source="greenhouse", description="",
    )
    base.update(overrides)
    return Job(**base)


def test_senior_data_engineer_bengaluru_on_stack_scores_70_plus():
    job = _job(
        title="Senior Data Engineer",
        company="Acme Pharma",
        location="Bengaluru, India",
        description=(
            "Build Python and PySpark pipelines on AWS Glue, Redshift, Athena, "
            "Kinesis and Lake Formation, orchestrated with Airflow and Apache "
            "Iceberg tables. 6+ years experience required."
        ),
    )
    result = score_job(job, PROFILE)
    assert result["score"] >= 70


def test_generic_software_engineer_scores_below_40():
    job = _job(
        title="Software Engineer, Mobile (iOS)",
        company="Acme SaaS",
        location="Bengaluru, India",
        description=(
            "Build delightful native iOS apps in Swift and SwiftUI. 3+ years "
            "experience with mobile development required."
        ),
    )
    result = score_job(job, PROFILE)
    assert result["score"] < 40


def test_excessive_years_requirement_is_penalised():
    reasonable = _job(
        title="Lead Data Engineer",
        company="BigCorp",
        location="Remote",
        description=(
            "Lead Data Engineer role using Python, SQL and PySpark on our "
            "platform. 5+ years of experience required."
        ),
    )
    excessive = _job(
        title="Lead Data Engineer",
        company="BigCorp",
        location="Remote",
        description=(
            "Lead Data Engineer role using Python, SQL and PySpark on our "
            "platform. 18+ years of experience required."
        ),
    )
    reasonable_result = score_job(reasonable, PROFILE)
    excessive_result = score_job(excessive, PROFILE)

    assert excessive_result["breakdown"]["experience_penalty"] > 0
    assert reasonable_result["breakdown"]["experience_penalty"] == 0
    assert excessive_result["score"] <= reasonable_result["score"] - 20


def test_score_is_clamped_to_0_100():
    empty_job = _job(title="", company="", location="", description="")
    result = score_job(empty_job, PROFILE)
    assert 0 <= result["score"] <= 100
