import aiohttp
from datetime import datetime, timedelta, timezone
from bs4 import BeautifulSoup

class TestConfig():
    async def print(self):
        return True

class TestCog():
    def __init__(self):
        self.config = TestConfig()
        self.session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30))

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.session.close()

def log(msg, *args):
    time = datetime.now(timezone.utc)
    print("{}: {}".format(time.strftime('%Y-%m-%d %H:%M:%S'), msg.format(*args)))

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

    async def request(self, url, json=False):
        if await self.cog.config.print():
            log("request {}", url)
        # This is wrong but I can't get it to work when reusing the cog's session
        # [CRITICAL] red.main: Caught unhandled exception in task: Unclosed client session
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
            async with self.session.get(url) as r:
                if r.status != 200:
                    raise RuntimeError('HTTP {}'.format(r.status))
                if json:
                    return await r.json()
                else:
                    return await r.text()

    def parse_catalog(self, html, now=None):
        if now == None:
            now = datetime.now(timezone.utc)
        soup = BeautifulSoup(html, "html.parser")
        for a in soup.select("#Grid .thread > a"):
            last_modified = datetime.strptime(a.img["title"], '%b %d %H:%M')
            # Set to UTC
            last_modified = last_modified.replace(tzinfo=timezone.utc)
            # Set to current year
            last_modified = last_modified.replace(year=now.year)
            # Set to minute + 1 and second + 15 (to give some margin of error)
            last_modified = last_modified.replace(
                    minute=last_modified.minute + 1,
                    second=last_modified.second + 15)
            # Account for threads updated last year
            # No way to tell if the update was actually more than 1 year ago?
            if last_modified > now + timedelta(days=1):
                last_modified = last_modified.replace(year=last_modified.year - 1)
            yield {"href": a["href"], "last_modified": last_modified}

