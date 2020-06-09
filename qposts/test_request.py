import asyncio
from utils import TestConfig, TestCog, Utils, HTTPError

async def main():
    async with TestCog() as cog:
        utils = Utils(cog)

        print(await utils.request('https://httpbin.org/get'))

        errors = 0
        try:
            print(await utils.request('https://httpbin.org/status/400'))
        except HTTPError as e:
            errors += 1
            print(f'HTTPError: {e}')
            assert(e.code == 400)
            assert("{}".format(e) == 'HTTP 400')
            assert(str(e) == 'HTTP 400')

        assert(errors == 1)

if __name__ == '__main__':
    asyncio.run(main())
