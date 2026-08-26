import datetime
import aiohttp
import discord
from discord import app_commands
from discord.ext import commands, tasks

# ==================== 設定區 (請修改這裡) ====================
TWITCH_CLIENT_ID = "29eqw6f4o3palij1j02i81lf28jche"  # 你的 Twitch Client ID
TWITCH_CLIENT_SECRET = "ks7hcha13daaoap5pj2v3t7j5hrdow"  # 貼上你的 Twitch Client Secret
TWITCH_CHANNEL_NAME = "niyaa0123"  # 主播 Twitch 帳號

ANNOUNCE_CHANNEL_ID = 1507590474599235656  # 貼上 Discord 公告頻道 ID
# ============================================================


# 建立底部按鈕介面（對應圖片最下方的按鈕風格）
class StreamView(discord.ui.View):

    def __init__(self, channel_name):
        super().__init__(timeout=None)
        stream_url = f"https://www.twitch.tv/{channel_name}"
        # 第一個按鈕：前往 Twitch 直播
        self.add_item(
            discord.ui.Button(
                label="前往 Twitch 頻道",
                url=stream_url,
                emoji="🔴",
                style=discord.ButtonStyle.link,
            )
        )
        # 第二個按鈕：Discord 連結（可自行更換）
        self.add_item(
            discord.ui.Button(
                label="加入霓夜的社群",
                url="https://discord.gg/你的邀請連結",
                emoji="💬",
                style=discord.ButtonStyle.link,
            )
        )


