import discord
from discord.ext import commands
from discord import app_commands
import os
import json 
from keep_alive import keep_alive
import random
from PIL import Image
import io
import aiohttp

# カード定義
CARD_SUITS = ['spades', 'hearts', 'clubs', 'diamonds']
CARD_NUMBERS = [str(i) for i in range(2, 11)] + ['J', 'Q', 'K', 'A']
CARD_DECK = [f"{suit}_{number}" for suit in CARD_SUITS for number in CARD_NUMBERS]
CARD_IMAGE_BASE_URL = "https://raw.githubusercontent.com/yuuyuu661/bot5/main/cards/"

# Botセットアップ
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

GUILD_ID = 1398607685158440991
POKER_GAMES = {}

CURRENCY_FILE = "currency.json"

def load_currency():
    if not os.path.exists(CURRENCY_FILE):
        return {}
    with open(CURRENCY_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_currency(data):
    with open(CURRENCY_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def get_balance(user_id):
    data = load_currency()
    return data.get(str(user_id), 0)

def add_balance(user_id, amount):
    data = load_currency()
    uid = str(user_id)
    data[uid] = data.get(uid, 0) + amount
    save_currency(data)

def subtract_balance(user_id, amount):
    data = load_currency()
    uid = str(user_id)
    if data.get(uid, 0) >= amount:
        data[uid] -= amount
        save_currency(data)
        return True
    return False
    
# カード画像結合関数
async def create_hand_image(card_names):
    images = []
    async with aiohttp.ClientSession() as session:
        for name in card_names:
            url = f"{CARD_IMAGE_BASE_URL}{name}.png"
            async with session.get(url) as resp:
                if resp.status == 200:
                    img_bytes = await resp.read()
                    img = Image.open(io.BytesIO(img_bytes)).convert("RGBA")
                    images.append(img)

    widths, heights = zip(*(i.size for i in images))
    total_width = sum(widths)
    max_height = max(heights)
    combined = Image.new('RGBA', (total_width, max_height))
    x_offset = 0
    for img in images:
        combined.paste(img, (x_offset, 0))
        x_offset += img.width

    buffer = io.BytesIO()
    combined.save(buffer, format="PNG")
    buffer.seek(0)
    return discord.File(fp=buffer, filename="hand.png")

# ゲーム状態クラス
class PokerGameState:
    def __init__(self, owner_id):
        self.owner_id = owner_id
        self.players = []
        self.started = False
        self.turn_index = 0
        self.folded = set()
        self.bets = {}
        self.pot = 0

# 参加ボタン
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

# アクションボタン
class PokerActionView(discord.ui.View):
    def __init__(self, game, player):
        super().__init__(timeout=60)
        self.game = game
        self.player = player

    @discord.ui.button(label="💰 ベット", style=discord.ButtonStyle.success)
    async def bet(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.game.bets[self.player.id] = 100
        self.game.pot += 100
        await interaction.response.send_message("💰 あなたは 100 チップをベットしました", ephemeral=True)
        self.stop()

    @discord.ui.button(label="📞 コール", style=discord.ButtonStyle.primary)
    async def call(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.game.bets[self.player.id] = 100
        self.game.pot += 100
        await interaction.response.send_message("📞 あなたは 100 チップをコールしました", ephemeral=True)
        self.stop()

    @discord.ui.button(label="📈 レイズ", style=discord.ButtonStyle.danger)
    async def raise_(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.game.bets[self.player.id] = 200
        self.game.pot += 200
        await interaction.response.send_message("📈 あなたは 200 チップをレイズしました", ephemeral=True)
        self.stop()

    @discord.ui.button(label="🙅 フォールド", style=discord.ButtonStyle.secondary)
    async def fold(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.game.folded.add(self.player.id)
        await interaction.response.send_message("🙅‍♂️ あなたはフォールドしました", ephemeral=True)
        self.stop()

# ターン処理関数（クラス外）
async def play_turn(interaction, game: PokerGameState):
    if game.turn_index >= len(game.players):
        await interaction.channel.send("🟢 全員のアクションが完了しました。次のフェーズに進みます。")
        return

    player = game.players[game.turn_index]
    if player.id in game.folded:
        game.turn_index += 1
        await play_turn(interaction, game)
        return

    await interaction.channel.send(f"🎯 現在のターン：{player.mention}")
    try:
        await player.send("あなたのアクションを選択してください：", view=PokerActionView(game, player))
    except discord.Forbidden:
        await interaction.channel.send(f"⚠️ {player.mention} にDMを送れませんでした。フォールド扱いにします。")
        game.folded.add(player.id)

    view = PokerActionView(game, player)
    await view.wait()

    game.turn_index += 1
    await play_turn(interaction, game)

# コマンド定義
@bot.tree.command(name="joinpoker", description="ポーカーの参加者を募集します", guild=discord.Object(id=GUILD_ID))
async def join_poker(interaction: discord.Interaction):
    if interaction.channel_id in POKER_GAMES:
        await interaction.response.send_message("このチャンネルではすでにポーカーが開催中です。", ephemeral=True)
        return
    POKER_GAMES[interaction.channel_id] = PokerGameState(owner_id=interaction.user.id)
    view = PokerJoinView(channel_id=interaction.channel_id)
    await interaction.response.send_message("🃏 ポーカーを開始しました！参加するには以下のボタンを押してください👇", view=view)

@bot.tree.command(name="chargem", description="VirtualCryptoで支払った分をBot内通貨にチャージします")
async def charge(interaction: discord.Interaction):
    await interaction.response.send_message("💸 最新の `/pay` メッセージを確認しています...", ephemeral=True)

    async for msg in interaction.channel.history(limit=20):
        if msg.author.bot and "/pay" in msg.content and interaction.user.name in msg.content:
            parts = msg.content.split()
            if len(parts) >= 3:
                try:
                    amount = int(parts[2].replace("spt", "").replace("Spt", ""))
                    add_balance(interaction.user.id, amount)
                    await interaction.followup.send(f"✅ {amount} spt をチャージしました！現在の残高: {get_balance(interaction.user.id)} spt", ephemeral=True)
                    return
                except ValueError:
                    continue

    await interaction.followup.send("⚠️ `/pay` メッセージが見つかりませんでした。再度 `/pay` を送信してください。", ephemeral=True)

LOG_CHANNEL_ID = 1401466622149005493  # ログチャンネルのIDを必ず設定

@bot.tree.command(name="changem", description="Bot内通貨を換金申請します（手動振込）")
@app_commands.describe(amount="換金する通貨量")
async def change(interaction: discord.Interaction, amount: int):
    if amount <= 0:
        await interaction.response.send_message("⚠️ 金額は1以上にしてください。", ephemeral=True)
        return

    if subtract_balance(interaction.user.id, amount):
        await interaction.response.send_message(f"💰 {amount} spt の換金申請を受け付けました。", ephemeral=True)

        log_channel = bot.get_channel(LOG_CHANNEL_ID)
        if log_channel:
            await log_channel.send(f"💸 {interaction.user.mention} が {amount} spt の換金を申請しました。 `/pay` にて振込をお願いします。")
        else:
            await interaction.channel.send("⚠️ ログチャンネルが見つかりませんでした。")
    else:
        await interaction.response.send_message("❌ 残高が不足しています。", ephemeral=True)

@bot.tree.command(name="walletm", description="現在のBot内通貨残高を確認します")
async def wallet(interaction: discord.Interaction):
    balance = get_balance(interaction.user.id)
    await interaction.response.send_message(f"💼 あなたの残高は {balance} spt です。", ephemeral=True)
    
@bot.tree.command(name="startpoker", description="ポーカーゲームを開始します（主催者のみ）", guild=discord.Object(id=GUILD_ID))
async def start_poker(interaction: discord.Interaction):
    game = POKER_GAMES.get(interaction.channel_id)
    if not game:
        await interaction.response.send_message("ポーカーが開始されていません。", ephemeral=True)
        return
    if interaction.user.id != game.owner_id:
        await interaction.response.send_message("このコマンドは主催者のみ使用できます。", ephemeral=True)
        return
    if len(game.players) < 2:
        await interaction.response.send_message("プレイヤーが2人以上必要です。", ephemeral=True)
        return
    if game.started:
        await interaction.response.send_message("すでにゲームが開始されています。", ephemeral=True)
        return

    game.started = True
    await interaction.response.send_message("🃏 ポーカーを開始します！ プレイヤーに手札を配ります。")

    deck = CARD_DECK.copy()
    random.shuffle(deck)
    for player in game.players:
        hand = [deck.pop() for _ in range(5)]
        file = await create_hand_image(hand)
        try:
            await player.send(content="🎴 あなたの手札はこちら：", file=file)
        except discord.Forbidden:
            await interaction.channel.send(f"⚠️ {player.mention} にDMを送れませんでした。")

    await play_turn(interaction, game)

# 同期コマンド
@bot.command()
async def sync(ctx):
    await bot.tree.sync(guild=ctx.guild)
    await ctx.send("✅ コマンドを再同期しました")

# 起動時
@bot.event
async def on_ready():
    bot.add_view(PokerJoinView(None))
    await bot.tree.sync(guild=discord.Object(id=GUILD_ID))
    print(f"✅ Bot connected as {bot.user}")

# 起動
keep_alive()
bot.run(os.environ["DISCORD_TOKEN"])



