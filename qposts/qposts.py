import discord
import aiohttp
import asyncio
import json
import os
import traceback
from datetime import datetime, timedelta, timezone
from redbot.core import commands
from redbot.core import Config
from redbot.core import checks
from redbot.core.data_manager import cog_data_path
from pathlib import Path
from bs4 import BeautifulSoup
from .utils import Utils, HTTPError, round_time
try:
    import tweepy as tw
    twInstalled = True
except:
    twInstalled = False

numbs = {
    "next": "➡",
    "back": "⬅",
    "exit": "❌"
}
class QPosts(getattr(commands, "Cog", object)):
    """Gather QAnon updates from 8kun"""

    def __init__(self, bot):
        self.bot = bot
        default_data = {
            "twitter": {
                "access_secret" : "",
                "access_token" : "",
                "consumer_key" : "",
                "consumer_secret" : "",
            },
            "boards": {},
            "channels": [],
            "last_checked": 0,
            "last_succeeded": 0,
            "print": True,
        }
        self.config = Config.get_conf(self, 112444567876)
        self.config.register_global(**default_data)
        self.session = aiohttp.ClientSession(
                loop=self.bot.loop,
                timeout=aiohttp.ClientTimeout(total=15))
        self.utils = Utils(self)
        self.url = "https://8kun.top"
        self.boards = ["qresearch", "projectdcomms"]
        self.trips = ["!!Hs1Jq13jV6"]
        self.loop = bot.loop.create_task(self.get_q_posts())

    async def twitter_authenticate(self):
        """Authenticate with Twitter's API"""
        try:
            consumer_key = await self.config.twitter.consumer_key()
            consumer_secret = await self.config.twitter.consumer_secret()
            access_token = await self.config.twitter.access_token()
            access_secret = await self.config.twitter.access_secret()
            if not consumer_key or not consumer_secret \
                    or not access_token or not access_secret:
                return None
            auth = tw.OAuthHandler(consumer_key, consumer_secret)
            auth.set_access_token(access_token, access_secret)
            return tw.API(auth)
        except:
            return

    async def send_tweet(self, message: str, file=None):
        """Sends tweets as the bot owners account"""
        if not twInstalled:
            return
        try:
            api = await self.twitter_authenticate()
            if not api:
                return
            if file is None:
                api.update_status(message)
                if await self.config.print():
                    print("sent tweet")
            else:
                api.update_with_media(file, status=message)
                if await self.config.print():
                    print("sent tweet with image")
        except:
            return

    @commands.command()
    async def reset_qpost(self, ctx):
        await self.config.last_checked.set(0)
        await self.config.last_succeeded.set(0)
        await ctx.send("Done.")

    @commands.command(pass_context=True, name="qrole")
    async def qrole(self, ctx):
        """
        Add yourself to the QPOSTS role so you will get notifications for new Q
        posts.

        For this to work, a role called QPOSTS must exist on your server, and
        the bot must be assigned to a role that can Manage Roles and that is
        higher up in the roles list (more permissions) than the QPOSTS role.
        """
        guild = ctx.message.guild
        mention = ctx.message.author.mention
        async with ctx.typing():
            try:
                if not guild:
                    raise TypeError("This command only works within a guild.")
                role = [role for role in guild.roles if role.name == "QPOSTS"][0]
                await ctx.message.author.add_roles(role)
                await ctx.send(f"{mention}, you are now a member of the QPOSTS role and will get notifications for new Q posts.")
            except Exception as e:
                await ctx.send(f"{mention}, error adding you to the QPOSTS role: {e}")

    async def get_catalog_threads(self, board):
        catalog_url = "{}/{}/catalog.html".format(self.url, board)
        catalog_html = await self.utils.request(catalog_url)
        catalog_threads = [t for t in self.utils.parse_catalog(catalog_html)]
        catalog_updated = max(t["last_modified"] for t in catalog_threads)
        expected_updated = datetime.now(timezone.utc) - timedelta(minutes=6)
        if catalog_updated < expected_updated:
            self.utils.log("Catalog for /{}/ may be stuck! {} < {}".format(
                    board,
                    catalog_updated.strftime('%Y-%m-%d %H:%M:%S'),
                    expected_updated.strftime('%Y-%m-%d %H:%M:%S')))
            cb = int(round_time(round_to=15).timestamp())
            catalog_url = "{}/{}/catalog.html?_={}".format(self.url, board, cb)
            catalog_html = await self.utils.request(catalog_url,
                    timeout=30, max_tries=6)
            catalog_threads = [t for t in self.utils.parse_catalog(catalog_html)]
        return catalog_threads

    async def get_thread_posts(self, thread):
        thread_url = self.url + thread["href"].replace(".html", ".json")
        thread_posts = await self.utils.request(thread_url, json=True)
        thread_posts = thread_posts["posts"]
        thread_updated = datetime.utcfromtimestamp(
                max(p["last_modified"] for p in thread_posts))
        thread_updated = thread_updated.replace(tzinfo=timezone.utc)
        expected_updated = thread["last_modified"]
        # Max difference should be 75, see utils.parse_catalog()
        if expected_updated - thread_updated >= timedelta(seconds=90):
            self.utils.log("Thread {} looks stuck! c:{} - t:{} = {}s".format(
                thread_url,
                expected_updated.strftime('%Y-%m-%d %H:%M:%S'),
                thread_updated.strftime('%Y-%m-%d %H:%M:%S'),
                round((expected_updated - thread_updated).total_seconds())))
            cb = int(round_time(round_to=15).timestamp())
            thread_url += '?_=' + cb
            thread_posts = await self.utils.request(thread_url, json=True)
            thread_posts = thread_posts["posts"]
            thread_updated = datetime.utcfromtimestamp(
                    max(p["last_modified"] for p in thread_posts))
            thread_updated = thread_updated.replace(tzinfo=timezone.utc)
            self.utils.log("c:{} - t2:{} = {}s".format(
                thread_url,
                expected_updated.strftime('%Y-%m-%d %H:%M:%S'),
                thread_updated.strftime('%Y-%m-%d %H:%M:%S'),
                round((expected_updated - thread_updated).total_seconds())))
        return thread_posts

    async def get_q_posts(self):
        await self.bot.wait_until_ready()
        while self is self.bot.get_cog("QPosts"):
            errors = False
            this_check_time = datetime.now(timezone.utc)
            try:
                last_succeeded_time = await self.config.last_succeeded()
                if not last_succeeded_time: # migration
                    last_succeeded_time = await self.config.last_checked()
                last_succeeded_time = datetime.utcfromtimestamp(last_succeeded_time)
                last_succeeded_time = last_succeeded_time.replace(tzinfo=timezone.utc)
                board_posts = await self.config.boards()
                for board in self.boards:
                    try:
                        catalog_threads = await self.get_catalog_threads(board)
                    except:
                        self.utils.log("error getting catalog for /{}/: {}",
                                board,
                                traceback.format_exc(limit=1))
                        errors = True
                        continue
                    Q_posts = []
                    if board not in board_posts:
                        board_posts[board] = []
                    for thread in catalog_threads:
                        if thread["last_modified"] >= last_succeeded_time:
                            try:
                                posts = await self.get_thread_posts(thread)
                            except HTTPError as e:
                                if e.code == 404:
                                    self.utils.log("warning getting thread {}: {}",
                                            thread["href"],
                                            traceback.format_exc(limit=1))
                                    continue
                                else:
                                    raise
                            except:
                                self.utils.log("error getting thread {}: {}",
                                        thread["href"],
                                        traceback.format_exc(limit=1))
                                errors = True
                                continue
                            for post in posts:
                                if "trip" in post:
                                    if post["trip"] in self.trips:
                                        Q_posts.append(post)

                    old_posts = [post_no["no"] for post_no in board_posts[board]]

                    Q_posts.sort(key=lambda p: p["no"])
                    for post in Q_posts:
                        if post["no"] not in old_posts:
                            board_posts[board].append(post)
                            await self.postq(post, board)
                        for old_post in board_posts[board]:
                            if old_post["no"] == post["no"] and old_post["com"] != post["com"]:
                                if "edit" not in board_posts:
                                    board_posts["edit"] = {}
                                if board not in board_posts["edit"]:
                                    board_posts["edit"][board] = []
                                board_posts["edit"][board].append(old_post)
                                board_posts[board].remove(old_post)
                                board_posts[board].append(post)
                                await self.postq(post, board, True)
                await self.config.boards.set(board_posts)
            except:
                self.utils.log("unhandled error: {}",
                        traceback.format_exc(limit=1))
                errors = True

            if errors:
                if await self.config.print():
                    self.utils.log("check failed")
            else:
                await self.config.last_succeeded.set(this_check_time.timestamp())
                if await self.config.print():
                    self.utils.log("check complete")
            await self.config.last_checked.set(this_check_time.timestamp())
            await asyncio.sleep(30)

    async def get_quoted_post(self, qpost):
        html = qpost["com"]
        soup = BeautifulSoup(html, "html.parser")
        reference_post = []
        for a in soup.find_all("a", href=True):
            try:
                url = a["href"].split("#")[0].replace("html", "json")
                post_id = int(a["href"].split("#")[1])
            except:
                continue
            async with self.session.get(self.url + url) as resp:
                data = await resp.json()
            for post in data["posts"]:
                if post["no"] == post_id:
                    reference_post.append(post)
        return reference_post

    # @commands.command(pass_context=True)
    async def postq(self, qpost, board, is_edit=False):
        name = qpost["name"] if "name" in qpost else "Anonymous"
        url = "{}/{}/res/{}.html#{}".format(self.url, board, qpost["resto"], qpost["no"])
        timestamp = datetime.utcfromtimestamp(qpost["time"])

        log = await self.config.print()
        if log:
            status = 'New'
            if is_edit: status = 'Edited'
            self.utils.log('{} Q: {}, {}',
                    status,
                    timestamp.strftime('%Y-%m-%d %H:%M:%S'),
                    url)

        html = qpost["com"]
        soup = BeautifulSoup(html, "html.parser")
        ref_text = ""
        text = ""
        img_url = ""
        reference = await self.get_quoted_post(qpost)
        if qpost["com"] != "<p class=\"body-line empty \"></p>":
            for p in soup.find_all("p"):
                if p.get_text() is None:
                    text += "."
                else:
                    text += p.get_text() + "\n"
        if reference != []:
            for post in reference:
                # print(post)
                ref_html = post["com"]
                soup_ref = BeautifulSoup(ref_html, "html.parser")
                for p in soup_ref.find_all("p"):
                    if p.get_text() is None:
                        ref_text += "."
                    else:
                        ref_text += p.get_text() + "\n"
            if "tim" in reference[0] and "tim" not in qpost:
                file_id = reference[0]["tim"]
                file_ext = reference[0]["ext"]
                img_url = "https://media.8kun.top/file_store/{}{}".format(file_id, file_ext)
                await self.save_q_files(reference[0])
        if "tim" in qpost:
            file_id = qpost["tim"]
            file_ext = qpost["ext"]
            img_url = "https://media.8kun.top/file_store/{}{}".format(file_id, file_ext)
            await self.save_q_files(qpost)

        em = discord.Embed(colour=discord.Colour.red())
        em.set_author(name=name + qpost["trip"], url=url)
        em.timestamp = timestamp
        if text != "":
            if text.count("_") > 2 or text.count("~") > 2 or text.count("*") > 2:
                em.description = "```\n{}```".format(text[:1990])
            else:
                em.description = text[:1900]
        else:
            em.description = qpost["com"]

        if ref_text != "":
            if ref_text.count("_") > 2 or ref_text.count("~") > 2 or ref_text.count("*") > 2:
                em.add_field(name=str(post["no"]), value="```{}```".format(ref_text[:1000]))
            else:
                em.add_field(name=str(post["no"]), value=ref_text[:1000])
        if img_url != "":
            em.set_image(url=img_url)
            try:
                tw_msg = "{}\n#QAnon\n{}".format(url, text)
                await self.send_tweet(tw_msg[:280], "data/qposts/files/{}{}".format(file_id, file_ext))
            except Exception as e:
                print(f"Error sending tweet with image: {e}")
                pass
        else:
            try:
                tw_msg = "{}\n#QAnon\n{}".format(url, text)
                await self.send_tweet(tw_msg[:280])
            except Exception as e:
                print(f"Error sending tweet: {e}")
                pass
        if is_edit:
            em.set_footer(text="/{}/ (EDIT)".format(board))
        else:
            em.set_footer(text="/{}/".format(board))

        for channel_id in await self.config.channels():
            try:
                channel = self.bot.get_channel(id=channel_id)
            except Exception as e:
                print(f"Error getting the qchannel: {e}")
                continue
            if channel is None:
                continue
            guild = channel.guild
            if not channel.permissions_for(guild.me).send_messages:
                continue
            if not channel.permissions_for(guild.me).embed_links:
                await channel.send(text[:1900])
            try:
                post_timestamp = timestamp.strftime('%H:%M:%S')
                now_timestamp = datetime.now(timezone.utc).strftime('%H:%M:%S')
                timestamps_str = "Q/{} bot/{}".format(
                        post_timestamp,
                        now_timestamp)
                role = "".join(role.mention for role in guild.roles if role.name == "QPOSTS")
                if role != "":
                    role += " "
                await channel.send("{}<{}> {}".format(role, url, timestamps_str), embed=em)
                if log:
                    self.utils.log('Posted Q: {}, {}',
                            post_timestamp,
                            url)
            except Exception as e:
                print(f"Error posting Qpost in {channel_id}: {e}")


    async def q_menu(self, ctx, post_list: list, board,
                         message: discord.Message=None,
                         page=0, timeout: int=30):
        """menu control logic for this taken from
           https://github.com/Lunar-Dust/Dusty-Cogs/blob/master/menu/menu.py"""

        qpost = post_list[page]
        em = discord.Embed(colour=discord.Colour.red())
        name = qpost["name"] if "name" in qpost else "Anonymous"
        url = "{}/{}/res/{}.html#{}".format(self.url, board, qpost["resto"], qpost["no"])
        em.set_author(name=name + qpost["trip"], url=url)
        em.timestamp = datetime.utcfromtimestamp(qpost["time"])
        html = qpost["com"]
        soup = BeautifulSoup(html, "html.parser")
        text = ""
        for p in soup.find_all("p"):
            if p.get_text() is None:
                text += "."
            else:
                text += p.get_text() + "\n"
        em.description = "```{}```".format(text[:1800])
        reference = await self.get_quoted_post(qpost)
        if reference != []:
            for post in reference:
                # print(post)
                ref_html = post["com"]
                soup_ref = BeautifulSoup(ref_html, "html.parser")
                ref_text = ""
                for p in soup_ref.find_all("p"):
                    if p.get_text() is None:
                        ref_text += "."
                    else:
                        ref_text += p.get_text() + "\n"
                em.add_field(name=str(post["no"]), value="```{}```".format(ref_text[:1000]))
            if "tim" in post and "tim" not in qpost:
                file_id = post["tim"]
                file_ext = post["ext"]
                img_url = "https://media.8kun.top/file_store/{}{}".format(file_id, file_ext)
                if file_ext in [".png", ".jpg", ".jpeg"]:
                    em.set_image(url=img_url)
        em.set_footer(text="/{}/".format(board))
        if "tim" in qpost:
            file_id = qpost["tim"]
            file_ext = qpost["ext"]
            img_url = "https://media.8kun.top/file_store/{}{}".format(file_id, file_ext)
            if file_ext in [".png", ".jpg", ".jpeg"]:
                em.set_image(url=img_url)
        if not message:
            message = await ctx.send(embed=em)
            await message.add_reaction("⬅")
            await message.add_reaction("❌")
            await message.add_reaction("➡")
        else:
            # message edits don't return the message object anymore lol
            await message.edit(embed=em)
        check = lambda react, user:user == ctx.message.author and react.emoji in ["➡", "⬅", "❌"]
        try:
            react, user = await self.bot.wait_for("reaction_add", check=check, timeout=timeout)
        except asyncio.TimeoutError:
            await message.remove_reaction("⬅", self.bot.user)
            await message.remove_reaction("❌", self.bot.user)
            await message.remove_reaction("➡", self.bot.user)
            return None
        else:
            reacts = {v: k for k, v in numbs.items()}
            react = reacts[react.emoji]
            if react == "next":
                next_page = 0
                if page == len(post_list) - 1:
                    next_page = 0  # Loop around to the first item
                else:
                    next_page = page + 1
                try:
                    await message.remove_reaction("➡", ctx.message.author)
                except:
                    pass
                return await self.q_menu(ctx, post_list, board, message=message,
                                             page=next_page, timeout=timeout)
            elif react == "back":
                next_page = 0
                if page == 0:
                    next_page = len(post_list) - 1  # Loop around to the last item
                else:
                    next_page = page - 1
                try:
                    await message.remove_reaction("⬅", ctx.message.author)
                except:
                    pass
                return await self.q_menu(ctx, post_list, board, message=message,
                                             page=next_page, timeout=timeout)
            else:
                return await message.delete()

    @commands.command(pass_context=True, aliases=["postq"])
    async def qpost(self, ctx, board="qresearch"):
        """Display latest qpost from specified board"""
        if board not in await self.config.boards():
            await ctx.send("{} is not an available board!".format(board))
            return
        qposts = await self.config.boards()
        qposts = list(reversed(qposts[board]))
        await self.q_menu(ctx, qposts, board)

    @commands.command()
    async def qprint(self, ctx):
        """Toggle printing to the console"""
        if await self.config.print():
            await self.config.print.set(False)
            await ctx.send("Printing off.")
        else:
            await self.config.print.set(True)
            await ctx.send("Printing on.")

    async def save_q_files(self, post):
        try:
            file_id = post["tim"]
            file_ext = post["ext"]

            file_path =  cog_data_path(self) /"files"
            file_path.mkdir(exist_ok=True, parents=True)
            url = "https://media.8kun.top/file_store/{}{}".format(file_id, file_ext)
            async with self.session.get(url) as resp:
                image = await resp.read()
            with open(str(file_path) + "/{}{}".format(file_id, file_ext), "wb") as out:
                out.write(image)
            if "extra_files" in post:
                for file in post["extra_files"]:
                    file_id = file["tim"]
                    file_ext = file["ext"]
                    url = "https://media.8kun.top/file_store/{}{}".format(file_id, file_ext)
                    async with self.session.get(url) as resp:
                        image = await resp.read()
                    with open(str(file_path) + "/{}{}".format(file_id, file_ext), "wb") as out:
                        out.write(image)
        except Exception as e:
            print(f"Error saving files: {e}")
            pass

    @commands.command(pass_context=True)
    async def qchannel(self, ctx, channel:discord.TextChannel=None):
        """Set the channel for live qposts"""
        if channel is None:
            channel = ctx.message.channel
        guild = ctx.message.guild
        cur_chans = await self.config.channels()
        if channel.id in cur_chans:
            await ctx.send("{} is already posting new Q posts!".format(channel.mention))
            return
        else:
            cur_chans.append(channel.id)
        await self.config.channels.set(cur_chans)
        await ctx.send("{} set for qposts!".format(channel.mention))

    @commands.command(pass_context=True)
    async def remqchannel(self, ctx, channel:discord.TextChannel=None):
        """Remove qpost updates from a channel"""
        if channel is None:
            channel = ctx.message.channel
        guild = ctx.message.guild
        cur_chans = await self.config.channels()
        if channel.id not in cur_chans:
            await ctx.send("{} is not posting new Q posts!".format(channel.mention))
            return
        else:
            cur_chans.remove(channel.id)
        await self.config.channels.set(cur_chans)
        await ctx.send("{} set for qposts!".format(channel.mention))

    @commands.command(name='qtwitterset')
    @checks.is_owner()
    async def set_creds(self, ctx, consumer_key: str, consumer_secret: str, access_token: str, access_secret: str):
        """Set automatic twitter updates alongside discord"""
        api = {'consumer_key': consumer_key, 'consumer_secret': consumer_secret,
            'access_token': access_token, 'access_secret': access_secret}
        await self.config.twitter.set(api)
        await ctx.send('Set the access credentials!')

    def __unload(self):
        self.bot.loop.create_task(self.session.close())

    __del__ = __unload