class StreamCog(commands.Cog):

    def __init__(self, bot):
        self.bot = bot
        self.access_token = None
        self.is_live = False
        self.last_msg_id = None  # 記錄已發送的開台卡片 ID，用來做即時編輯
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

    @tasks.loop(minutes=1.5)  # 每 90 秒自動向 Twitch 抓取最新數據
    async def check_twitch_live(self):
        if not TWITCH_CLIENT_ID or TWITCH_CLIENT_ID == "YOUR_TWITCH_CLIENT_ID":
            return

        if not self.access_token:
            await self.get_twitch_token()

        url = f"https://api.twitch.tv/helix/streams?user_login={TWITCH_CHANNEL_NAME}"
        headers = {
            "Client-ID": TWITCH_CLIENT_ID,
            "Authorization": f"Bearer {self.access_token}",
        }

        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as resp:
                if resp.status == 401:
                    await self.get_twitch_token()
                    return

                if resp.status == 200:
                    data = await resp.json()
                    streams = data.get("data", [])

                    # 1. 剛剛開台：發送新公告卡片
                    if streams and not self.is_live:
                        self.is_live = True
                        await self.send_stream_notice(streams[0])

                    # 2. 持續開台中：動態編輯舊卡片，即時更新人數、分類與開台時長
                    elif streams and self.is_live:
                        await self.update_stream_notice(streams[0])

                    # 3. 關台：將卡片轉為灰色停播狀態
                    elif not streams and self.is_live:
                        self.is_live = False
                        await self.handle_stream_offline()

    @check_twitch_live.before_loop
    async def before_check(self):
        await self.bot.wait_until_ready()

    # 發送全新的開台通知卡片
    async def send_stream_notice(self, stream_data):
        channel = self.bot.get_channel(ANNOUNCE_CHANNEL_ID)
        if not channel:
            return

        embed = self.build_embed(stream_data)
        view = StreamView(TWITCH_CHANNEL_NAME)
        stream_url = f"https://www.twitch.tv/{TWITCH_CHANNEL_NAME}"

        msg = await channel.send(
            content=f"@everyone\n準備狗叫啦~ {stream_url}", embed=embed, view=view
        )
        self.last_msg_id = msg.id

    # 動態更新舊卡片（編輯人數、分類與時長）
    async def update_stream_notice(self, stream_data):
        channel = self.bot.get_channel(ANNOUNCE_CHANNEL_ID)
        if not channel or not self.last_msg_id:
            return

        try:
            msg = await channel.fetch_message(self.last_msg_id)
            new_embed = self.build_embed(stream_data)
            view = StreamView(TWITCH_CHANNEL_NAME)
            await msg.edit(embed=new_embed, view=view)
        except Exception:
            pass  # 若訊息被手動刪除則忽略錯誤

    # 封裝 Embed 卡片：完美移植 FiveM 狀態面板外觀，但內容改為 Twitch 數據
    def build_embed(self, stream_data):
        title = stream_data.get("title", "霓夜開台囉！")
        game = stream_data.get("game_name", "未指定分類")
        viewers = stream_data.get("viewer_count", 0)
        started_at_str = stream_data.get("started_at")
        stream_url = f"https://www.twitch.tv/{TWITCH_CHANNEL_NAME}"
        thumb_url = f"https://static-cdn.jtvnw.net/previews-img/live_user_{TWITCH_CHANNEL_NAME}-1280x720.jpg"

        # 計算開台時長
        duration_str = "`0 hrs, 0 min`"
        if started_at_str:
            started_at = datetime.datetime.fromisoformat(
                started_at_str.replace("Z", "+00:00")
            )
            now = datetime.datetime.now(datetime.timezone.utc)
            duration_delta = now - started_at

            hours = int(duration_delta.total_seconds() // 3600)
            minutes = int((duration_delta.total_seconds() % 3600) // 60)
            duration_str = f"{hours} hrs, {minutes} mins"

        embed = discord.Embed(
            title="🌴 霓夜台 | 直播即時狀態",
            description=(
                f"歡迎來到霓夜的直播間！\n"
                f"**目前直播標題**：{title}\n"
                f"若有問題請在 Discord 反映"
            ),
            color=discord.Color.from_rgb(100, 65, 165),  # Twitch 紫色邊條
        )

        # 右上角小頭貼
        embed.set_thumbnail(url=thumb_url)

        # 仿造 FiveM 狀態面板的欄位配對
        embed.add_field(
            name="狀態", value="`🟢 正在直播中...`", inline=True
        )
        embed.add_field(
            name="線上觀眾", value=f"`{viewers} 人線上`", inline=True
        )

        embed.add_field(
            name="一鍵前往直播 (URL)",
            value=f"[`click to watch`]({stream_url})",
            inline=False,
        )

        embed.add_field(name="遊戲分類", value=f"`{game}`", inline=True)
        embed.add_field(name="開台時長", value=f"`{duration_str}`", inline=True)

        # 正下方大預覽圖
        embed.set_image(url=thumb_url)

        embed.set_footer(
            text=f"Streamcord 8.1.1 • Updated every minute • {datetime.datetime.now().strftime('%p %I:%M')}"
        )
        return embed

    # 關台時自動更新卡片狀態
    async def handle_stream_offline(self):
        channel = self.bot.get_channel(ANNOUNCE_CHANNEL_ID)
        if channel and self.last_msg_id:
            try:
                msg = await channel.fetch_message(self.last_msg_id)
                embed = msg.embeds[0]
                embed.title = "🌴 霓夜台 | 直播已結束"
                embed.description = "⚫ **直播已關閉，感謝大家的陪伴！**"
                embed.color = discord.Color.dark_gray()
                embed.clear_fields()
                await msg.edit(
                    content="💤 **霓夜已關台**", embed=embed, view=None
                )
            except Exception:
                pass

    # 管理員測試指令
    @app_commands.command(
        name="test_stream", description="測試的開台通知"
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def test_stream(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        channel = self.bot.get_channel(ANNOUNCE_CHANNEL_ID)
        if not channel:
            await interaction.followup.send(
                "❌ 找不到指定的公告頻道，請檢查 ANNOUNCE_CHANNEL_ID 設定！"
            )
            return

        stream_url = f"https://www.twitch.tv/{TWITCH_CHANNEL_NAME}"
        thumb_url = f"https://static-cdn.jtvnw.net/previews-img/live_user_{TWITCH_CHANNEL_NAME}-1280x720.jpg"

        embed = discord.Embed(
            title="🌴 霓夜台 | 直播即時狀態",
            description=(
                f"歡迎來到霓夜的直播間！\n"
                f"**目前直播標題**：[【測試】今天來跟大家聊天玩遊戲！]({stream_url})\n"
                f"若有問題請在 Discord 反映"
            ),
            color=discord.Color.from_rgb(100, 65, 165),
        )
        embed.set_thumbnail(url=thumb_url)
        embed.add_field(
            name="狀態", value="`🟢 正在直播中...`", inline=True
        )
        embed.add_field(name="線上觀眾", value="`100 人線上`", inline=True)
        embed.add_field(
            name="一鍵前往直播 (URL)",
            value=f"[`click to watch`]({stream_url})",
            inline=False,
        )
        embed.add_field(name="遊戲分類", value="`Just Chatting`", inline=True)
        embed.add_field(name="開台時長", value="`1 hrs, 15 mins`", inline=True)
        embed.set_image(url=thumb_url)
        embed.set_footer(
            text=f"Streamcord 8.1.1 • Updated every minute • {datetime.datetime.now().strftime('%p %I:%M')}"
        )

        view = StreamView(TWITCH_CHANNEL_NAME)
        await channel.send(
            content=f"@everyone\n準備狗叫啦~ {stream_url}", embed=embed, view=view
        )
        await interaction.followup.send(
            "✅ Twitch 測試卡片發送成功！"
        )


async def setup(bot):
    await bot.add_cog(StreamCog(bot))
