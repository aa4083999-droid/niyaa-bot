import asyncio
import logging
import os
from pathlib import Path

import discord
from discord.ext import commands


BASE_DIR = Path(__file__).resolve().parent
COGS_DIR = BASE_DIR / "cogs"


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("discord_bot")


intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.voice_states = True

bot = commands.Bot(command_prefix="/", intents=intents)
_commands_synced = False


async def load_extensions():
    """載入 cogs 目錄內所有 Python 模組，並明確回報失敗項目。"""
    if not COGS_DIR.is_dir():
        raise FileNotFoundError(f"找不到 cogs 目錄：{COGS_DIR}")

    for path in sorted(COGS_DIR.glob("*.py")):
        if path.name.startswith("_"):
            continue

        extension = f"cogs.{path.stem}"

        try:
            await bot.load_extension(extension)
            log.info("已成功載入模組：%s", extension)
        except Exception:
            log.exception("載入模組失敗：%s", extension)
            raise


@bot.event
async def on_ready():
    """on_ready 可能因重連再次觸發，因此只同步一次。"""
    global _commands_synced

    if not _commands_synced:
        try:
            synced = await bot.tree.sync()
            _commands_synced = True
            log.info("成功同步 %d 個斜線指令", len(synced))
        except discord.HTTPException:
            log.exception("同步斜線指令失敗")

    await bot.change_presence(
        activity=discord.Game(
            name="霓夜的小精靈 v2.0 | 多功能 RPG 系統啟動中"
        )
    )

    log.info("霓夜的小精靈已上線！帳號：%s", bot.user)


async def main():
    token = os.getenv("DISCORD_TOKEN")

    if not token:
        raise RuntimeError("找不到 DISCORD_TOKEN 環境變數")

    async with bot:
        await load_extensions()
        await bot.start(token)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("機器人已停止")
