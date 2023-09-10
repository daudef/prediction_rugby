import dataclasses
import pydantic

from forecast_rugby.lib import cfg


@dataclasses.dataclass
class Match:
    forecast_url: pydantic.HttpUrl
    country1: cfg.Country
    country2: cfg.Country


@dataclasses.dataclass
class Prediction:
    match: Match
    country1_is_winning: bool
    delta: float
