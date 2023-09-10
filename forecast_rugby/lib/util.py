import asyncio
import typing

_T = typing.TypeVar("_T")


async def gather_futures(
    futures: typing.Iterable[typing.Coroutine[typing.Any, typing.Any, _T]]
) -> list[_T]:
    async with asyncio.TaskGroup() as tg:
        tasks = [tg.create_task(future) for future in futures]
    return [task.result() for task in tasks]
