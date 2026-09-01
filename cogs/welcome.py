import asyncio
import io
import logging
import os
import re
import discord
from discord import app_commands
from discord.ext import commands
from PIL import Image, ImageDraw, ImageFont

# ==================== 日誌系統設置 ====================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ==================== 從環境變數讀取設定 ====================
WELCOME_CHANNEL_ID = int(os.getenv("WELCOME_CHANNEL_ID", 0))
MOD_CHANNEL_ID = int(os.getenv("MOD_CHANNEL_ID", 0))

# ==================== 資產配置 ====================
DOG_BG_IMAGE_FILENAME = "welcome_background.jpg"
FONT_FILENAME = "font.ttc"

# ==================== 禁用詞配置 ====================
BANNED_WORDS = [
    "badword1",
    "badword2",
    "inappropriate",
]
EXEMPT_USERS = []
EXEMPT_CHANNELS = []

# ==================== 全域配置變數 ====================
class ConfigManager:
    """配置管理器，允許動態修改頻道 ID"""
    _welcome_channel_id = WELCOME_CHANNEL_ID
    _mod_channel_id = MOD_CHANNEL_ID
    
    @classmethod
    def get_welcome_channel_id(cls) -> int:
        return cls._welcome_channel_id
    
    @classmethod
    def set_welcome_channel_id(cls, channel_id: int) -> None:
        cls._welcome_channel_id = channel_id
        logger.info(f"✅ 歡迎頻道 ID 已更新為：{channel_id}")
    
    @classmethod
    def get_mod_channel_id(cls) -> int:
        return cls._mod_channel_id
    
    @classmethod
    def set_mod_channel_id(cls, channel_id: int) -> None:
        cls._mod_channel_id = channel_id
        logger.info(f"✅ 日誌頻道 ID 已更新為：{channel_id}")


