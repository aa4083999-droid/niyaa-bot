import datetime
import os
import aiohttp
import discord
from discord import app_commands
from discord.ext import commands, tasks

# ==================== 從環境變數讀取設定 ====================
TWITCH_CLIENT_ID = os.getenv("TWITCH_CLIENT_ID")
TWITCH_CLIENT_SECRET = os.getenv("TWITCH_CLIENT_SECRET")
TWITCH_CHANNEL_NAME = os.getenv("TWITCH_CHANNEL_NAME", "niyaa0123")

try:
    ANNOUNCE_CHANNEL_ID = int(os.getenv("ANNOUNCE_CHANNEL_ID", 0))
except ValueError:
    ANNOUNCE_CHANNEL_ID = 0

# 調試輸出環境變數狀態
print(f"🔍 TWITCH_CLIENT_ID: {'✅ 已設定' if TWITCH_CLIENT_ID else '❌ 未設定'}")
print(f"🔍 TWITCH_CLIENT_SECRET: {'✅ 已設定' if TWITCH_CLIENT_SECRET else '❌ 未設定'}")
print(f"🔍 ANNOUNCE_CHANNEL_ID: {'✅ 已設定' if ANNOUNCE_CHANNEL_ID != 0 else '❌ 未設定'}")

if not TWITCH_CLIENT_ID or not TWITCH_CLIENT_SECRET:
    raise ValueError("❌ 請在環境變數或 Secrets 中設定 TWITCH_CLIENT_ID 和 TWITCH_CLIENT_SECRET")
if ANNOUNCE_CHANNEL_ID == 0:
    raise ValueError("❌ 請在環境變數或 Secrets 中設定 ANNOUNCE_CHANNEL_ID")

print("✅ [Config] 環境變數已成功載入")
# ============================================================


class StreamView(discord.ui.View):
    def __init__(self, channel_name):
        super().__init__(timeout=None)
        stream_url = f"https://www.twitch.tv/{channel_name}"
        self.add_item(
            discord.ui.Button(
                label="前往 Twitch 觀看",
                url=stream_url,
                style=discord.ButtonStyle.link,
            )
        )


class StreamCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.access_token = None
        self.is_live = False
        self.last_msg_id = None
        self.check_twitch_live.start()

    def cog_unload(self):
        self.check_twitch_live.cancel()

    async def get_twitch_token(self):
        url = "https://id.twitch.tv/oauth2/token"
        params = {
            "client_id": TWITCH_CLIENT_ID,
            "client_secret": TWITCH_CLIENT_SECRET,
            "grant_type": "client_credentials",
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(url, params=params) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    self.access_token = data.get("access_token")
                    print(f"✅ [Token] 成功獲取 Twitch 訪問令牌")
                else:
                    print(f"❌ [Token] 獲取失敗: {resp.status}")

    @tasks.loop(minutes=1.5)
    async def check_twitch_live(self):
        if not self.access_token:
            await self.get_twitch_token()

        url = f"https://api.twitch.tv/helix/streams?user_login={TWITCH_CHANNEL_NAME}"
        headers = {
            "Client-ID": TWITCH_CLIENT_ID,
            "Authorization": f"Bearer {self.access_token}",
        }
        user_url = f"https://api.twitch.tv/helix/users?login={TWITCH_CHANNEL_NAME}"

        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as resp:
                if resp.status == 401:
                    print("⚠️ [Check] Token 過期，重新獲取...")
                    await self.get_twitch_token()
                    return

                if resp.status == 200:
                    data = await resp.json()
                    streams = data.get("data", [])

                    avatar_url = None
                    async with session.get(user_url, headers=headers) as user_resp:
                        if user_resp.status == 200:
                            user_data = await user_resp.json()
                            users = user_data.get("data", [])
                            if users:
                                avatar_url = users[0].get("profile_image_url")

                    if streams:
                        thumbnail_url = streams[0].get("thumbnail_url", "")
                        timestamp = int(datetime.datetime.now().timestamp())
                        
                        if thumbnail_url:
                            base_thumb_url = thumbnail_url.replace("{width}", "1280").replace("{height}", "720")
                            final_thumb_url = f"{base_thumb_url}?t={timestamp}"
                        else:
                            final_thumb_url = f"https://static-cdn.jtvnw.net/previews-img/live_user_{TWITCH_CHANNEL_NAME.lower()}-1280x720.jpg?t={timestamp}"

                        streams[0]["safe_thumb_url"] = final_thumb_url

                    if streams and not self.is_live:
                        self.is_live = True
                        await self.send_stream_notice(streams[0], avatar_url)
                    elif streams and self.is_live:
                        await self.update_stream_notice(streams[0], avatar_url)
                    elif not streams and self.is_live:
                        self.is_live = False
                        await self.handle_stream_offline()

    @check_twitch_live.before_loop
    async def before_check(self):
        await self.bot.wait_until_ready()
        print("✅ [Ready] Bot 已就緒，開始監控 Twitch...")

    async def send_stream_notice(self, stream_data, avatar_url):
        channel = self.bot.get_channel(ANNOUNCE_CHANNEL_ID)
        if not channel:
            return

        embed = self.build_embed_grid(stream_data, avatar_url)
        view = StreamView(TWITCH_CHANNEL_NAME)
        stream_url = f"https://www.twitch.tv/{TWITCH_CHANNEL_NAME}"

        try:
            msg = await channel.send(
                content=f"@everyone\n準備狗叫啦~\n<{stream_url}>", embed=embed, view=view
            )
            self.last_msg_id = msg.id
        except Exception as e:
            print(f"❌ [Send] 發送失敗: {e}")

    async def update_stream_notice(self, stream_data, avatar_url):
        channel = self.bot.get_channel(ANNOUNCE_CHANNEL_ID)
        if not channel or not self.last_msg_id:
            return

        try:
            msg = await channel.fetch_message(self.last_msg_id)
            new_embed = self.build_embed_grid(stream_data, avatar_url)
            view = StreamView(TWITCH_CHANNEL_NAME)
            await msg.edit(embed=new_embed, view=view)
        except discord.NotFound:
            self.is_live = False
            self.last_msg_id = None
            await self.send_stream_notice(stream_data, avatar_url)
        except Exception as e:
            print(f"❌ [Update] 更新失敗: {e}")

    def build_embed_grid(self, stream_data, avatar_url):
        title = stream_data.get("title", "霓夜開台囉！")
        game = stream_data.get("game_name", "未指定分類")
        viewers = stream_data.get("viewer_count", 0)
        started_at_str = stream_data.get("started_at")
        stream_url = f"https://www.twitch.tv/{TWITCH_CHANNEL_NAME}"
        
        duration_str = "0 hrs, 0 mins"
        if started_at_str:
            try:
                started_at = datetime.datetime.fromisoformat(
                    started_at_str.replace("Z", "+00:00")
                )
                now = datetime.datetime.now(datetime.timezone.utc)
                duration_delta = now - started_at

                hours = int(duration_delta.total_seconds() // 3600)
                minutes = int((duration_delta.total_seconds() % 3600) // 60)
                duration_str = f"{hours} hrs, {minutes} mins"
            except Exception as e:
                print(f"⚠️ [BuildEmbed] 時間轉換失敗: {e}")

        embed = discord.Embed(
            title="🌴 霓夜台 | 直播即時狀態",
            description=(
                f"歡迎來到霓夜的直播間！\n"
                f"**目前直播標題**：[{title}]({stream_url})\n"
                f"若有問題請在 Discord 反映"
            ),
            color=discord.Color.from_rgb(100, 65, 165),
        )

        if avatar_url:
            embed.set_author(name=f"{TWITCH_CHANNEL_NAME} is now live on Twitch!", icon_url=avatar_url)
        else:
            embed.set_author(name=f"{TWITCH_CHANNEL_NAME} is now live on Twitch!")

        left_column = f"🟢 正在直播中...\n👥 觀看人數：**{viewers} 人**"
        right_column = f"🎮 **{game}**\n⏱️ 開台時長：**{duration_str}**"

        embed.add_field(name="直播資訊", value=left_column, inline=True)
        embed.add_field(name="遊戲與時長", value=right_column, inline=True)

        thumb_url = stream_data.get("safe_thumb_url", avatar_url)
        if thumb_url:
            embed.set_image(url=thumb_url)

        embed.set_footer(text=f"streamcord.io • Updated every minute • {datetime.datetime.now().strftime('%p %I:%M')}")
        return embed

    async def handle_stream_offline(self):
        channel = self.bot.get_channel(ANNOUNCE_CHANNEL_ID)
        if channel and self.last_msg_id:
            try:
                msg = await channel.fetch_message(self.last_msg_id)
                embed = discord.Embed(
                    title="🌴 霓夜台 | 直播已結束",
                    description="⚫ **直播已關閉，感謝大家的陪伴！**",
                    color=discord.Color.dark_gray(),
                )
                embed.set_footer(text=f"streamcord.io • {datetime.datetime.now().strftime('%p %I:%M')}")
                await msg.edit(content="💤 **霓夜已關台**", embed=embed, view=None)
            except Exception as e:
                print(f"❌ [Offline] 關台更新失敗: {e}")

    @app_commands.command(
        name="test_stream", description="測試開台通知卡片 (抓取目前真實的實況狀態)"
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def test_stream(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        channel = self.bot.get_channel(ANNOUNCE_CHANNEL_ID)
        if not channel:
            await interaction.followup.send("❌ 找不到指定的公告頻道，請檢查 ANNOUNCE_CHANNEL_ID 設定！")
            return

        if not self.access_token:
            await self.get_twitch_token()

        url = f"https://api.twitch.tv/helix/streams?user_login={TWITCH_CHANNEL_NAME}"
        headers = {
            "Client-ID": TWITCH_CLIENT_ID,
            "Authorization": f"Bearer {self.access_token}",
        }
        user_url = f"https://api.twitch.tv/helix/users?login={TWITCH_CHANNEL_NAME}"

        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as resp:
                streams = (await resp.json()).get("data", []) if resp.status == 200 else []

            avatar_url = None
            async with session.get(user_url, headers=headers) as user_resp:
                if user_resp.status == 200:
                    users = (await user_resp.json()).get("data", [])
                    if users:
                        avatar_url = users[0].get("profile_image_url")

        if not streams:
            await interaction.followup.send("⚠️ **目前 Twitch API 顯示未開台**")
            return

        stream_data = streams[0]
        thumbnail_url = stream_data.get("thumbnail_url", "")
        timestamp = int(datetime.datetime.now().timestamp())
        
        if thumbnail_url:
            base_thumb_url = thumbnail_url.replace("{width}", "1280").replace("{height}", "720")
            stream_data["safe_thumb_url"] = f"{base_thumb_url}?t={timestamp}"
        else:
            stream_data["safe_thumb_url"] = f"https://static-cdn.jtvnw.net/previews-img/live_user_{TWITCH_CHANNEL_NAME.lower()}-1280x720.jpg?t={timestamp}"

        embed = self.build_embed_grid(stream_data, avatar_url)
        view = StreamView(TWITCH_CHANNEL_NAME)
        stream_url = f"https://www.twitch.tv/{TWITCH_CHANNEL_NAME}"

        await channel.send(
            content=f"@everyone\n準備狗叫啦~\n<{stream_url}>", embed=embed, view=view
        )
        await interaction.followup.send("✅ 測試卡片已成功發送至公告頻道！")


async def setup(bot):
    await bot.add_cog(StreamCog(bot))
