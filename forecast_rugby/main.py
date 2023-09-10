import asyncio
import httpx

from forecast_rugby.lib import fdj, cfg, scorecast


async def main():
    config = cfg.read_config()

    async with httpx.AsyncClient(headers={"user-agent": ""}) as http_client:
        predictions = await fdj.get_upcomming_predictions(config, http_client)
        await scorecast.send_predictions(predictions, config=config, http_client=http_client)


if __name__ == "__main__":
    asyncio.run(main())
