import random
import sqlite3
import discord
from discord import app_commands
from discord.ext import commands


def get_db():
    conn = sqlite3.connect("database.db")
    # 自動檢查並建立 players 表格
    cursor = conn.cursor()
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS players (
        user_id INTEGER PRIMARY KEY,
        level INTEGER DEFAULT 1,
        exp INTEGER DEFAULT 0,
        gold INTEGER DEFAULT 50,
        hp INTEGER DEFAULT 100,
        atk INTEGER DEFAULT 15
    )
    """)
    conn.commit()
    return conn


class RPGCog(commands.Cog):

    def __init__(self, bot):
        self.bot = bot

    def get_player(self, user_id):
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM players WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()

        if not row:
            cursor.execute(
                "INSERT INTO players (user_id) VALUES (?)", (user_id,)
            )
            conn.commit()
            cursor.execute(
                "SELECT * FROM players WHERE user_id = ?", (user_id,)
            )
            row = cursor.fetchone()

        conn.close()
        return {
            "user_id": row[0],
            "level": row[1],
            "exp": row[2],
            "gold": row[3],
            "hp": row[4],
            "atk": row[5],
        }

    def update_player(self, user_id, level, exp, gold, hp, atk):
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE players 
            SET level = ?, exp = ?, gold = ?, hp = ?, atk = ?
            WHERE user_id = ?
        """,
            (level, exp, gold, hp, atk, user_id),
        )
        conn.commit()
        conn.close()

    @app_commands.command(name="hunt", description="前往森林討伐怪物獲取經驗與金幣！")
    async def hunt(self, interaction: discord.Interaction):
        await interaction.response.defer()
        try:
            user = interaction.user
            player = self.get_player(user.id)

            monsters = [
                {"name": "史萊姆", "exp": 15, "gold": 10, "damage": 5},
                {"name": "哥布林", "exp": 25, "gold": 20, "damage": 12},
                {"name": "野生冒險家", "exp": 40, "gold": 35, "damage": 20},
                {"name": "迷路的迷魅狐", "exp": 60, "gold": 50, "damage": 30},
            ]
            monster = random.choice(monsters)

            player["hp"] -= monster["damage"]
            player["exp"] += monster["exp"]
            player["gold"] += monster["gold"]

            leveled_up = False
            target_exp = player["level"] * 100
            if player["exp"] >= target_exp:
                player["exp"] -= target_exp
                player["level"] += 1
                player["hp"] = 100 + (player["level"] * 10)
                player["atk"] += 5
                leveled_up = True

            self.update_player(
                user.id,
                player["level"],
                player["exp"],
                player["gold"],
                player["hp"],
                player["atk"],
            )

            msg = f"⚔️ **{user.display_name}** 出門冒險，遇到了 **{monster['name']}**！\n"
            msg += f"💥 擊敗怪物！獲得 `{monster['exp']}` 經驗值與 `{monster['gold']}` 金幣（受到 {monster['damage']} 點傷害）。\n"

            if leveled_up:
                msg += f"\n🎉 **恭喜升級！** 升到了 **Lv.{player['level']}**！攻擊力提升至 `{player['atk']}`！"

            await interaction.followup.send(content=msg)
        except Exception as e:
            print(f"❌ /hunt 發生錯誤: {e}")
            await interaction.followup.send(content=f"❌ 發生錯誤：`{e}`")

    @app_commands.command(name="profile", description="查看你的 RPG 角色狀態與裝備")
    async def profile(self, interaction: discord.Interaction):
        await interaction.response.defer()
        try:
            user = interaction.user
            player = self.get_player(user.id)

            embed = discord.Embed(
                title=f"🛡️ {user.display_name} 的冒險者護照",
                color=discord.Color.purple(),
            )
            if user.avatar:
                embed.set_thumbnail(url=user.avatar.url)

            embed.add_field(
                name="等級 (Level)", value=f"Lv. {player['level']}", inline=True
            )
            embed.add_field(
                name="經驗值 (EXP)",
                value=f"{player['exp']} / {player['level'] * 100}",
                inline=True,
            )
            embed.add_field(
                name="金幣 (Gold)", value=f"💰 {player['gold']}", inline=True
            )
            embed.add_field(
                name="生命值 (HP)", value=f"❤️ {player['hp']}", inline=True
            )
            embed.add_field(
                name="攻擊力 (ATK)", value=f"⚔️ {player['atk']}", inline=True
            )
            embed.set_footer(text="霓夜的奇幻世界 • 資料庫已連線安全儲存")

            await interaction.followup.send(embed=embed)
        except Exception as e:
            print(f"❌ /profile 發生錯誤: {e}")
            await interaction.followup.send(content=f"❌ 發生錯誤：`{e}`")


async def setup(bot):
    await bot.add_cog(RPGCog(bot))