import collections
import dataclasses
import typing

import pydantic
import bs4
import httpx

from forecast_rugby.lib import scrap, model, cfg, util

POINTS_PREFIX = "Plus / Moins Point(s) - ".lower().strip()
FULL_MATCH_SUFFIX = " - 80 mins".lower().strip()


async def get_document(url: pydantic.HttpUrl, http_client: httpx.AsyncClient):
    response = await http_client.get(str(url))
    try:
        return bs4.BeautifulSoup(response.text, "html.parser")
    except Exception:
        raise Exception(response.status_code, response.text)


def get_country_names(url: pydantic.HttpUrl):
    assert url.path is not None
    (c1, c2) = url.path.split("/")[-1].split("-vs-")
    return c1.strip(), c2.strip()


@dataclasses.dataclass
class CountryScore:
    country: str
    score: float


@dataclasses.dataclass
class Ratings:
    more: float
    less: float


@dataclasses.dataclass
class Forecast:
    cscore: CountryScore
    ratings: Ratings


def get_country_score(tag: bs4.Tag):
    if scrap.get_first_attr(tag, "class") == "psel-title-market__label":
        child = scrap.get_child(tag, bs4.NavigableString)
        if child is None:
            return
        child = child.lower()
        if not child.startswith(POINTS_PREFIX) or not child.endswith(FULL_MATCH_SUFFIX):
            return
        *country, score = child.removeprefix(POINTS_PREFIX).removesuffix(FULL_MATCH_SUFFIX).split()
        return CountryScore(country="-".join(country), score=float(score.replace(",", ".")))


def get_ratings(tag: bs4.Tag):
    for index in [1, 0, 0, 0]:
        child = scrap.get_child(tag, bs4.Tag, index=index)
        if child is None:
            return None
        tag = child

    ratings: list[float] = []
    for rating_index in range(2):
        rating_tag = tag
        for index in [rating_index, 1, 0, 0]:
            child = scrap.get_child(rating_tag, bs4.Tag, index=index)
            if child is None:
                return None
            rating_tag = child
        rating_value = scrap.get_child(rating_tag, bs4.NavigableString)
        if rating_value is None:
            return None
        ratings.append(float(rating_value.replace(",", ".")))

    if len(ratings) != 2:
        return None
    (more, less) = ratings
    return Ratings(more=more, less=less)


def find_forecasts(
    tag: bs4.Tag, parent: bs4.Tag | None, grand_parent: bs4.Tag | None
) -> typing.Iterator[Forecast]:
    if (
        (cscore := get_country_score(tag)) is not None
        and grand_parent is not None
        and (ratings := get_ratings(grand_parent)) is not None
    ):
        yield Forecast(cscore=cscore, ratings=ratings)

    for child in tag.children:
        if isinstance(child, bs4.Tag):
            yield from find_forecasts(child, parent=tag, grand_parent=parent)


@dataclasses.dataclass
class GroupedForecasts:
    c1: list[Forecast]
    c2: list[Forecast]


def group_forecast_by_country(forecasts: list[Forecast], *, c1: str, c2: str):
    forecasts_by_country: dict[str, list[Forecast]] = collections.defaultdict(list)
    for forecast in forecasts:
        forecasts_by_country[forecast.cscore.country].append(forecast)
    if not set(forecasts_by_country.keys()).issubset({c1, c2}):
        raise Exception(
            f"forecast countries are {list(forecasts_by_country.keys())}"
            + f" but searched countries are {c1} and {c2}"
        )
    return GroupedForecasts(
        c1=forecasts_by_country.get(c1, []), c2=forecasts_by_country.get(c2, [])
    )


def get_average_points_from_forecasts(forecasts: list[Forecast]):
    a = None
    b = None
    for f in forecasts:
        if (a is not None and f.cscore.score <= a) or (b is not None and f.cscore.score >= b):
            continue
        if f.ratings.more <= f.ratings.less:
            a = f.cscore.score
        if f.ratings.more >= f.ratings.less:
            b = f.cscore.score
    if a is None:
        if b is None:
            return None
        return b
    if b is None:
        return a
    return (a + b) / 2


async def make_prediction(match: model.Match, http_client: httpx.AsyncClient):
    document = await get_document(match.forecast_url, http_client)
    forecasts = list(find_forecasts(document, parent=None, grand_parent=None))
    if len(forecasts) == 0:
        return None
    grouped_forecasts = group_forecast_by_country(
        forecasts, c1=match.country1.fdj, c2=match.country2.fdj
    )
    p1 = get_average_points_from_forecasts(grouped_forecasts.c1)
    p2 = get_average_points_from_forecasts(grouped_forecasts.c2)
    if p1 is None or p2 is None:
        print(
            f"score prediction is {p1} for {match.country1.fdj}, and {p2} for {match.country2.fdj}"
            + " which is not enough to make a full predction"
        )
        return None
    return model.Prediction(
        match=match,
        country1_is_winning=p1 >= p2,
        delta=abs(p1 - p2),
    )


def url_to_match(
    url: pydantic.HttpUrl, base_url: pydantic.HttpUrl, country_name_map: dict[str, cfg.Country]
):
    if not str(url).startswith(str(base_url)):
        return None
    county_names = (url.path or "/").split("/")[-1].split("-vs-")
    if len(county_names) != 2:
        return None
    cname1, cname2 = county_names
    return model.Match(
        forecast_url=url, country1=country_name_map[cname1], country2=country_name_map[cname2]
    )


async def get_upcomming_matchs(config: cfg.Config, http_client: httpx.AsyncClient):
    base_url = config.fdj.base_url
    document = await get_document(base_url, http_client)
    country_name_map = {c.fdj: c for c in config.countries}
    urls = set(scrap.get_urls(document, base_url=base_url))
    return [
        match
        for url in urls
        if (match := url_to_match(url, base_url=base_url, country_name_map=country_name_map))
        is not None
    ]


async def get_upcomming_predictions(config: cfg.Config, http_client: httpx.AsyncClient):
    return [
        prediction
        for prediction in await util.gather_futures(
            make_prediction(match, http_client)
            for match in await get_upcomming_matchs(config, http_client)
        )
        if prediction is not None
    ]
