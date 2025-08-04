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
import asyncio

VIRTUALCRYPTO_ID = 800892182633381950

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

def evaluate_hand(cards):
    values_order = {'2': 2, '3': 3, '4': 4, '5': 5, '6': 6,
                    '7': 7, '8': 8, '9': 9, '10': 10,
                    'J': 11, 'Q': 12, 'K': 13, 'A': 14}
    suits = [c.split('_')[0] for c in cards]
    values = sorted([values_order[c.split('_')[1]] for c in cards])
    counts = {v: values.count(v) for v in set(values)}

    is_flush = len(set(suits)) == 1
    is_straight = values == list(range(min(values), max(values)+1))

    if is_flush and is_straight:
        return (8, max(values))  # ストレートフラッシュ
    elif 4 in counts.values():
        return (7, max(k for k, v in counts.items() if v == 4))  # フォーカード
    elif sorted(counts.values()) == [2, 3]:
        return (6, max(k for k, v in counts.items() if v == 3))  # フルハウス
    elif is_flush:
        return (5, max(values))  # フラッシュ
    elif is_straight:
        return (4, max(values))  # ストレート
    elif 3 in counts.values():
        return (3, max(k for k, v in counts.items() if v == 3))  # スリーカード
    elif list(counts.values()).count(2) == 2:
        return (2, max(k for k, v in counts.items() if v == 2))  # ツーペア
    elif 2 in counts.values():
        return (1, max(k for k, v in counts.items() if v == 2))  # ワンペア
    else:
        return (0, max(values))  # ハイカード
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
        self.round_bets = {}      # 各プレイヤーがこのラウンドで賭けた額
        self.current_bet = 0      # 現在の最高ベット額
        self.first_round = True   # 一巡目フラグ
        self.hands = {}  # ← 追加：プレイヤーの手札保存用
        