class ModerationCog(commands.Cog):
    """自動化管理系統 Cog"""
    
    def __init__(self, bot):
        self.bot = bot
        self.banned_words = [word.lower() for word in BANNED_WORDS]
        logger.info("✅ [Cog] ModerationCog 已載入")

    def is_word_in_text(self, text, word):
        text_lower = text.lower()
        pattern = r'\b' + re.escape(word) + r'\b'
        return re.search(pattern, text_lower) is not None

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author == self.bot.user or message.author.bot:
            return
        
        if message.channel.id in EXEMPT_CHANNELS or message.author.id in EXEMPT_USERS:
            return
        
        found_banned_word = None
        for word in self.banned_words:
            if self.is_word_in_text(message.content, word):
                found_banned_word = word
                break
        
        if found_banned_word:
            try:
                await message.delete()
                logger.warning(
                    f"❌ [Filter] {message.author} 在 #{message.channel.name} 使用了禁用詞: '{found_banned_word}'"
                )
                
                warning_embed = discord.Embed(
                    title="⚠️ 訊息已刪除",
                    description=f"{message.author.mention} 請注意用詞\n\n**原因**：使用了不適當的語言",
                    color=discord.Color.orange()
                )
                warning_embed.set_footer(text="如有疑問，請聯繫管理員")
                await message.channel.send(embed=warning_embed, delete_after=10)
                
                mod_channel_id = ConfigManager.get_mod_channel_id()
                if mod_channel_id != 0:
                    mod_channel = self.bot.get_channel(mod_channel_id)
                    if mod_channel:
                        log_embed = discord.Embed(
                            title="🚨 訊息過濾日誌",
                            description=f"**使用者**：{message.author.mention}\n"
                                        f"**頻道**：{message.channel.mention}\n"
                                        f"**違規詞**：`{found_banned_word}`\n"
                                        f"**原訊息**：{message.content[:100]}...",
                            color=discord.Color.red()
                        )
                        log_embed.set_footer(text=f"時間：{discord.utils.utcnow().strftime('%Y-%m-%d %H:%M:%S')}")
                        await mod_channel.send(embed=log_embed)
                        
            except discord.Forbidden:
                logger.error(f"❌ [Permission] 沒有權限刪除訊息（頻道：{message.channel.name}）")
            except Exception as e:
                logger.error(f"❌ [Error] 刪除訊息時出錯：{e}")

    @app_commands.command(name="set_welcome_channel", description="設定歡迎頻道（僅管理員可用）")
    @app_commands.checks.has_permissions(administrator=True)
    async def set_welcome_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        ConfigManager.set_welcome_channel_id(channel.id)
        embed = discord.Embed(
            title="✅ 歡迎頻道已設定",
            description=f"歡迎卡片將發送到：{channel.mention}",
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="set_mod_channel", description="設定日誌頻道（僅管理員可用）")
    @app_commands.checks.has_permissions(administrator=True)
    async def set_mod_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        ConfigManager.set_mod_channel_id(channel.id)
        embed = discord.Embed(
            title="✅ 日誌頻道已設定",
            description=f"違規訊息日誌將發送到：{channel.mention}",
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="add_ban_word", description="添加一個禁用詞（僅管理員可用）")
    @app_commands.checks.has_permissions(administrator=True)
    async def add_ban_word(self, interaction: discord.Interaction, word: str):
        word_lower = word.lower()
        if word_lower in self.banned_words:
            await interaction.response.send_message(f"⚠️ 禁用詞 `{word}` 已存在", ephemeral=True)
            return
        self.banned_words.append(word_lower)
        BANNED_WORDS.append(word)
        embed = discord.Embed(title="✅ 禁用詞已添加", description=f"成功添加禁用詞：`{word}`", color=discord.Color.green())
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="remove_ban_word", description="移除一個禁用詞（僅管理員可用）")
    @app_commands.checks.has_permissions(administrator=True)
    async def remove_ban_word(self, interaction: discord.Interaction, word: str):
        word_lower = word.lower()
        if word_lower not in self.banned_words:
            await interaction.response.send_message(f"⚠️ 禁用詞 `{word}` 不存在", ephemeral=True)
            return
        self.banned_words.remove(word_lower)
        BANNED_WORDS.remove(word)
        embed = discord.Embed(title="✅ 禁用詞已移除", description=f"成功移除禁用詞：`{word}`", color=discord.Color.green())
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="list_ban_words", description="顯示所有禁用詞（僅管理員可用）")
    @app_commands.checks.has_permissions(administrator=True)
    async def list_ban_words(self, interaction: discord.Interaction):
        if not self.banned_words:
            await interaction.response.send_message("ℹ️ 目前沒有禁用詞", ephemeral=True)
            return
        banned_list = ", ".join([f"`{word}`" for word in self.banned_words])
        embed = discord.Embed(title="📋 禁用詞列表", description=banned_list, color=discord.Color.blue())
        embed.set_footer(text=f"總計：{len(self.banned_words)} 個禁用詞")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="exempt_user", description="將使用者添加到豁免列表")
    @app_commands.checks.has_permissions(administrator=True)
    async def exempt_user(self, interaction: discord.Interaction, user: discord.User):
        if user.id in EXEMPT_USERS:
            await interaction.response.send_message(f"⚠️ {user.mention} 已在豁免列表中", ephemeral=True)
            return
        EXEMPT_USERS.append(user.id)
        embed = discord.Embed(title="✅ 使用者已豁免", description=f"{user.mention} 已添加到豁免列表", color=discord.Color.green())
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="exempt_channel", description="將頻道添加到豁免列表")
    @app_commands.checks.has_permissions(administrator=True)
    async def exempt_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        if channel.id in EXEMPT_CHANNELS:
            await interaction.response.send_message(f"⚠️ {channel.mention} 已在豁免列表中", ephemeral=True)
            return
        EXEMPT_CHANNELS.append(channel.id)
        embed = discord.Embed(title="✅ 頻道已豁免", description=f"{channel.mention} 已添加到豁免列表", color=discord.Color.green())
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="config_status", description="查看目前的配置狀態（僅管理員可用）")
    @app_commands.checks.has_permissions(administrator=True)
    async def config_status(self, interaction: discord.Interaction):
        welcome_id = ConfigManager.get_welcome_channel_id()
        mod_id = ConfigManager.get_mod_channel_id()
        embed = discord.Embed(title="⚙️ 配置狀態", color=discord.Color.blue())
        
        embed.add_field(
            name="歡迎頻道",
            value=f"<#{welcome_id}>" if welcome_id != 0 else "未設定",
            inline=False
        )
        embed.add_field(
            name="日誌頻道",
            value=f"<#{mod_id}>" if mod_id != 0 else "未設定",
            inline=False
        )
        embed.add_field(name="📋 禁用詞數量", value=f"{len(self.banned_words)} 個", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)


