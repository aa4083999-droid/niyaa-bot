import datetime
import aiohttp
import discord
from discord import app_commands
from discord.ext import commands, tasks

# ==================== 設定區 (請修改這裡) ====================
TWITCH_CLIENT_ID = "29eqw6f4o3palij1j02i81lf28jche"  # 你的 Twitch Client ID
TWITCH_CLIENT_SECRET = "93pkcfspisoyllmibm3srt3bg52bv0"  # 你的 Twitch Client Secret
TWITCH_CHANNEL_NAME = "niyaa0123"  # 主播 Twitch 帳號

ANNOUNCE_CHANNEL_ID = 1507590474599235656  # Discord 公告頻道 ID
# ============================================================


# 仿照 Streamcord 風格的底部按鈕
class StreamView(discord.ui.View):
    def __init__(self, channel_name):
        super().__init__(timeout=None)
        stream_url = f"https://www.twitch.tv/{channel_name}"
        self.add_item(
            discord.ui.Button(
                label="Watch Stream",
                url=stream_url,
                style=discord.ButtonStyle.link,
            )
        )


class StreamCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.access_token = None
        self.is_live = False
        self.last_msg_id = None  # 記錄開台訊息 ID，用來做動態更新
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

    @tasks.loop(minutes=1.5)  # 每 90 秒檢查一次 Twitch 直播狀態
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
        user_url = f"https://api.twitch.tv/helix/users?login={TWITCH_CHANNEL_NAME}"

        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as resp:
                if resp.status == 401:
                    await self.get_twitch_token()
                    return

                if resp.status == 200:
                    data = await resp.json()
                    streams = data.get("data", [])

                    # 取得用戶頭貼
                    avatar_url = None
                    async with session.get(user_url, headers=headers) as user_resp:
                        if user_resp.status == 200:
                            user_data = await user_resp.json()
                            users = user_data.get("data", [])
                            if users:
                                avatar_url = users[0].get("profile_image_url")

                    if streams:
                        # 🌟 智慧防護：直接使用 API 的預覽圖並替換解析度，加上時間戳強制刷新快取
                        thumbnail_url = streams[0].get("thumbnail_url", "")
                        timestamp = int(datetime.datetime.now().timestamp())
                        
                        if thumbnail_url:
                            # 替換 Twitch API 回傳的 {width} 和 {height} 為標準 16:9 解析度
                            base_thumb_url = thumbnail_url.replace("{width}", "1280").replace("{height}", "720")
                            final_thumb_url = f"{base_thumb_url}?t={timestamp}"
                        else:
                            # 防呆機制：直接拼接圖片網址
                            final_thumb_url = f"https://static-cdn.jtvnw.net/previews-img/live_user_{TWITCH_CHANNEL_NAME.lower()}-1280x720.jpg?t={timestamp}"

                        streams[0]["safe_thumb_url"] = final_thumb_url

                    # 1. 剛剛開台：發送新公告
                    if streams and not self.is_live:
                        self.is_live = True
                        await self.send_stream_notice(streams[0], avatar_url)

                    # 2. 持續開台中：即時更新數據與預覽圖
                    elif streams and self.is_live:
                        await self.update_stream_notice(streams[0], avatar_url)

                    # 3. 關台：將卡片轉為灰色停播狀態
                    elif not streams and self.is_live:
                        self.is_live = False
                        await self.handle_stream_offline()

    @check_twitch_live.before_loop
    async def before_check(self):
        await self.bot.wait_until_ready()

    # 發送全新的開台通知 (正式通知預設使用排版一：2x2 對稱佈局，你也可以隨時換成排版二)
    async def send_stream_notice(self, stream_data, avatar_url):
        channel = self.bot.get_channel(ANNOUNCE_CHANNEL_ID)
        if not channel:
            return

        embed = self.build_embed_grid(stream_data, avatar_url)
        view = StreamView(TWITCH_CHANNEL_NAME)
        stream_url = f"https://www.twitch.tv/{TWITCH_CHANNEL_NAME}"

        # 🌟 加上 < > 隱藏 Discord 預設的陽春網址預覽
        msg = await channel.send(
            content=f"@everyone\n準備狗叫啦~\n<{stream_url}>", embed=embed, view=view
        )
        self.last_msg_id = msg.id

    # 即時更新舊卡片數據
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
            print(f"更新失敗: {e}")

    # ==========================================
    # 🎨 排版一：2x2 對稱佈局 & 粗體放大 (正式通知使用此函數)
    # ==========================================
    def build_embed_grid(self, stream_data, avatar_url):
        title = stream_data.get("title", "霓夜開台囉！")
        game = stream_data.get("game_name", "未指定分類")
        viewers = stream_data.get("viewer_count", 0)
        started_at_str = stream_data.get("started_at")
        stream_url = f"https://www.twitch.tv/{TWITCH_CHANNEL_NAME}"
        
        # 計算開台時長
        duration_str = "0 hrs, 0 mins"
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
                f"**目前直播標題**：[{title}]({stream_url})\n"
                f"若有問題請在 Discord 反映"
            ),
            color=discord.Color.from_rgb(100, 65, 165),
        )

        if avatar_url:
            embed.set_author(name=f"{TWITCH_CHANNEL_NAME} is now live on Twitch!", icon_url=avatar_url)
        else:
            embed.set_author(name=f"{TWITCH_CHANNEL_NAME} is now live on Twitch!")

        # 2x2 對稱欄位
        embed.add_field(name="狀態", value="**🟢 正在直播中...**", inline=True)
        embed.add_field(name="線上觀眾", value=f"**👥 {viewers} 人**", inline=True)
        embed.add_field(name="\u200b", value="\u200b", inline=True)  # 隱形空白換行
        embed.add_field(name="遊戲分類", value=f"**🎮 {game}**", inline=True)
        embed.add_field(name="開台時長", value=f"**⏱️ {duration_str}**", inline=True)

        thumb_url = stream_data.get("safe_thumb_url", avatar_url)
        if thumb_url:
            embed.set_image(url=thumb_url)

        embed.set_footer(text=f"streamcord.io • Updated every minute • {datetime.datetime.now().strftime('%p %I:%M')}")
        return embed

    # 關台時更新
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
                await msg.edit(
                    content="💤 **霓夜已關台**", embed=embed, view=None
                )
            except Exception as e:
                print(f"關台更新失敗: {e}")

    # ==========================================
    # 管理員測試指令：同時發送兩種排版供比較
    # ==========================================
    @app_commands.command(
        name="test_stream", description="測試開台通知卡片 (同時發送兩種排版供比較)"
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def test_stream(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        channel = self.bot.get_channel(ANNOUNCE_CHANNEL_ID)
        if not channel:
            await interaction.followup.send("❌ 找不到指定的公告頻道，請檢查 ANNOUNCE_CHANNEL_ID 設定！")
            return

        stream_url = f"https://www.twitch.tv/{TWITCH_CHANNEL_NAME}"
        timestamp = int(datetime.datetime.now().timestamp())
        fake_thumb_url = f"https://static-cdn.jtvnw.net/previews-img/live_user_{TWITCH_CHANNEL_NAME.lower()}-1280x720.jpg?t={timestamp}"
        
        # 測試用的模擬文字資料
        title = "[霓夜Niya]0825 | 休假也好累 【歡迎追蹤|200追有抽獎|記得開5%🔊唷】"
        game = "VALORANT"
        viewers = 100
        duration_str = "1 hrs, 15 mins"

        # ------------------------------------------
        # 🎨 排版一：2x2 對稱佈局 & 粗體放大
        # ------------------------------------------
        embed1 = discord.Embed(
            title="🌴 霓夜台 | 直播即時狀態 (排版一：2x2 對稱格子)",
            description=(
                f"歡迎來到霓夜的直播間！\n"
                f"**目前直播標題**：[{title}]({stream_url})\n"
                f"若有問題請在 Discord 反映"
            ),
            color=discord.Color.from_rgb(100, 65, 165),
        )
        embed1.set_author(name=f"{TWITCH_CHANNEL_NAME} is now live on Twitch!")
        
        embed1.add_field(name="狀態", value="**🟢 正在直播中...**", inline=True)
        embed1.add_field(name="線上觀眾", value=f"**👥 {viewers} 人**", inline=True)
        embed1.add_field(name="\u200b", value="\u200b", inline=True)  # 隱形空白換行
        embed1.add_field(name="遊戲分類", value=f"**🎮 {game}**", inline=True)
        embed1.add_field(name="開台時長", value=f"**⏱️ {duration_str}**", inline=True)
        
        embed1.set_image(url=fake_thumb_url)
        embed1.set_footer(text=f"streamcord.io • {datetime.datetime.now().strftime('%p %I:%M')}")

        # ------------------------------------------
        # 🎨 排版二：Discord 原生 H3 大字體清單
        # ------------------------------------------
        embed2 = discord.Embed(
            title="🌴 霓夜台 | 直播即時狀態 (排版二：大字體清單)",
            description=(
                f"歡迎來到霓夜的直播間！\n"
                f"**目前直播標題**：[{title}]({stream_url})\n"
                f"若有問題請在 Discord 反映\n\n"
                f"### 🟢 狀態：正在直播中\n"
                f"### 👥 觀眾：{viewers} 人\n"
                f"### 🎮 遊戲：{game}\n"
                f"### ⏱️ 時長：{duration_str}"
            ),
            color=discord.Color.from_rgb(100, 65, 165),
        )
        embed2.set_author(name=f"{TWITCH_CHANNEL_NAME} is now live on Twitch!")
        embed2.set_image(url=fake_thumb_url)
        embed2.set_footer(text=f"streamcord.io • {datetime.datetime.now().strftime('%p %I:%M')}")

        # 發送兩則訊息到頻道讓您直接比較
        view1 = StreamView(TWITCH_CHANNEL_NAME)
        view2 = StreamView(TWITCH_CHANNEL_NAME)

        await channel.send(content=f"@everyone\n👇 **【測試排版一：對稱格子】**\n<{stream_url}>", embed=embed1, view=view1)
        await channel.send(content=f"@everyone\n👇 **【測試排版二：大字體清單】**\n<{stream_url}>", embed=embed2, view=view2)

        await interaction.followup.send("✅ 兩種排版都已經發送到公告頻道囉！請去頻道裡看看你比較喜歡哪一種！")


async def setup(bot):
    await bot.add_cog(StreamCog(bot))