async def exchange_cards(interaction: discord.Interaction, game: PokerGameState, deck: list):
    for player in game.players:
        if player.id in game.folded:
            continue  # フォールド者はスキップ

        try:
            await player.send(
                "🃏 **カード交換フェーズです！**\n"
                "交換したいカードの位置（1〜5）を**半角スペース区切り**で入力してください。\n"
                "例: `2 4 5`（最大3枚まで）\n"
                "交換しない場合は `0` を入力してください。"
            )

            def check(m: discord.Message):
                return m.author == player and isinstance(m.channel, discord.DMChannel)

            msg = await bot.wait_for('message', check=check, timeout=60)
            input_text = msg.content.strip()

            if input_text == "0":
                await player.send("📩 カードを交換しませんでした。")
                continue

            indexes = list(map(int, input_text.split()))
            if len(indexes) > 3 or not all(1 <= i <= 5 for i in indexes):
                await player.send("⚠️ 入力が無効です。交換はスキップされました。")
                continue

            old_hand = game.hands[player.id]
            for i in indexes:
                old_hand[i - 1] = deck.pop()

            file = await create_hand_image(old_hand)
            await player.send("🎴 新しい手札はこちらです：", file=file)
            await interaction.channel.send(f"🔁 {player.mention} が {len(indexes)} 枚のカードを交換しました。")

        except asyncio.TimeoutError:
            await interaction.channel.send(f"⏱️ {player.mention} のカード交換が時間切れになりました。スキップします。")
        except Exception as e:
            await interaction.channel.send(f"⚠️ {player.mention} の交換処理でエラーが発生しました。{e}")

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
    def __init__(self, game, player, is_first_player):
        super().__init__(timeout=60)
        self.game = game
        self.player = player
        self.is_first_player = is_first_player
        self.selected_amount = 0
        self.action = None

        if not is_first_player:
            self.add_item(self.call_button)
            self.add_item(self.raise_button)

    @discord.ui.button(label="💰 ベット", style=discord.ButtonStyle.success, row=0)
    async def bet_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.is_first_player:
            await interaction.response.send_message("このアクションは現在使用できません（すでにベットが行われています）。", ephemeral=True)
            return

        await interaction.response.send_message("💰 100〜500 Spt の間でベット額を入力してください。", ephemeral=True)

        def check(m: discord.Message):
            return m.author == interaction.user and m.channel == interaction.channel

        try:
            msg = await bot.wait_for('message', timeout=30.0, check=check)
            amount = int(msg.content)
            if 100 <= amount <= 500:
                if subtract_balance(self.player.id, amount):
                    self.selected_amount = amount
                    self.action = "bet"
                    self.game.round_bets[self.player.id] = amount
                    self.game.current_bet = amount
                    self.game.pot += amount
                    await interaction.followup.send(f"✅ {amount} Spt をベットしました！", ephemeral=True)
                    self.stop()
                else:
                    await interaction.followup.send("❌ 残高が不足しています。", ephemeral=True)
            else:
                await interaction.followup.send("❌ 金額は100〜500の間で指定してください。", ephemeral=True)
        except asyncio.TimeoutError:
            await interaction.followup.send("⏱️ 入力が時間切れになりました。", ephemeral=True)
        except ValueError:
            await interaction.followup.send("❌ 数値を入力してください。", ephemeral=True)

    @discord.ui.button(label="📞 コール", style=discord.ButtonStyle.primary, row=1, custom_id="call_button", disabled=True)
    async def call_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        required = self.game.current_bet - self.game.round_bets.get(self.player.id, 0)
        if required <= 0:
            await interaction.response.send_message("✅ すでに必要な額を支払っています。", ephemeral=True)
            self.stop()
            return

        if subtract_balance(self.player.id, required):
            self.selected_amount = required
            self.action = "call"
            self.game.round_bets[self.player.id] = self.game.round_bets.get(self.player.id, 0) + required
            self.game.pot += required
            await interaction.response.send_message(f"📞 {required} Spt をコールしました！", ephemeral=True)
            self.stop()
        else:
            await interaction.response.send_message("❌ 残高が不足しています。", ephemeral=True)

    @discord.ui.button(label="📈 レイズ", style=discord.ButtonStyle.danger, row=1, custom_id="raise_button", disabled=True)
    async def raise_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        current = self.game.current_bet
        await interaction.response.send_message(f"📈 {current} Spt 以上の金額を入力してください（最大500）。", ephemeral=True)

        def check(m: discord.Message):
            return m.author == interaction.user and m.channel == interaction.channel

        try:
            msg = await bot.wait_for('message', timeout=30.0, check=check)
            raise_amount = int(msg.content)
            if raise_amount > current and raise_amount <= 500:
                if subtract_balance(self.player.id, raise_amount):
                    self.selected_amount = raise_amount
                    self.action = "raise"
                    self.game.round_bets[self.player.id] = raise_amount
                    self.game.current_bet = raise_amount
                    self.game.pot += raise_amount
                    await interaction.followup.send(f"📈 {raise_amount} Spt にレイズしました！", ephemeral=True)
                    self.stop()
                else:
                    await interaction.followup.send("❌ 残高が不足しています。", ephemeral=True)
            else:
                await interaction.followup.send("❌ 有効なレイズ額を入力してください（現在のベットより多く、最大500まで）。", ephemeral=True)
        except asyncio.TimeoutError:
            await interaction.followup.send("⏱️ 入力が時間切れになりました。", ephemeral=True)
        except ValueError:
            await interaction.followup.send("❌ 数値を入力してください。", ephemeral=True)

    @discord.ui.button(label="🙅 フォールド", style=discord.ButtonStyle.secondary, row=2)
    async def fold_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.game.folded.add(self.player.id)
        self.action = "fold"
        await interaction.response.send_message("🙅‍♂️ フォールドしました。", ephemeral=True)
        self.stop()

# ターン処理関数（クラス外）