class WelcomeCog(commands.Cog):
    """歡迎卡片系統 Cog"""
    
    def __init__(self, bot):
        self.bot = bot
        self.pillow_semaphore = asyncio.Semaphore(3)
        self._cached_background: bytes | None = None
        self._cached_font_title: ImageFont.FreeTypeFont | ImageFont.ImageFont | None = None
        self._cached_font_sub: ImageFont.FreeTypeFont | ImageFont.ImageFont | None = None
        self._load_assets()
        logger.info("✅ [Cog] WelcomeCog 已載入")

    def _load_assets(self):
        root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        bg_path = os.path.join(root_dir, DOG_BG_IMAGE_FILENAME)
        font_path_zh = os.path.join(root_dir, FONT_FILENAME)

        try:
            if os.path.exists(bg_path):
                with open(bg_path, "rb") as f:
                    self._cached_background = f.read()
                logger.info("✅ 已成功快取歡迎卡片背景圖片")
        except Exception as e:
            logger.error(f"❌ 載入背景圖片時發生錯誤: {e}")

        try:
            if os.path.exists(font_path_zh):
                self._cached_font_title = ImageFont.truetype(font_path_zh, 32)
                self._cached_font_sub = ImageFont.truetype(font_path_zh, 22)
            else:
                self._cached_font_title = ImageFont.load_default()
                self._cached_font_sub = ImageFont.load_default()
        except Exception as e:
            logger.error(f"❌ 載入字型時發生錯誤: {e}")
            self._cached_font_title = ImageFont.load_default()
            self._cached_font_sub = ImageFont.load_default()

    def _generate_card_sync(self, avatar_bytes: bytes, display_name: str) -> bytes:
        width, height = 800, 400

        if self._cached_background:
            try:
                with Image.open(io.BytesIO(self._cached_background)) as bg:
                    base_img = bg.convert("RGBA").resize((width, height), Image.Resampling.LANCZOS)
            except Exception:
                base_img = Image.new("RGBA", (width, height), (30, 30, 45, 255))
        else:
            base_img = Image.new("RGBA", (width, height), (30, 30, 45, 255))

        overlay = Image.new("RGBA", (width, height), (0, 0, 0, 100))
        card = Image.alpha_composite(base_img, overlay)

        if avatar_bytes:
            try:
                with Image.open(io.BytesIO(avatar_bytes)) as avatar_img:
                    avatar_img = avatar_img.convert("RGBA").resize((150, 150), Image.Resampling.LANCZOS)
                    mask = Image.new("L", (150, 150), 0)
                    draw_mask = ImageDraw.Draw(mask)
                    draw_mask.ellipse((0, 0, 150, 150), fill=255)

                    avatar_x, avatar_y = (width - 150) // 2, 45
                    card.paste(avatar_img, (avatar_x, avatar_y), mask)

                    draw = ImageDraw.Draw(card)
                    draw.ellipse(
                        (avatar_x - 5, avatar_y - 5, avatar_x + 155, avatar_y + 155),
                        outline=(100, 255, 218),
                        width=8,
                    )
            except Exception as e:
                logger.warning(f"⚠️ 處理頭貼繪製時發生錯誤: {e}")

        draw = ImageDraw.Draw(card)
        font_title = self._cached_font_title or ImageFont.load_default()
        font_sub = self._cached_font_sub or ImageFont.load_default()

        if len(display_name) > 25:
            display_name = display_name[:25] + "..."

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
        welcome_channel_id = ConfigManager.get_welcome_channel_id()
        if welcome_channel_id == 0:
            return None
        
        channel = self.bot.get_channel(welcome_channel_id)
        if channel is None:
            try:
                channel = await asyncio.wait_for(self.bot.fetch_channel(welcome_channel_id), timeout=30.0)
            except Exception:
                return None

        return channel if isinstance(channel, (discord.TextChannel, discord.Thread, discord.VoiceChannel)) else None

    async def send_welcome_process(self, member: discord.Member) -> bool:
        channel = await self._get_welcome_channel()
        if not channel:
            return False

        intro_text = f"{member.mention}，歡迎來到 **霓夜的狗窩** 😍\n"
        avatar_bytes = b""
        try:
            avatar_asset = member.display_avatar.with_size(256)
            avatar_bytes = await asyncio.wait_for(avatar_asset.read(), timeout=15.0)
        except Exception as e:
            logger.warning(f"⚠️ 下載成員頭貼失敗: {e}")

        display_name = getattr(member, "display_name", member.name)

        try:
            async with self.pillow_semaphore:
                card_bytes = await asyncio.to_thread(self._generate_card_sync, avatar_bytes, display_name)
        except Exception as e:
            logger.error(f"❌ 圖片合成過程發生錯誤: {e}", exc_info=True)
            return False

        file = discord.File(io.BytesIO(card_bytes), filename="welcome_card.png")

        try:
            await asyncio.wait_for(channel.send(content=intro_text, file=file), timeout=30.0)
            logger.info(f"✅ 成功發送歡迎卡片給成員: {display_name} ({member.id})")
            return True
        except Exception as e:
            logger.error(f"❌ 發送歡迎訊息失敗: {e}", exc_info=True)
            return False

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        await self.send_welcome_process(member)

    @app_commands.command(name="test_welcome", description="測試精美圖片歡迎卡片 (僅限管理員)")
    @app_commands.checks.has_permissions(administrator=True)
    async def test_welcome(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        channel = await self._get_welcome_channel()
        if not channel:
            await interaction.followup.send("❌ 找不到設定的歡迎頻道，請使用 `/set_welcome_channel` 設定！", ephemeral=True)
            return

        member = interaction.user
        if interaction.guild and not isinstance(member, discord.Member):
            try:
                member = await asyncio.wait_for(interaction.guild.fetch_member(interaction.user.id), timeout=10.0)
            except Exception:
                pass

        success = await self.send_welcome_process(member)
        if success:
            await interaction.followup.send("✅ 測試歡迎卡片已成功發送到指定的歡迎頻道！", ephemeral=True)
        else:
            await interaction.followup.send("❌ 測試歡迎卡片發送失敗，請檢查日誌。", ephemeral=True)


# ==================== 修復重點：正確註冊 Cogs ====================
async def setup(bot: commands.Bot):
    await bot.add_cog(ModerationCog(bot))
    await bot.add_cog(WelcomeCog(bot))
