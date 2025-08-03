import discord
from discord.ext import commands
from discord import app_commands
import os
from keep_alive import keep_alive  # Flaskサーバーを使う場合（なければ削除可）

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

POKER_GAMES = {}

# --- ポーカー参加状態管理クラス ---
class PokerGameState:
    def __init__(self, owner_id):
        self.owner_id = owner_id
        self.players = []
        self.started = False

# --- 参加ボタン付きView ---
class PokerJoinView(discord.ui.View):
    def __init__(self, channel_id):
        super().__init__(timeout=None)
        self.channel_id = channel_id

    @discord.ui.button(label="参加する", style=discord.ButtonStyle.primary, custom_id="poker_join_button")
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        game = POKER_GAMES.get(self.channel_id)
        if not game or game.started:
            await interaction.response.send_message("このチャンネルでは参加できません。", ephemeral=True)
            return

        if interaction.user.id in [p.id for p in game.players]:
            await interaction.response.send_message("すでに参加しています。", ephemeral=True)
            return

        game.players.append(interaction.user)
        await interaction.response.send_message("参加が完了しました！", ephemeral=True)
        await interaction.channel.send(f"✅ {interaction.user.mention} さんがポーカーに参加しました！")

# --- /joinpoker コマンド ---
@bot.tree.command(name="joinpoker", description="ポーカーの参加者を募集します")
async def join_poker(interaction: discord.Interaction):
    if interaction.channel_id in POKER_GAMES:
        await interaction.response.send_message("このチャンネルではすでにポーカーが開催中です。", ephemeral=True)
        return

    POKER_GAMES[interaction.channel_id] = PokerGameState(owner_id=interaction.user.id)
    view = PokerJoinView(channel_id=interaction.channel_id)
    await interaction.response.send_message(
        "🃏 ポーカーを開始しました！参加するには以下のボタンを押してください👇",
        view=view
    )
@bot.command()
async def sync(ctx):
    await bot.tree.sync(guild=ctx.guild)
    await ctx.send("✅ コマンドを再同期しました")
# --- 起動時処理 ---
@bot.event
async def on_ready():
    bot.add_view(PokerJoinView(None))
    guild = discord.Object(id=1398607685158440991)  # ← あなたのサーバーIDに変更！
    await bot.tree.sync(guild=guild)
    print(f"✅ Bot connected as {bot.user}")

# --- keep_alive（Railway/Render用）---
keep_alive()

# --- Bot起動 ---
bot.run(os.environ["DISCORD_TOKEN"])


