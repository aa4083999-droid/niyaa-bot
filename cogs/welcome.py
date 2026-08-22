import io
import os
import discord
from discord.ext import commands
from PIL import Image, ImageDraw, ImageFont
import asyncio

# ==================== 設定區 (請修改這裡) ====================
WELCOME_CHANNEL_ID = 1506072169145307339  # 貼上你想發送歡迎訊息的頻道 ID
# 如果你的圖片是 jpg 格式，請改成 "welcome_background.jpg"
DOG_BG_IMAGE_FILENAME = "welcome_background.jpg"
# ============================================================


class WelcomeCog(commands.Cog):

    def __init__(self, bot):
        self.bot = bot

    async def create_welcome_card(self, member: discord.Member) -> io.BytesIO:
        width, height = 800, 400
        card_dir = os.path.dirname(os.path.abspath(__file__))
        bg_path = os.path.join(card_dir, DOG_BG_IMAGE_FILENAME)

        # 1. 載入背景圖片
        if os.path.exists(bg_path):
            try:
                bg = Image.open(bg_path).convert("RGBA")
                bg = bg.resize((width, height), Image.Resampling.LANCZOS)
            except Exception as e:
                print(f"❌ 圖片開啟失敗: {e}")
                bg = Image.new("RGBA", (width, height), (30, 30, 45, 255))
        else:
            print(f"⚠️ 找不到背景圖片檔案: {bg_path}")
            bg = Image.new("RGBA", (width, height), (30, 30, 45, 255))

        # 加上一層半透明黑色遮罩（讓文字和頭貼更顯眼）
        overlay = Image.new("RGBA", (width, height), (0, 0, 0, 100))
        card = Image.alpha_composite(bg, overlay)

        # 2. 處理使用者大頭貼（畫成圓形）
        try:
            avatar_asset = member.display_avatar.with_size(256)
            avatar_bytes = await avatar_asset.read()
            avatar_img = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA")
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
            print(f"❌ 無法處理頭貼: {e}")

        # 3. 寫入文字
        draw = ImageDraw.Draw(card)
        try:
            font_path_zh = "msjh.ttc"
            font_title = ImageFont.truetype(font_path_zh, 32)
            font_sub = ImageFont.truetype(font_path_zh, 22)
        except IOError:
            font_title = ImageFont.load_default()
            font_sub = ImageFont.load_default()

        # 歡迎文字（亮白色 + 粗黑色描邊，超級清晰）
        text_welcome = f"歡迎 {member.name} 狗勾"
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

        # 副標題（改用不會變亂碼的符號，換成亮黃色吸引注意）
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
        return output

    async def send_welcome_process(
        self, member: discord.Member, channel: discord.abc.Messageable
    ):
        intro_text = (
            f"{member.mention}，歡迎來到 **霓夜的狗窩** 😍\n"
        )

        card_io = await self.create_welcome_card(member)
        file = discord.File(card_io, filename="welcome_card.png")

        try:
            await channel.send(content=intro_text, file=file)
        except Exception as e:
            print(f"❌ 發送歡迎訊息失敗: {e}")

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        channel = self.bot.get_channel(WELCOME_CHANNEL_ID)
        if not channel:
            return
        await self.send_welcome_process(member, channel)

    @discord.app_commands.command(
        name="test_welcome", description="測試精美圖片歡迎卡片"
    )
    @discord.app_commands.checks.has_permissions(administrator=True)
    async def test_welcome(self, interaction: discord.Interaction):
        channel = self.bot.get_channel(WELCOME_CHANNEL_ID)
        if not channel:
            await interaction.response.send_message(
                "❌ 找不到設定的歡迎頻道 ID！", ephemeral=True
            )
            return

        await interaction.response.send_message(
            "✅ 正在產生歡迎卡片...", ephemeral=True
        )
        await self.send_welcome_process(interaction.user, channel)


async def setup(bot):
    await bot.add_cog(WelcomeCog(bot))