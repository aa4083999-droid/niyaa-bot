import asyncio
import os
import discord
from discord.ext import commands

# 1. 設定機器人權限與意圖
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.voice_states = True  # 啟用語音狀態更新意圖（用於偵測進入、離開與靜音）

bot = commands.Bot(command_prefix="/", intents=intents)


# 2. 自動動態載入 cogs 資料夾裡的所有模組
async def load_extensions():
    for filename in os.listdir("./cogs"):
        if filename.endswith(".py"):
            await bot.load_extension(f"cogs.{filename[:-3]}")
            print(f"✅ 已成功載入模組：{filename}")


@bot.event
async def on_ready():
    try:
        synced = await bot.tree.sync()
        print(f"成功同步 {len(synced)} 個斜線指令！")
    except Exception as e:
        print(f"同步指令失敗: {e}")

    await bot.change_presence(
        activity=discord.Game(
            name="霓夜的小精靈 v2.0 | 多功能 RPG 系統啟動中"
        )
    )
    print(f"✨ 霓夜的小精靈已成功上線！帳號：{bot.user}")


async def main():
    async with bot:
        await load_extensions()

        token = os.getenv("DISCORD_TOKEN")
        if not token:
            print("❌ 錯誤：找不到 DISCORD_TOKEN 環境變數！")
            return

        await bot.start(token)


if __name__ == "__main__":
    asyncio.run(main())
