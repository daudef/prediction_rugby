import tomllib
import pydantic
import pathlib


class Country(pydantic.BaseModel):
    scorecast: str
    fdj: str


class Scorecast(pydantic.BaseModel):
    username: str
    password: str
    device: str
    token_cache_path: pathlib.Path
    base_url: pydantic.HttpUrl
    forecast_read_route: str
    forecast_write_route: str
    auth_route: str


class Fdj(pydantic.BaseModel):
    base_url: pydantic.HttpUrl


class Config(pydantic.BaseModel):
    fdj: Fdj
    scorecast: Scorecast
    countries: list[Country]


def read_config():
    dir = pathlib.Path(__file__).parent
    while dir != pathlib.Path("/"):
        try:
            fp = dir / "config.toml"
            with fp.open(mode="rb") as f:
                print(f"Reading config at {fp}")
                return Config(**tomllib.load(f))
        except FileNotFoundError:
            pass
        dir = dir.parent
    raise Exception("Config not found")
