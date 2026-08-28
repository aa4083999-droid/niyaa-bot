import random
import discord
from discord import app_commands
from discord.ext import commands

# 授權白名單頻道 ID 列表
ALLOWED_CHANNEL_IDS = [1542821360215265280]

def is_allowed_channel():
    async def predicate(interaction: discord.Interaction):
        if interaction.channel_id not in ALLOWED_CHANNEL_IDS:
            await interaction.response.send_message(
                "❌ 此指令只能在指定的桌遊專屬頻道中使用！",
                ephemeral=True
            )
            return False
        return True
    return app_commands.check(predicate)

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
    def __init__(self, game_name, max_players, organizer):
        super().__init__(timeout=None)
        self.game_name = game_name
        self.max_players = max_players
        self.players = [organizer]  # 發起人自動加入
        self.organizer = organizer

    @discord.ui.button(label="➕ 參加 (Join)", style=discord.ButtonStyle.success)
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        user = interaction.user
        
        # ✅ 檢查是否已滿人
        if len(self.players) >= self.max_players:
            await interaction.response.send_message(
                f"❌ 人數已滿 ({len(self.players)}/{self.max_players})，無法加入！",
                ephemeral=True
            )
            return
        
        if user in self.players:
            await interaction.response.send_message("⚠️ 你已經在車隊裡囉！", ephemeral=True)
            return

        self.players.append(user)
        
        # ✅ 人數滿時提示
        if len(self.players) == self.max_players:
            embed = await self._create_embed()
            embed.title = f"🎉 {embed.title}"
            embed.description = f"**當前人數**：`{len(self.players)} / {self.max_players}` ✅ **人數已滿！**\n\n**已加入玩家：**\n" + \
                                    "\n".join([f"• {p.mention}" for p in self.players])
            await interaction.response.edit_message(embed=embed, view=self)
        else:
            await self.update_embed(interaction)

    @discord.ui.button(label="➖ 退出 (Leave)", style=discord.ButtonStyle.danger)
    async def leave(self, interaction: discord.Interaction, button: discord.ui.Button):
        user = interaction.user
        
        # ✅ 發起人無法退出
        if user == self.organizer and len(self.players) > 1:
            await interaction.response.send_message(
                "⚠️ 作為遊戲發起人，如果你要退出請解散遊戲。\n"
                "請使用 `/boardgame_party` 重新發起新的揪團。",
                ephemeral=True
            )
            return
        
        if user not in self.players:
            await interaction.response.send_message("⚠️ 你本來就還沒加入喔！", ephemeral=True)
            return

        self.players.remove(user)
        await self.update_embed(interaction)

    @discord.ui.button(label="🎮 開始遊戲 (Start)", style=discord.ButtonStyle.primary)
    async def start_game(self, interaction: discord.Interaction, button: discord.ui.Button):
        # ✅ 只有發起人可以開始遊戲
        if interaction.user != self.organizer:
            await interaction.response.send_message(
                "⚠️ 只有遊戲發起人才能開始遊戲！",
                ephemeral=True
            )
            return
        
        # ✅ 檢查最少人數
        if len(self.players) < 2:
            await interaction.response.send_message(
                "❌ 至少需要 2 人以上才能開始遊戲！",
                ephemeral=True
            )
            return

        player_mentions = "、".join([p.mention for p in self.players])
        embed = discord.Embed(
            title=f"🎮 {self.game_name} - 遊戲開始！",
            description=f"參與玩家 ({len(self.players)} 人)：\n{player_mentions}\n\n祝各位遊戲愉快！🎉",
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed)
        
        # ✅ 遊戲開始後禁用按鈕
        self.join.disabled = True
        self.leave.disabled = True
        self.start_game.disabled = True
        await interaction.edit_original_response(view=self)

    async def _create_embed(self):
        player_list_str = "\n".join([f"• {p.mention}" for p in self.players]) if self.players else "*目前還沒有人加入*"
        
        embed = discord.Embed(
            title=f"🎲 桌遊揪團囉：{self.game_name}",
            description=f"**當前人數**：`{len(self.players)} / {self.max_players}`\n\n**已加入玩家：**\n{player_list_str}",
            color=discord.Color.blue()
        )
        return embed

    async def update_embed(self, interaction: discord.Interaction):
        embed = await self._create_embed()
        await interaction.response.edit_message(embed=embed, view=self)


