"""Interest profile service — updates user dimension scores based on interaction signals."""

from datetime import datetime, timezone

from app.models.user_interest_profile import UserInterestProfile
from app.models.job_posting import JobPosting
from app.models.organization import Organization

# Signal weights (adapted from newsscraper content-based scoring)
SIGNAL_WEIGHTS = {
    "thumbs_up": 1.0,
    "apply_click": 0.9,
    "save": 0.7,
    "view": 0.15,
    "unsave": -0.3,
    "thumbs_down": -1.0,
}

LEARNING_RATE = 0.1


def _update_score(current: float, weight: float) -> float:
    """Update a single dimension score toward target based on signal weight.

    All scores start at 0.5 (neutral).
    Positive signals push toward 1.0, negative toward 0.0.
    """
    target = 1.0 if weight > 0 else 0.0
    magnitude = abs(weight)
    delta = (target - current) * magnitude * LEARNING_RATE
    return max(0.0, min(1.0, current + delta))


def apply_job_signal(profile: UserInterestProfile, job: JobPosting, org: Organization | None, signal_type: str):
    """Apply a signal from a job interaction to the user's interest profile.

    Updates category, city, region, and org_type dimension scores.
    """
    weight = SIGNAL_WEIGHTS.get(signal_type, 0)
    if weight == 0:
        return

    # Category
    if job.category:
        scores = dict(profile.category_scores or {})
        current = scores.get(job.category, 0.5)
        scores[job.category] = round(_update_score(current, weight), 4)
        profile.category_scores = scores

    # City
    if job.city:
        scores = dict(profile.city_scores or {})
        current = scores.get(job.city, 0.5)
        scores[job.city] = round(_update_score(current, weight), 4)
        profile.city_scores = scores

    # Region (from organization)
    if org and org.esc_region:
        region_key = str(org.esc_region)
        scores = dict(profile.region_scores or {})
        current = scores.get(region_key, 0.5)
        scores[region_key] = round(_update_score(current, weight), 4)
        profile.region_scores = scores

    # Org type
    if org and org.org_type:
        scores = dict(profile.org_type_scores or {})
        current = scores.get(org.org_type, 0.5)
        scores[org.org_type] = round(_update_score(current, weight), 4)
        profile.org_type_scores = scores

    profile.last_updated_at = datetime.now(timezone.utc)


def apply_time_decay(profile: UserInterestProfile, days: float = 1.0, half_life: float = 14.0):
    """Apply time decay to all scores, moving them toward 0.5 (neutral).

    Formula: score = 0.5 + (score - 0.5) * 0.5^(days/half_life)
    """
    decay_factor = 0.5 ** (days / half_life)

    for attr in ("category_scores", "city_scores", "region_scores", "org_type_scores"):
        scores = dict(getattr(profile, attr) or {})
        for key in scores:
            scores[key] = round(0.5 + (scores[key] - 0.5) * decay_factor, 4)
        setattr(profile, attr, scores)

    profile.last_updated_at = datetime.now(timezone.utc)
