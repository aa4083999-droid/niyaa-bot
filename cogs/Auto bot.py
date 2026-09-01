import discord

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

client = discord.Client(intents=intents)

# 禁用的關鍵字列表
Banned_Words = ["badword1", "badword2"]


@client.event
async def on_ready():
  print(f"目前登入身分：{client.user}")


@client.event
async def on_message(message):
  # 避免機器人自己回覆自己造成無限迴圈
  if message.author == client.user:
    return

  # 檢查訊息是否包含違規關鍵字
  if any(word in message.content for word in Banned_Words):
    await message.delete()  # 刪除訊息
    await message.channel.send(
        f"{message.author.mention} 請注意用詞，該訊息已被自動刪除。"
    )


@client.event
async def on_member_join(member):
  # 指定發送歡迎訊息的頻道 ID
  channel = member.guild.get_channel(你的頻道ID數字)
  if channel:
    await channel.send(f"歡迎 {member.mention} 來到本伺服器！")


# 啟動機器人（需填入你的 Bot Token）
client.run("你的Discord_Bot_Token")