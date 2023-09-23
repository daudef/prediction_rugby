import asyncio
import typing


import unidecode


_T = typing.TypeVar("_T")


async def gather_futures(
    futures: typing.Iterable[typing.Coroutine[typing.Any, typing.Any, _T]]
) -> list[_T]:
    async with asyncio.TaskGroup() as tg:
        tasks = [tg.create_task(future) for future in futures]
    return [task.result() for task in tasks]


def str_normalise(s: str, join_char: str):
    return join_char.join(
        "".join(
            c if c.isalnum() else " "
            for c in unidecode.unidecode(s, errors="replace", replace_str=" ")
        ).split()
    )