async def play_turn(interaction: discord.Interaction, game: PokerGameState):
    while game.turn_index < len(game.players):
        player = game.players[game.turn_index]

        # フォールド済プレイヤーはスキップ
        if player.id in game.folded:
            game.turn_index += 1
            continue

        # コール・レイズが可能かの判定（一巡目の最初のみFalse）
        is_first_player = (game.turn_index == 0 and all(v == 0 for v in game.round_bets.values()))
        view = PokerActionView(game, player, is_first_player=is_first_player)

        await interaction.channel.send(
            f"🎯 現在のターン：{player.mention}（現在のベット額：{game.current_bet} Spt）"
        )

        try:
            await player.send("あなたのアクションを選択してください：", view=view)
        except discord.Forbidden:
            await interaction.channel.send(f"⚠️ {player.mention} にDMを送信できませんでした。フォールド扱いにします。")
            game.folded.add(player.id)
            game.turn_index += 1
            continue

        await view.wait()
        game.turn_index += 1

    await interaction.channel.send("🟢 全員のアクションが完了しました。次のフェーズに進みます。")
async def exchange_cards(interaction: discord.Interaction, game: PokerGameState, deck: list):
    await interaction.channel.send("🔄 手札交換フェーズを開始します。全プレイヤーにDMを送信しています。")

    player_hands = {}

    for player in game.players:
        player_hands[player.id] = [deck.pop() for _ in range(5)]  # 初回仮実装（将来は保存された手札を使用）

    for player in game.players:
        if player.id in game.folded:
            continue

        try:
            await player.send(
                "✉️ 交換したいカードの位置を「1,3,5」のようにカンマ区切りで入力してください（最大3枚まで）。\n"
                "交換しない場合は `なし` または `0` と入力してください。"
            )
        except discord.Forbidden:
            await interaction.channel.send(f"⚠️ {player.mention} にDMを送れませんでした。交換スキップします。")
            continue

    def check(m: discord.Message):
        return m.guild is None and m.author.id in [p.id for p in game.players]

    end_time = asyncio.get_event_loop().time() + 30
    responded = set()

    while asyncio.get_event_loop().time() < end_time and len(responded) < len(game.players):
        try:
            msg = await bot.wait_for("message", timeout=end_time - asyncio.get_event_loop().time(), check=check)
            user_id = msg.author.id
            if user_id in responded:
                continue
            responded.add(user_id)

            content = msg.content.strip().lower().replace(" ", "").replace("　", "")
            if content in ["0", "なし", "なし。", "交換なし"]:
                await msg.channel.send("👌 交換しない選択が確認されました。")
                continue

            indexes = content.split(",")
            if len(indexes) > 3:
                await msg.channel.send("⚠️ 交換は最大3枚までです。")
                continue

            current_hand = player_hands.get(user_id, [deck.pop() for _ in range(5)])
            new_hand = current_hand[:]

            for i in indexes:
                if i.isdigit():
                    idx = int(i) - 1
                    if 0 <= idx < 5:
                        new_hand[idx] = deck.pop()

            player_hands[user_id] = new_hand

            file = await create_hand_image(new_hand)
            await msg.author.send("🆕 新しい手札はこちらです：", file=file)

        except asyncio.TimeoutError:
            break
        except Exception as e:
            print(f"交換中のエラー: {e}")

    await interaction.channel.send("✅ 交換フェーズが終了しました。次のアクションに進みます。")
    
