import random
import discord
from discord import app_commands
from discord.ext import commands

# ==================== 桌遊選單 UI ====================
class BoardGameSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(
                label="阿瓦隆 (Avalon)",
                description="5-10人 | 陣營陣營與陣營對抗、陣營隱藏遊戲",
                emoji="👑",
                value="avalon"
            ),
            discord.SelectOption(
                label="誰是牛頭王 (6 nimmt!)",
                description="2-10人 | 心機排牌、避免吃下最多牛頭",
                emoji="🐮",
                value="cow"
            ),
            discord.SelectOption(
                label="UNO",
                description="2-10人 | 經典牌類遊戲、轉向與+4地獄",
                emoji="🃏",
                value="uno"
            ),
            discord.SelectOption(
                label="德國蟑螂 (Cockroach Poker)",
                description="2-6人 | 吹牛與心機吹捧、坑害朋友必備",
                emoji="🪳",
                value="cockroach"
            ),
        ]
        super().__init__(placeholder="👉 選擇想查看規則的桌遊...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        game = self.values[0]
        embed = discord.Embed(color=discord.Color.gold())
        
        if game == "avalon":
            embed.title = "👑 阿瓦隆 (Avalon)"
            embed.description = (
                "**建議人數**：5 - 10 人\n"
                "**遊戲類型**：陣營心機、陣營隱藏\n\n"
                "**陣營分配**：\n"
                "• 藍方（正義）：梅林、派西維爾、忠臣\n"
                "• 紅方（邪惡）：莫德雷德、刺客、莫甘娜、奧伯倫、爪牙\n\n"
                "**勝負條件**：正義方完成 3 次任務，或邪惡方破壞 3 次任務（若正義方勝出，刺客仍可刺殺梅林翻盤）。"
            )
        elif game == "cow":
            embed.title = "🐮 誰是牛頭王 (6 nimmt!)"
            embed.description = (
                "**建議人數**：2 - 10 人\n"
                "**遊戲類型**：數字出牌、避害遊戲\n\n"
                "**基本規則**：\n"
                "1. 每人手牌 10 張，同時選擇一張牌蓋著，隨後同時翻開。\n"
                "2. 依照從小到大的順序，將牌接在桌上 4 排數字最接近的牌後面。\n"
                "3. 當某那一排接滿第 6 張牌時，該玩家必須收走前 5 張牌並扣分！"
            )
        elif game == "uno":
            embed.title = "🃏 UNO"
            embed.description = (
                "**建議人數**：2 - 10 人\n"
                "**遊戲類型**：手牌出光、同色同號\n\n"
                "**基本規則**：\n"
                "• 出與上一張同顏色或同數字的牌。\n"
                "• 剩最後一張牌時務必喊『UNO』！\n"
                "• 特殊卡：+2、+4、轉向、跳過、換色。"
            )
        elif game == "cockroach":
            embed.title = "🪳 德國蟑螂 (Cockroach Poker)"
            embed.description = (
                "**建議人數**：2 - 6 人\n"
                "**遊戲類型**：吹牛、心理戰\n\n"
                "**基本規則**：\n"
                "1. 蓋牌傳給其他人並宣稱內容（如：『這是一隻蝙蝠』）。\n"
                "2. 接收者可選擇：**相信/不相信**，或**看牌後繼續傳給其他人**。\n"
                "3. 猜錯的人收下該張牌，率先集滿 4 張同款害蟲或牌發完時輸掉遊戲！"
            )

        await interaction.response.send_message(embed=embed, ephemeral=True)


class BoardGameSelectView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(BoardGameSelect())


# ==================== 桌遊揪團按鈕 UI ====================
class PartyView(discord.ui.View):
    def __init__(self, game_name, max_players):
        super().__init__(timeout=None)
        self.game_name = game_name
        self.max_players = max_players
        self.players = []

    @discord.ui.button(label="➕ 參加 (Join)", style=discord.ButtonStyle.success)
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        user = interaction.user
        if user in self.players:
            await interaction.response.send_message("⚠️ 你已經在車隊裡囉！", ephemeral=True)
            return

        self.players.append(user)
        await self.update_embed(interaction)

    @discord.ui.button(label="➖ 退出 (Leave)", style=discord.ButtonStyle.danger)
    async def leave(self, interaction: discord.Interaction, button: discord.ui.Button):
        user = interaction.user
        if user not in self.players:
            await interaction.response.send_message("⚠️ 你本來就還沒加入喔！", ephemeral=True)
            return

        self.players.remove(user)
        await self.update_embed(interaction)

    async def update_embed(self, interaction: discord.Interaction):
        player_list_str = "\n".join([f"• {p.mention}" for p in self.players]) if self.players else "*目前還沒有人加入*"
        
        embed = discord.Embed(
            title=f"🎲 桌遊揪團囉：{self.game_name}",
            description=f"**當前人數**：`{len(self.players)} / {self.max_players}`\n\n**已加入玩家：**\n{player_list_str}",
            color=discord.Color.blue()
        )
        await interaction.response.edit_message(embed=embed, view=self)


# ==================== 主 Cog 指令區 ====================
class BoardGameCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # 1. 遊戲選單指令
    @app_commands.command(name="boardgame_list", description="查看經典桌遊列表與規則說明")
    async def boardgame_list(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="🎲 DC 桌遊中心",
            description="請從下方選單選擇你想查看的桌遊規則與人數簡介：",
            color=discord.Color.purple()
        )
        view = BoardGameSelectView()
        await interaction.response.send_message(embed=embed, view=view)

    # 2. 發起揪團指令
    @app_commands.command(name="boardgame_party", description="發起一個桌遊揪團卡片")
    @app_commands.describe(game="遊戲名稱（例如：阿瓦隆/UNO/牛頭王）", max_players="預計招募人數")
    async def boardgame_party(self, interaction: discord.Interaction, game: str, max_players: int = 6):
        embed = discord.Embed(
            title=f"🎲 桌遊揪團囉：{game}",
            description=f"**當前人數**：`0 / {max_players}`\n\n**已加入玩家：**\n*目前還沒有人加入*",
            color=discord.Color.blue()
        )
        view = PartyView(game_name=game, max_players=max_players)
        await interaction.response.send_message(content="@everyone 開打桌遊囉！", embed=embed, view=view)

    # 3. 抽 UNO 牌指令（娛樂用）
    @app_commands.command(name="uno_draw", description="隨機抽取一張 UNO 卡牌！")
    async def uno_draw(self, interaction: discord.Interaction):
        colors = ["🔴 紅色", "🟡 黃色", "🟢 綠色", "🔵 藍色"]
        numbers = [str(i) for i in range(0, 10)] + ["Skip (跳過)", "Reverse (反轉)", "+2 (罰抽2張)"]
        special_cards = ["🌈 Wild (換色卡)", "🔥 Wild +4 (強迫+4與換色)"]

        if random.random() < 0.15:  # 15% 機率抽到王牌
            card = random.choice(special_cards)
        else:
            color = random.choice(colors)
            num = random.choice(numbers)
            card = f"{color} - {num}"

        await interaction.response.send_message(f"🃏 {interaction.user.mention} 抽到了：**{card}**！")


async def setup(bot):
    await bot.add_cog(BoardGameCog(bot))