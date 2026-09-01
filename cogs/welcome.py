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
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

# 改成預設為 0，允許啟動時先不填
WELCOME_CHANNEL_ID = int(os.getenv("WELCOME_CHANNEL_ID", 0))
MOD_CHANNEL_ID = int(os.getenv("MOD_CHANNEL_ID", 0))

if not DISCORD_TOKEN:
    raise ValueError("❌ 請在環境變數中設定 DISCORD_TOKEN")

print("🔍 DISCORD_TOKEN: ✅ 已設定")
print(f"🔍 動態歡迎頻道 ID: {WELCOME_CHANNEL_ID if WELCOME_CHANNEL_ID != 0 else '⚠️ 尚未設定（請稍後在 DC 使用指令設定）'}")
print(f"🔍 動態日誌頻道 ID: {MOD_CHANNEL_ID if MOD_CHANNEL_ID != 0 else '⚠️ 尚未設定（選填）'}")
print("✅ [Config] 環境變數已成功載入\n")
# ============================================================

# ==================== 資產配置 ====================
DOG_BG_IMAGE_FILENAME = "welcome_background.jpg"
FONT_FILENAME = "font.ttc"
# ============================================================

# ==================== 禁用詞配置 ====================
BANNED_WORDS = [
    "badword1",
    "badword2",
    "inappropriate",
]

# 豁免的使用者 ID
EXEMPT_USERS = []

# 豁免的頻道 ID
EXEMPT_CHANNELS = []
# ============================================================

# ==================== 全域配置變數（可動態修改） ====================
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
# ============================================================