# showdown関数（同点対応版）
async def showdown(interaction: discord.Interaction, game: PokerGameState):
    results = []

    for player in game.players:
        if player.id in game.folded:
            continue
        try:
            messages = await player.history(limit=10).flatten()
            for msg in messages:
                if msg.attachments:
                    filename = msg.attachments[0].filename
                    card_names = filename.replace("hand:", "").replace(".png", "").split(",")
                    hand_value = evaluate_hand(card_names)
                    results.append((player, hand_value))
                    break
        except Exception:
            continue

    if not results:
        await interaction.channel.send("❌ 勝者を判定できませんでした。")
        return

    results.sort(key=lambda x: x[1], reverse=True)
    top_score = results[0][1]
    winners = [p for p, score in results if score == top_score]

    if len(winners) == 1:
        winner = winners[0]
        add_balance(winner.id, game.pot)
        await interaction.channel.send(f"🏆 勝者は {winner.mention} です！ポット {game.pot} Spt を獲得しました！")
    else:
        share = game.pot // len(winners)
        for winner in winners:
            add_balance(winner.id, share)
        winner_mentions = ", ".join(w.mention for w in winners)
        await interaction.channel.send(f"🤝 引き分けです！{winner_mentions} がそれぞれ {share} Spt を獲得しました。")


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

@bot.tree.command(name="chargem", description="VirtualCryptoで支払った分をBot内通貨にチャージします", guild=discord.Object(id=GUILD_ID))
@app_commands.describe(amount="チャージする通貨量（例：1000）")
async def chargem(interaction: discord.Interaction, amount: int):
    if amount <= 0:
        await interaction.response.send_message("⚠️ 金額は1以上で指定してください。", ephemeral=True)
        return

    await interaction.response.send_message(
        f"💰 `{amount}Spt` を VirtualCrypto 経由で「{bot.user.name}」宛に送金してください。\n"
        f"制限時間：**3分以内**に送金が確認されるとチャージされます。",
        ephemeral=False
    )

    def check(msg: discord.Message):
        description = msg.embeds[0].description if msg.embeds else ""
        return (
            msg.author.id == VIRTUALCRYPTO_ID and
            f"<@{interaction.user.id}>から<@{bot.user.id}>へ" in description and
            f"{amount}" in description and
            "Spt" in description
        )

    try:
        msg = await bot.wait_for("message", timeout=180, check=check)
        add_balance(interaction.user.id, amount)
        await interaction.channel.send(f"✅ {interaction.user.mention} さん、{amount} Spt のチャージが完了しました！\n💼 現在の残高：{get_balance(interaction.user.id)} Spt")
    except asyncio.TimeoutError:
        await interaction.channel.send(f"⏱️ {interaction.user.mention} さん、**3分以内に送金が確認できませんでした**。もう一度 `/chargem` を実行してください。")

LOG_CHANNEL_ID = 1401466622149005493  # ログチャンネルのIDを必ず設定

@bot.tree.command(name="changem", description="Bot内通貨を換金申請します（手動振込）", guild=discord.Object(id=GUILD_ID))
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

@bot.tree.command(name="walletm", description="現在のBot内通貨残高を確認します", guild=discord.Object(id=GUILD_ID))
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

    # デッキ準備
    deck = CARD_DECK.copy()
    random.shuffle(deck)

    # 手札配布と参加費処理
    for player in game.players:
        hand = [deck.pop() for _ in range(5)]
        file = await create_hand_image(hand)
        try:
            await player.send(content="🎴 あなたの手札はこちら：", file=file)
            subtract_balance(player.id, 100)
            await player.send("💸 参加費として 100 Spt を支払いました。")
        except discord.Forbidden:
            await interaction.channel.send(f"⚠️ {player.mention} にDMを送れませんでした。")

    # ゲーム状態初期化（1巡目）
    game.turn_index = 0
    game.first_round = True
    game.round_bets = {}
    game.current_bet = 0

    # ▶️ 1巡目アクション
    await play_turn(interaction, game)

    # 🔁 カード交換フェーズ
    await exchange_cards(interaction, game, deck)

    # ゲーム状態初期化（2巡目）
    game.turn_index = 0
    game.first_round = False
    game.round_bets = {}
    game.current_bet = 0

    # ▶️ 2巡目アクション
    await play_turn(interaction, game)

    # 🏆 ショウダウン（勝敗判定）
    await showdown(interaction, game)

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























