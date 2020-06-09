import aiohttp
import asyncio
from datetime import datetime, timedelta, timezone
from bs4 import BeautifulSoup

class HTTPError(RuntimeError):
    def __init__(self, code):
        self.code = code

    def __str__(self):
        return "HTTP {}".format(self.code)

class TestConfig():
    async def print(self):
        return True

class TestCog():
    def __init__(self):
        self.config = TestConfig()
        self.session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=15))

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.session.close()

def round_time(dt=None, round_to=1):
    # https://stackoverflow.com/a/10854034
    if dt == None:
        dt = datetime.now(timezone.utc)
    seconds = (dt.replace(tzinfo=None) - dt.min).seconds
    rounding = (seconds + roundTo / 2) // roundTo * roundTo
    return dt + timedelta(0, rounding - seconds, -dt.microsecond)

class Utils():
    def __init__(self, cog):
        self.cog = cog

    def log(self, msg, *args):
        time = datetime.now(timezone.utc)
        print("{}: {}".format(time.strftime('%Y-%m-%d %H:%M:%S'), msg.format(*args)))

    async def request(self, url, json=False):
        log = await self.cog.config.print()
        if log:
            self.log("request {}", url)
        # This is wrong but I can't get it to work when reusing the cog's session
        # [CRITICAL] red.main: Caught unhandled exception in task: Unclosed client session
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
            for i in range(3, 0, -1):
                try:
                    async with session.get(url) as r:
                        if r.status != 200:
                            raise HTTPError(r.status)
                        if json:
                            return await r.json()
                        else:
                            return await r.text()
                except asyncio.exceptions.TimeoutError:
                    if i == 1:
                        raise
                    elif log:
                        self.log("retry {}", url)

    def parse_catalog(self, html, now=None):
        if now == None:
            now = datetime.now(timezone.utc)
        soup = BeautifulSoup(html, "html5lib")
        for a in soup.select("#Grid .thread > a"):
            last_modified = datetime.strptime(a.img["title"], '%b %d %H:%M')
            # Set to UTC
            last_modified = last_modified.replace(tzinfo=timezone.utc)
            # Set to current year
            last_modified = last_modified.replace(year=now.year)
            # Add 75 seconds (for end of minute and to give some margin of error)
            last_modified = last_modified + timedelta(seconds=75)
            # Account for threads updated last year
            # No way to tell if the update was actually more than 1 year ago?
            if last_modified > now + timedelta(days=1):
                last_modified = last_modified.replace(year=last_modified.year - 1)
            yield {"href": a["href"], "last_modified": last_modified}