class ModerationCog(commands.Cog):
    """自動化管理系統 Cog"""
    
    def __init__(self, bot):
        self.bot = bot
        self.banned_words = [word.lower() for word in BANNED_WORDS]
        logger.info("✅ [Cog] ModerationCog 已載入")

    def is_word_in_text(self, text, word):
        """
        智慧關鍵字檢查（大小寫不敏感 + 單詞邊界檢查）
        """
        text_lower = text.lower()
        pattern = r'\b' + re.escape(word) + r'\b'
        return re.search(pattern, text_lower) is not None

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """監聽所有訊息並檢查禁用詞"""
        
        if message.author == self.bot.user:
            return
        
        if message.author.bot:
            return
        
        if message.channel.id in EXEMPT_CHANNELS:
            return
        
        if message.author.id in EXEMPT_USERS:
            return
        
        # 檢查訊息是否包含違規關鍵字
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
                
                # 發送到版主頻道
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

    # ==================== 管理 Slash Commands ====================
    
    @app_commands.command(
        name="set_welcome_channel",
        description="設定歡迎頻道（僅管理員可用）"
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def set_welcome_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        """設定歡迎頻道 ID"""
        
        ConfigManager.set_welcome_channel_id(channel.id)
        
        embed = discord.Embed(
            title="✅ 歡迎頻道已設定",
            description=f"歡迎卡片將發送到：{channel.mention}",
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(
        name="set_mod_channel",
        description="設定日誌頻道（僅管理員可用）"
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def set_mod_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        """設定日誌/版主頻道 ID"""
        
        ConfigManager.set_mod_channel_id(channel.id)
        
        embed = discord.Embed(
            title="✅ 日誌頻道已設定",
            description=f"違規訊息日誌將發送到：{channel.mention}",
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(
        name="add_ban_word",
        description="添加一個禁用詞（僅管理員可用）"
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def add_ban_word(self, interaction: discord.Interaction, word: str):
        """添加禁用詞"""
        
        word_lower = word.lower()
        
        if word_lower in self.banned_words:
            await interaction.response.send_message(
                f"⚠️ 禁用詞 `{word}` 已存在",
                ephemeral=True
            )
            return
        
        self.banned_words.append(word_lower)
        BANNED_WORDS.append(word)
        
        embed = discord.Embed(
            title="✅ 禁用詞已添加",
            description=f"成功添加禁用詞：`{word}`",
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        logger.info(f"✅ [Admin] {interaction.user.name} 添加了禁用詞：{word}")

    @app_commands.command(
        name="remove_ban_word",
        description="移除一個禁用詞（僅管理員可用）"
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def remove_ban_word(self, interaction: discord.Interaction, word: str):
        """移除禁用詞"""
        
        word_lower = word.lower()
        
        if word_lower not in self.banned_words:
            await interaction.response.send_message(
                f"⚠️ 禁用詞 `{word}` 不存在",
                ephemeral=True
            )
            return
        
        self.banned_words.remove(word_lower)
        BANNED_WORDS.remove(word)
        
        embed = discord.Embed(
            title="✅ 禁用詞已移除",
            description=f"成功移除禁用詞：`{word}`",
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        logger.info(f"✅ [Admin] {interaction.user.name} 移除了禁用詞：{word}")

    @app_commands.command(
        name="list_ban_words",
        description="顯示所有禁用詞（僅管理員可用）"
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def list_ban_words(self, interaction: discord.Interaction):
        """列出所有禁用詞"""
        
        if not self.banned_words:
            await interaction.response.send_message(
                "ℹ️ 目前沒有禁用詞",
                ephemeral=True
            )
            return
        
        banned_list = ", ".join([f"`{word}`" for word in self.banned_words])
        
        embed = discord.Embed(
            title="📋 禁用詞列表",
            description=banned_list,
            color=discord.Color.blue()
        )
        embed.set_footer(text=f"總計：{len(self.banned_words)} 個禁用詞")
        
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(
        name="exempt_user",
        description="將使用者添加到豁免列表（不會觸發訊息過濾）"
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def exempt_user(self, interaction: discord.Interaction, user: discord.User):
        """豁免使用者"""
        
        if user.id in EXEMPT_USERS:
            await interaction.response.send_message(
                f"⚠️ {user.mention} 已在豁免列表中",
                ephemeral=True
            )
            return
        
        EXEMPT_USERS.append(user.id)
        
        embed = discord.Embed(
            title="✅ 使用者已豁免",
            description=f"{user.mention} 已添加到豁免列表",
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        logger.info(f"✅ [Admin] {user.name} 已添加到豁免列表")

    @app_commands.command(
        name="exempt_channel",
        description="將頻道添加到豁免列表（該頻道的訊息不會被過濾）"
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def exempt_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        """豁免頻道"""
        
        if channel.id in EXEMPT_CHANNELS:
            await interaction.response.send_message(
                f"⚠️ {channel.mention} 已在豁免列表中",
                ephemeral=True
            )
            return
        
        EXEMPT_CHANNELS.append(channel.id)
        
        embed = discord.Embed(
            title="✅ 頻道已豁免",
            description=f"{channel.mention} 已添加到豁免列表",
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        logger.info(f"✅ [Admin] {channel.name} 已添加到豁免列表")

    @app_commands.command(
        name="config_status",
        description="查看目前的配置狀態（僅管理員可用）"
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def config_status(self, interaction: discord.Interaction):
        """查看配置狀態"""
        
        welcome_id = ConfigManager.get_welcome_channel_id()
        mod_id = ConfigManager.get_mod_channel_id()
        
        embed = discord.Embed(
            title="⚙️ 配置狀態",
            color=discord.Color.blue()
        )
        
        # 歡迎頻道
        if welcome_id != 0:
            try:
                welcome_channel = self.bot.get_channel(welcome_id)
                if welcome_channel:
                    embed.add_field(
                        name="✅ 歡迎頻道",
                        value=f"{welcome_channel.mention}",
                        inline=False
                    )
                else:
                    embed.add_field(
                        name="⚠️ 歡迎頻道",
                        value=f"頻道 ID: {welcome_id}（找不到該頻道）",
                        inline=False
                    )
            except:
                embed.add_field(
                    name="⚠️ 歡迎頻道",
                    value=f"頻道 ID: {welcome_id}",
                    inline=False
                )
        else:
            embed.add_field(
                name="❌ 歡迎頻道",
                value="尚未設定，使用 `/set_welcome_channel` 設定",
                inline=False
            )
        
        # 日誌頻道
        if mod_id != 0:
            try:
                mod_channel = self.bot.get_channel(mod_id)
                if mod_channel:
                    embed.add_field(
                        name="✅ 日誌頻道",
                        value=f"{mod_channel.mention}",
                        inline=False
                    )
                else:
                    embed.add_field(
                        name="⚠️ 日誌頻道",
                        value=f"頻道 ID: {mod_id}（找不到該頻道）",
                        inline=False
                    )
            except:
                embed.add_field(
                    name="⚠️ 日誌頻道",
                    value=f"頻道 ID: {mod_id}",
                    inline=False
                )
        else:
            embed.add_field(
                name="ℹ️ 日誌頻道",
                value="未設定（選填），使用 `/set_mod_channel` 設定",
                inline=False
            )
        
        # 禁用詞統計
        embed.add_field(
            name="📋 禁用詞",
            value=f"共 {len(self.banned_words)} 個禁用詞已配置",
            inline=False
        )
        
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
        """在啟動時載入背景與字型至記憶體中"""
        current_dir = os.path.dirname(os.path.abspath(__file__))
        root_dir = os.path.dirname(current_dir)
        
        bg_path = os.path.join(root_dir, DOG_BG_IMAGE_FILENAME)
        font_path_zh = os.path.join(root_dir, FONT_FILENAME)

        try:
            if os.path.exists(bg_path):
                with open(bg_path, "rb") as f:
                    self._cached_background = f.read()
                logger.info("✅ 已成功快取歡迎卡片背景圖片")
            else:
                logger.warning(f"⚠️ 找不到背景圖片檔案: {bg_path}")
        except Exception as e:
            logger.error(f"❌ 載入背景圖片時發生錯誤: {e}", exc_info=True)

        try:
            if os.path.exists(font_path_zh):
                self._cached_font_title = ImageFont.truetype(font_path_zh, 32)
                self._cached_font_sub = ImageFont.truetype(font_path_zh, 22)
                logger.info("✅ 已成功建立字型物件快取")
            else:
                logger.warning(f"⚠️ 找不到字型檔案: {font_path_zh}，將使用預設字型")
                self._cached_font_title = ImageFont.load_default()
                self._cached_font_sub = ImageFont.load_default()
        except Exception as e:
            logger.error(f"❌ 載入字型時發生錯誤: {e}", exc_info=True)
            self._cached_font_title = ImageFont.load_default()
            self._cached_font_sub = ImageFont.load_default()

    def _generate_card_sync(self, avatar_bytes: bytes, display_name: str) -> bytes:
        """使用 Pillow 進行同步的圖片合成工作"""
        width, height = 800, 400

        if self._cached_background:
            try:
                with Image.open(io.BytesIO(self._cached_background)) as bg:
                    base_img = bg.convert("RGBA")
                    base_img = base_img.resize((width, height), Image.Resampling.LANCZOS)
            except Exception:
                base_img = Image.new("RGBA", (width, height), (30, 30, 45, 255))
        else:
            base_img = Image.new("RGBA", (width, height), (30, 30, 45, 255))

        overlay = Image.new("RGBA", (width, height), (0, 0, 0, 100))
        card = Image.alpha_composite(base_img, overlay)

        if avatar_bytes:
            try:
                with Image.open(io.BytesIO(avatar_bytes)) as avatar_img:
                    avatar_img = avatar_img.convert("RGBA")
                    avatar_img = avatar_img.resize((150, 150), Image.Resampling.LANCZOS)

                    mask = Image.new("L", (150, 150), 0)
                    draw_mask = ImageDraw.Draw(mask)
                    draw_mask.ellipse((0, 0, 150, 150), fill=255)

                    avatar_x, avatar_y = (width - 150) // 2, 45
                    card.paste(avatar_img, (avatar_x, avatar_y), mask)

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
        """取得歡迎頻道"""
        welcome_channel_id = ConfigManager.get_welcome_channel_id()
        
        if welcome_channel_id == 0:
            logger.warning("⚠️ 歡迎頻道未設定，請使用 `/set_welcome_channel` 設定")
            return None
        
        channel = self.bot.get_channel(welcome_channel_id)
        if channel is None:
            try:
                channel = await asyncio.wait_for(
                    self.bot.fetch_channel(welcome_channel_id), timeout=30.0
                )
            except Exception as e:
                logger.error(f"❌ 無法透過 API 取得歡迎頻道 {welcome_channel_id}: {e}")
                return None

        if not isinstance(channel, (discord.TextChannel, discord.Thread, discord.VoiceChannel)):
            logger.error(f"❌ 取得的頻道 ID {welcome_channel_id} 不是支援訊息發送的頻道型態")
            return None

        return channel

    async def send_welcome_process(self, member: discord.Member) -> bool:
        """核心歡迎卡片生成與發送流程"""
        channel = await self._get_welcome_channel()
        if not channel:
            logger.warning(f"⚠️ 無法為成員 {member.id} 發送歡迎訊息，歡迎頻道未設定或不可用")
            return False

        intro_text = f"{member.mention}，歡迎來到 **霓夜的狗窩** 😍\n"

        avatar_bytes = b""
        try:
            avatar_asset = member.display_avatar.with_size(256)
            avatar_bytes = await asyncio.wait_for(avatar_asset.read(), timeout=15.0)
        except Exception as e:
            logger.warning(f"⚠️ 下載使用者 {member.id} 頭貼失敗或逾時: {e}")

        display_name = getattr(member, "display_name", member.name)

        try:
            async with self.pillow_semaphore:
                card_bytes = await asyncio.to_thread(
                    self._generate_card_sync, avatar_bytes, display_name
                )
        except Exception as e:
            logger.error(f"❌ 圖片合成過程發生錯誤: {e}", exc_info=True)
            return False

        file = discord.File(io.BytesIO(card_bytes), filename="welcome_card.png")

        try:
            await asyncio.wait_for(
                channel.send(content=intro_text, file=file),
                timeout=30.0
            )
            logger.info(f"✅ 成功發送歡迎卡片給成員: {display_name} ({member.id})")
            return True
        except Exception as e:
            logger.error(f"❌ 發送歡迎訊息失敗或逾時: {e}", exc_info=True)
            return False

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        """當成員加入時自動發送歡迎卡片"""
        await self.send_welcome_process(member)

    @app_commands.command(
        name="test_welcome",
        description="測試精美圖片歡迎卡片 (僅限管理員)"
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def test_welcome(self, interaction: discord.Interaction):
        """測試歡迎卡片"""
        await interaction.response.defer(ephemeral=True)

        channel = await self._get_welcome_channel()
        if not channel:
            await interaction.followup.send(
                "❌ 找不到設定的歡迎頻道，請使用 `/set_welcome_channel` 設定！",
                ephemeral=True
            )
            return

        member = interaction.user
        if interaction.guild and not isinstance(member, discord.Member):
            try:
                member = await asyncio.wait_for(
                    interaction.guild.fetch_member(interaction.user.id), timeout=10.0
                )
            except Exception as e:
                logger.warning(f"⚠️ 無法取得完整的 Member 物件: {e}")

        success = await self.send_welcome_process(member)
        
        if success:
            await interaction.followup.send(
                "✅ 測試歡迎卡片已成功發送到指定的歡迎頻道！",
                ephemeral=True
            )
        else:
            await interaction.followup.send(
                "❌ 測試歡迎卡片發送失敗，請檢查日誌詳細記錄。",
                ephemeral=True
            )


# ==================== Bot 初始化 ====================
async def setup_bot():
    """設置 Bot"""
    intents = discord.Intents.default()
    intents.message_content = True
    intents.members = True
    
    bot = commands.Bot(command_prefix="!", intents=intents)
    
    @bot.event
    async def on_ready():
        print(f"\n✅ Bot 已連接為：{bot.user}")
        print(f"✅ 監控的伺服器數：{len(bot.guilds)}")
        try:
            synced = await bot.tree.sync()
            print(f"✅ 已同步 {len(synced)} 個 Slash Commands\n")
        except Exception as e:
            print(f"❌ 同步 Slash Commands 失敗：{e}\n")
    
    @bot.event
    async def on_error(event, *args, **kwargs):
        """全域錯誤處理"""
        logger.error(f"❌ [Error] 事件 {event} 中發生錯誤", exc_info=True)
    
    # 載入 Cogs
    await bot.add_cog(ModerationCog(bot))
    await bot.add_cog(WelcomeCog(bot))
    
    return bot


# ==================== 主程式 ====================
async def main():
    """主程式入口"""
    bot = await setup_bot()
    await bot.start(DISCORD_TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
