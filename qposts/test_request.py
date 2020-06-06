import asyncio
from utils import TestConfig, TestCog, Utils

async def main():
    async with TestCog() as cog:
        utils = Utils(cog)

        print(await utils.request('https://httpbin.org/get'))

        try:
            print(await utils.request('https://httpbin.org/status/400'))
        except RuntimeError as e:
            print(f'RuntimeError: {e}')

if __name__ == '__main__':
    asyncio.run(main())
