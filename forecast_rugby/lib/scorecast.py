import binascii
import dataclasses
import datetime
import json
import httpx
import base64

import pydantic

from forecast_rugby.lib import cfg, model


def get_existing_token(config: cfg.Scorecast):
    try:
        with config.token_cache_path.open("r", encoding="utf-8") as f:
            token = f.read().strip()
    except FileNotFoundError:
        return
    token_parts = token.split(".")
    if len(token_parts) != 3:
        return
    _, payload, _ = token_parts
    try:
        payload = json.loads(base64.urlsafe_b64decode(payload + "===="))
    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError):
        return
    exp = payload.get("exp")
    if not isinstance(exp, (int, float)):
        return
    exp = datetime.datetime.fromtimestamp(exp)
    if exp < datetime.datetime.now() + datetime.timedelta(minutes=1):
        return None
    return token


async def get_token(config: cfg.Scorecast, http_client: httpx.AsyncClient):
    if (token := get_existing_token(config)) is not None:
        print("Already logged in Scorecast")
        return token

    print("Logging in Scorecast")

    response = await http_client.post(
        str(config.base_url)[:-1] + config.auth_route,
        json={
            "login": config.username,
            "password": config.password,
            "device": config.device,
        },
    )
    if not response.status_code // 100 == 2:
        raise Exception(response.status_code, response.text)
    token = response.json()["accessToken"]
    assert isinstance(token, str)
    with config.token_cache_path.open("w", encoding="utf-8") as f:
        f.write(token + "\n")
    return token


class Competitor(pydantic.BaseModel):
    id: str
    name: str


class DiffInterval(pydantic.BaseModel):
    from_: int = pydantic.Field(alias="from")
    to: int


class UserForecast(pydantic.BaseModel):
    score1: int
    score2: int
    winnerId: str | None
    gameId: str


class Game(pydantic.BaseModel):
    id: str
    competitor1: Competitor
    competitor2: Competitor
    diffIntervals: list[DiffInterval]
    userForecast: UserForecast | None = None


class Games(pydantic.BaseModel):
    games: list[Game]


async def get_games(token: str, config: cfg.Scorecast, http_client: httpx.AsyncClient):
    url = (
        str(config.base_url)[:-1]
        + config.forecast_read_route
        + "?"
        + "&".join(
            f"{k}={v}"
            for (k, v) in {
                "status": "COMING",
                "take": 10,
                "skip": 0,
            }.items()
        )
    )
    response = await http_client.get(
        url,
        headers={"authorization": f"Bearer {token}", "locale": "en"},
    )
    if response.status_code // 100 != 2:
        raise Exception(response.status_code, response.text)
    return list(reversed(Games(**{"games": response.json()}).games))


@dataclasses.dataclass
class MappedPrediction:
    prediction: model.Prediction
    game: Game
    reversed_countries: bool


def map_predictions(predictions: list[model.Prediction], games: list[Game]):
    cname_set_game_map = {
        frozenset([game.competitor1.name, game.competitor2.name]): game for game in games
    }
    mapped_predictions: list[MappedPrediction] = []
    for prediction in predictions:
        cname_set = frozenset(
            [prediction.match.country1.scorecast, prediction.match.country2.scorecast]
        )
        if (game := cname_set_game_map.get(cname_set)) is not None:
            mapped_predictions.append(
                MappedPrediction(
                    prediction=prediction,
                    game=game,
                    reversed_countries=prediction.match.country1.scorecast != game.competitor1.name,
                )
            )
        else:
            print(f"Cannot find Scorecast game for {' / '.join(cname_set)}")
    return mapped_predictions


def dist_to_range(v: float, interval: DiffInterval):
    if interval.from_ <= v <= interval.to:
        return 0
    return min(abs(interval.from_ - v), abs(interval.to - v))


def make_forecast(mapped_prediction: MappedPrediction):
    interval = min(
        mapped_prediction.game.diffIntervals,
        key=lambda i: dist_to_range(mapped_prediction.prediction.delta, i),
    )
    c1_is_winning = mapped_prediction.prediction.country1_is_winning
    if mapped_prediction.reversed_countries:
        c1_is_winning = not c1_is_winning

    if c1_is_winning:
        winner = mapped_prediction.game.competitor1
    else:
        winner = mapped_prediction.game.competitor2

    forecast = UserForecast(
        gameId=mapped_prediction.game.id,
        winnerId=winner.id,
        score1=interval.from_,
        score2=interval.to,
    )

    if mapped_prediction.game.userForecast == forecast:
        return None
    else:
        return forecast


def make_forecasts(mapped_predictions: list[MappedPrediction]):
    return [make_forecast(mp) for mp in mapped_predictions]


def get_winner_name(forecast: UserForecast, game: Game):
    if forecast.winnerId is None:
        return "none"
    return (
        game.competitor1.name if game.competitor1.id == forecast.winnerId else game.competitor2.name
    )


def display_forecast_update(forecast: UserForecast | None, game: Game):
    game_name = f"{game.competitor1.name} / {game.competitor2.name}"

    if forecast is None:
        print(f"[{game_name}] Not changing forecast")
    else:
        assert forecast.gameId == game.id
        winner = get_winner_name(forecast, game)
        score = f"{forecast.score1} - {forecast.score2}"
        if game.userForecast is not None:
            prev_winner = get_winner_name(game.userForecast, game)
            prev_score = f"{game.userForecast.score1} - {game.userForecast.score2}"
            print(
                f"[{game_name}] Updating forecast from {prev_winner} ({prev_score}) to {winner} ({score})"
            )
        else:
            print(f"[{game_name}] New forecast {winner} ({score})")


def display_forecast_updates(
    forecasts: list[UserForecast | None], mapped_predictions: list[MappedPrediction]
):
    for forecast, mapped_prediction in zip(forecasts, mapped_predictions):
        display_forecast_update(forecast, game=mapped_prediction.game)


class Forecasts(pydantic.BaseModel):
    forecasts: list[UserForecast]
    sync: bool


async def apply_forecast_updates(
    forecasts: list[UserForecast | None],
    token: str,
    config: cfg.Scorecast,
    http_client: httpx.AsyncClient,
):
    forecasts_model = Forecasts(
        forecasts=[forecast for forecast in forecasts if forecast is not None], sync=True
    )
    if len(forecasts_model.forecasts) == 0:
        return

    url = str(config.base_url)[:-1] + config.forecast_write_route
    response = await http_client.post(
        url,
        headers={
            "authorization": f"Bearer {token}",
        },
        json=forecasts_model.model_dump(),
    )

    if response.status_code // 100 != 2:
        raise Exception(response.status_code, response.text)
    print("Saved updates")


async def send_predictions(
    predictions: list[model.Prediction], config: cfg.Config, http_client: httpx.AsyncClient
):
    if len(predictions) == 0:
        print("Nothing to do")
        return
    token = await get_token(config.scorecast, http_client)
    games = await get_games(token, config=config.scorecast, http_client=http_client)
    mapped_predictions = map_predictions(predictions=predictions, games=games)
    forecasts = make_forecasts(mapped_predictions)
    display_forecast_updates(forecasts, mapped_predictions=mapped_predictions)
    await apply_forecast_updates(
        forecasts, token=token, config=config.scorecast, http_client=http_client
    )
