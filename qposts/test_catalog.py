import asyncio
import os
import pathlib
from datetime import datetime, timezone
from utils import TestConfig, TestCog, Utils

async def main():
    async with TestCog() as cog:
        utils = Utils(cog)

        catalog_path = os.path.join(os.path.dirname(__file__), 'catalog.html')
        catalog_html = pathlib.Path(catalog_path).read_text()

        found = 0
        fake_now = datetime(2020, 6, 6, 6, 24, 17, 0, tzinfo=timezone.utc)
        for t in utils.parse_catalog(catalog_html, fake_now):
            print(t)
            if t["href"] == '/qresearch/res/6064510.html':
                assert(t["last_modified"] == datetime(2020, 6, 5, 0, 43, 15, tzinfo=timezone.utc))
                found += 1
            if t["href"] == '/qresearch/res/6156082.html':
                assert(t["last_modified"] == datetime(2019, 12, 28, 22, 45, 15, tzinfo=timezone.utc))
                found += 1

        assert(found == 2)

if __name__ == '__main__':
    asyncio.run(main())