# ==================== 主 Cog 指令區 ====================
class BoardGameCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # 1. 遊戲選單指令
    @app_commands.command(name="boardgame_list", description="查看經典桌遊列表與規則說明")
    @is_allowed_channel()
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
    @app_commands.describe(
        game="遊戲名稱（例如：阿瓦隆/UNO/牛頭王/蟑螂）",
        max_players="預計招募人數 (2-10 人)"
    )
    @is_allowed_channel()
    async def boardgame_party(self, interaction: discord.Interaction, game: str, max_players: int = 6):
        # ✅ 驗證人數範圍
        if not 2 <= max_players <= 10:
            await interaction.response.send_message(
                "❌ 人數必須在 2-10 之間！",
                ephemeral=True
            )
            return
        
        # ✅ 驗證遊戲名稱不為空
        if not game or len(game.strip()) == 0:
            await interaction.response.send_message(
                "❌ 遊戲名稱不能為空！",
                ephemeral=True
            )
            return

        embed = discord.Embed(
            title=f"🎲 桌遊揪團囉：{game}",
            description=f"**當前人數**：`1 / {max_players}`（發起人：{interaction.user.mention}）\n\n**已加入玩家：\n• {interaction.user.mention}",
            color=discord.Color.blue()
        )
        embed.set_footer(text="提示：點擊「開始遊戲」按鈕時，所有玩家必須已確認加入。")
        
        view = PartyView(game_name=game, max_players=max_players, organizer=interaction.user)
        await interaction.response.send_message(
            content=f"@everyone {interaction.user.mention} 開打桌遊囉！",
            embed=embed,
            view=view
        )

    # 3. 抽 UNO 牌指令（娛樂用）
    @app_commands.command(name="uno_draw", description="隨機抽取一張 UNO 卡牌！")
    @is_allowed_channel()
    async def uno_draw(self, interaction: discord.Interaction):
        colors = [
            {"name": "🔴 紅色", "color": discord.Color.red()},
            {"name": "🟡 黃色", "color": discord.Color.yellow()},
            {"name": "🟢 綠色", "color": discord.Color.green()},
            {"name": "🔵 藍色", "color": discord.Color.blue()}
        ]
        
        numbers = [str(i) for i in range(0, 10)] + ["Skip (跳過)", "Reverse (反轉)", "+2 (罰抽2張)"]
        
        special_cards = [
            {"name": "🌈 Wild (換色卡)", "desc": "可以指定任何顏色"},
            {"name": "🔥 Wild +4 (強迫+4與換色)", "desc": "下家罰抽4張 + 換色"}
        ]

        if random.random() < 0.15:  # 15% 機率抽到王牌
            card = random.choice(special_cards)
            embed = discord.Embed(
                title="🃏 UNO 卡牌抽取",
                description=f"{interaction.user.mention} 抽到了一張特殊卡：\n\n**\n\n{card['desc']}",
                color=discord.Color.gold()
            )
        else:
            color_info = random.choice(colors)
            num = random.choice(numbers)
            embed = discord.Embed(
                title="🃏 UNO 卡牌抽取",
                description=f"{interaction.user.mention} 抽到了：\n\n**{color_info['name']} - {num}**",
                color=color_info['color']
            )

        embed.set_footer(text="這是娛樂功能，結果純隨機！")
        await interaction.response.send_message(embed=embed)

    # 4. 骰子指令（補充娛樂功能）
    @app_commands.command(name="dice", description="擲骰子！(1-6)")
    @is_allowed_channel()
    async def dice(self, interaction: discord.Interaction):
        result = random.randint(1, 6)
        dice_faces = ["⚀", "⚁", "⚂", "⚃", "⚄", "⚅"]
        
        embed = discord.Embed(
            title="🎲 骰子結果",
            description=f"{interaction.user.mention} 擲出：\n\n# {dice_faces[result - 1]} {result}",
            color=discord.Color.random()
        )
        await interaction.response.send_message(embed=embed)

    # 5. 隨機選擇器指令（幫助決定玩什麼）
    @app_commands.command(name="pick_game", description="隨機選擇一個桌遊！")
    @is_allowed_channel()
    async def pick_game(self, interaction: discord.Interaction):
        games = ["阿瓦隆", "誰是牛頭王", "UNO", "德國蟑螂"]
        picked = random.choice(games)
        
        embed = discord.Embed(
            title="🎮 隨機遊戲選擇",
            description=f"{interaction.user.mention} 的推薦遊戲是：\n\n# {picked}",
            color=discord.Color.random()
        )
        await interaction.response.send_message(embed=embed)


async def setup(bot):
    await bot.add_cog(BoardGameCog(bot))
