import asyncio
import io
import logging
import os
import discord
from discord import app_commands
from discord.ext import commands
from PIL import Image, ImageDraw, ImageFont

# 設定 logging 替代 print，方便 Railway 追蹤
logger = logging.getLogger("discord_bot.welcome")

# ==================== 設定區 ====================
WELCOME_CHANNEL_ID = 1507590474599235656  # 你的歡迎頻道 ID
DOG_BG_IMAGE_FILENAME = "welcome_background.jpg"
FONT_FILENAME = "font.ttc"
# ================================================


class WelcomeCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Semaphore 放在 Cog 內部，避免 Event Loop 綁定問題
        self.pillow_semaphore = asyncio.Semaphore(3)
        
        # 記憶體快取變數（包含實際的圖片 bytes 與字型物件）
        self._cached_background: bytes | None = None
        self._cached_font_title: ImageFont.FreeTypeFont | ImageFont.ImageFont | None = None
        self._cached_font_sub: ImageFont.FreeTypeFont | ImageFont.ImageFont | None = None

        # 初始化時載入資產並建立快取
        self._load_assets()

    def _load_assets(self):
        """在啟動時載入背景與字型至記憶體中，避免每次重複讀取"""
        current_dir = os.path.dirname(os.path.abspath(__file__))
        root_dir = os.path.dirname(current_dir)
        
        bg_path = os.path.join(root_dir, DOG_BG_IMAGE_FILENAME)
        font_path_zh = os.path.join(root_dir, FONT_FILENAME)

        # 1. 快取背景圖片 bytes
        try:
            if os.path.exists(bg_path):
                with open(bg_path, "rb") as f:
                    self._cached_background = f.read()
                logger.info("已成功快取歡迎卡片背景圖片。")
            else:
                logger.warning(f"找不到背景圖片檔案: {bg_path}")
        except Exception as e:
            logger.error(f"載入背景圖片時發生錯誤: {e}", exc_info=True)

        # 2. 預先建立字型物件快取
        try:
            if os.path.exists(font_path_zh):
                self._cached_font_title = ImageFont.truetype(font_path_zh, 32)
                self._cached_font_sub = ImageFont.truetype(font_path_zh, 22)
                logger.info("已成功建立字型物件快取。")
            else:
                logger.warning(f"找不到字型檔案: {font_path_zh}，將使用預設字型。")
                self._cached_font_title = ImageFont.load_default()
                self._cached_font_sub = ImageFont.load_default()
        except Exception as e:
            logger.error(f"載入字型時發生錯誤: {e}", exc_info=True)
            self._cached_font_title = ImageFont.load_default()
            self._cached_font_sub = ImageFont.load_default()

    def _generate_card_sync(self, avatar_bytes: bytes, display_name: str) -> bytes:
        """使用 Pillow 進行同步的圖片合成工作（在背景執行緒中執行）"""
        width, height = 800, 400

        # 1. 載入背景（使用記憶體快取）
        if self._cached_background:
            try:
                with Image.open(io.BytesIO(self._cached_background)) as bg:
                    base_img = bg.convert("RGBA")
                    base_img = base_img.resize((width, height), Image.Resampling.LANCZOS)
            except Exception:
                base_img = Image.new("RGBA", (width, height), (30, 30, 45, 255))
        else:
            base_img = Image.new("RGBA", (width, height), (30, 30, 45, 255))

        # 加上一層半透明黑色遮罩
        overlay = Image.new("RGBA", (width, height), (0, 0, 0, 100))
        card = Image.alpha_composite(base_img, overlay)

        # 2. 處理使用者大頭貼（若有 avatar_bytes 則畫成圓形）
        if avatar_bytes:
            try:
                with Image.open(io.BytesIO(avatar_bytes)) as avatar_img:
                    avatar_img = avatar_img.convert("RGBA")
                    avatar_img = avatar_img.resize((150, 150), Image.Resampling.LANCZOS)

                    # 製作圓形遮罩
                    mask = Image.new("L", (150, 150), 0)
                    draw_mask = ImageDraw.Draw(mask)
                    draw_mask.ellipse((0, 0, 150, 150), fill=255)

                    # 貼上圓形頭貼
                    avatar_x, avatar_y = (width - 150) // 2, 45
                    card.paste(avatar_img, (avatar_x, avatar_y), mask)

                    # 加上外框
                    draw = ImageDraw.Draw(card)
                    draw.ellipse(
                        (
                            avatar_x - 5,
                            avatar_y - 5,
                            avatar_x + 150 + 5,
                            avatar_y + 150 + 5,
                        ),
                        outline=(100, 255, 218),
                        width=8,
                    )
            except Exception as e:
                logger.warning(f"處理頭貼繪製時發生錯誤: {e}")

        # 3. 寫入文字
        draw = ImageDraw.Draw(card)
        font_title = self._cached_font_title or ImageFont.load_default()
        font_sub = self._cached_font_sub or ImageFont.load_default()

        # 長暱稱限制，避免排版超出範圍
        if len(display_name) > 25:
            display_name = display_name[:25] + "..."

        # 歡迎文字
        text_welcome = f"歡迎 {display_name} 狗勾"
        bbox_title = draw.textbbox((0, 0), text_welcome, font=font_title)
        w_title = bbox_title[2] - bbox_title[0]
        draw.text(
            ((width - w_title) / 2, 215),
            text_welcome,
            fill=(255, 255, 255),
            font=font_title,
            stroke_width=3,
            stroke_fill=(0, 0, 0),
        )

        # 副標題
        text_sub = "期待你在霓夜的狗窩裡玩得開心！"
        bbox_sub = draw.textbbox((0, 0), text_sub, font=font_sub)
        w_sub = bbox_sub[2] - bbox_sub[0]
        draw.text(
            ((width - w_sub) / 2, 270),
            text_sub,
            fill=(255, 230, 100),
            font=font_sub,
            stroke_width=2,
            stroke_fill=(0, 0, 0),
        )

        output = io.BytesIO()
        card.save(output, format="PNG")
        output.seek(0)
        return output.getvalue()

    async def _get_welcome_channel(self) -> discord.abc.Messageable | None:
        """取得歡迎頻道，檢查型態並支援 API Fallback（帶 30 秒超時保護）"""
        channel = self.bot.get_channel(WELCOME_CHANNEL_ID)
        if channel is None:
            try:
                channel = await asyncio.wait_for(
                    self.bot.fetch_channel(WELCOME_CHANNEL_ID), timeout=30.0
                )
            except Exception as e:
                logger.error(f"無法透過 API 取得歡迎頻道 {WELCOME_CHANNEL_ID}: {e}")
                return None

        # 檢查頻道型態是否支援傳送訊息
        if not isinstance(channel, (discord.TextChannel, discord.Thread, discord.VoiceChannel)):
            logger.error(f"取得的頻道 ID {WELCOME_CHANNEL_ID} 不是支援訊息發送的頻道型態。")
            return None

        return channel

    async def send_welcome_process(self, member: discord.Member) -> bool:
        """核心歡迎卡片生成與發送流程，成功回傳 True，失敗回傳 False"""
        channel = await self._get_welcome_channel()
        if not channel:
            logger.error("找不到可用的歡迎頻道，無法發送歡迎訊息。")
            return False

        intro_text = f"{member.mention}，歡迎來到 **霓夜的狗窩** 😍\n"

        # 頭貼下載失敗降級處理：若失敗或逾時，avatar_bytes 設為 b"" 繼續流程
        avatar_bytes = b""
        try:
            avatar_asset = member.display_avatar.with_size(256)
            avatar_bytes = await asyncio.wait_for(avatar_asset.read(), timeout=15.0)
        except Exception as e:
            logger.warning(f"下載使用者 {member.id} 頭貼失敗或逾時（將以無頭貼模式繼續）: {e}")

        display_name = getattr(member, "display_name", member.name)

        try:
            # 透過 Semaphore 限制併發，並使用 to_thread 避免阻塞 Event Loop
            async with self.pillow_semaphore:
                card_bytes = await asyncio.to_thread(
                    self._generate_card_sync, avatar_bytes, display_name
                )
        except Exception as e:
            logger.error(f"圖片合成過程發生錯誤: {e}", exc_info=True)
            return False

        file = discord.File(io.BytesIO(card_bytes), filename="welcome_card.png")

        # 傳送訊息超時保護：最多等待 30 秒
        try:
            await asyncio.wait_for(
                channel.send(content=intro_text, file=file),
                timeout=30.0
            )
            logger.info(f"成功發送歡迎卡片給成員: {display_name} ({member.id})")
            return True
        except Exception as e:
            logger.error(f"發送歡迎訊息失敗或逾時: {e}", exc_info=True)
            return False

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        await self.send_welcome_process(member)

    @app_commands.command(
        name="test_welcome", description="測試精美圖片歡迎卡片 (僅限管理員)"
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def test_welcome(self, interaction: discord.Interaction):
        # 1. 一定要先 defer，避免 Discord 3 秒互動逾時
        await interaction.response.defer(ephemeral=True)

        channel = await self._get_welcome_channel()
        if not channel:
            await interaction.followup.send(
                "❌ 找不到設定的歡迎頻道 ID，或該頻道不支援訊息發送！", ephemeral=True
            )
            return

        # 2. 確保取得完整的 discord.Member
        member = interaction.user
        if interaction.guild and not isinstance(member, discord.Member):
            try:
                member = await asyncio.wait_for(
                    interaction.guild.fetch_member(interaction.user.id), timeout=10.0
                )
            except Exception as e:
                logger.warning(f"無法取得完整的 Member 物件，退回使用互動使用者: {e}")

        # 3. 執行測試發送並根據結果回報
        success = await self.send_welcome_process(member)
        
        if success:
            await interaction.followup.send(
                "✅ 測試歡迎卡片已成功發送到指定的歡迎頻道！", ephemeral=True
            )
        else:
            await interaction.followup.send(
                "❌ 測試歡迎卡片發送失敗，請檢查 Railway Logs 詳細記錄。", ephemeral=True
            )


async def setup(bot):
    await bot.add_cog(WelcomeCog(bot))
