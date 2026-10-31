from app import vocab
from app.ingestion.candidate import blocking_issues
from app.models import Observation, ReviewFlag
from app.schemas import FlagOut, ObservationOut


def observation_out(obs: Observation) -> ObservationOut:
    out = ObservationOut.model_validate(obs)
    out.blocking_issues = blocking_issues(obs.extraction_issues)
    return out


def flag_out(flag: ReviewFlag) -> FlagOut:
    out = FlagOut.model_validate(flag)
    out.allowed_resolutions = list(vocab.ALLOWED_RESOLUTIONS[flag.kind]) if flag.status == "open" else []
    return out
