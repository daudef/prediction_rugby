import typing
import bs4
import pydantic


def get_first_attr(tag: bs4.Tag, key: str):
    value = tag.get(key)
    if value is None:
        return None
    if isinstance(value, list):
        if len(value) == 0:
            return None
        return value[0]
    return value


_T = typing.TypeVar("_T", bound=bs4.PageElement)


def get_child(tag: bs4.Tag, typ: type[_T], index: int | None = None):
    candidates = [child for child in tag.children if isinstance(child, typ)]
    if index is None:
        assert len(candidates) <= 1
        index = 0

    if index < len(candidates):
        return candidates[index]
    else:
        return None


def strip_url_path(url: pydantic.HttpUrl):
    return pydantic.HttpUrl.build(
        scheme=url.scheme,
        username=url.username,
        password=url.username,
        host=url.host or "",
        port=url.port,
    )


def get_urls(tag: bs4.Tag, base_url: pydantic.HttpUrl) -> typing.Iterator[pydantic.HttpUrl]:
    if (link := get_first_attr(tag, "href")) is not None:
        if link.startswith("/"):
            yield pydantic.HttpUrl(str(strip_url_path(base_url)) + link.removeprefix("/"))
        elif link.startswith("http"):
            yield pydantic.HttpUrl(link)
        else:
            yield pydantic.HttpUrl(str(strip_url_path(base_url)) + (base_url.path or "/") + link)
    for child in tag:
        if isinstance(child, bs4.Tag):
            yield from get_urls(child, base_url=base_url)
