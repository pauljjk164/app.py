from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    MessageHandler,
    filters,
    ConversationHandler,
    CallbackQueryHandler
)
import asyncio
import re
import random
import os
from datetime import datetime, timedelta

# ========== CONFIGURATION ==========
BOT_TOKEN = os.getenv('BOT_TOKEN')
WITHDRAWAL_CHANNEL = "https://t.me/INVITORCASHPH"
ARENA_LIVE_URL = "https://arenalive.ph/s/JOyiswx"
PUZZLE_REWARD = 200  # Updated to ₱200 per win

# ========== STATE CONSTANTS ==========
VERIFYING, MAIN_MENU = range(2)
WITHDRAWAL, GAME, AWAITING_REGISTRATION = range(2, 5)

# ========== DATABASE SCHEMA (SQLite/PostgreSQL) ==========
# Users Table:
#   user_id: INTEGER PRIMARY KEY
#   balance: FLOAT DEFAULT 0.0
#   invites: INTEGER DEFAULT 0
#   verified: BOOLEAN DEFAULT FALSE
#   last_activity: DATETIME
#   wallet_info: TEXT (JSON: {"name": "", "number": "", "type": ""})
#
# Invites Table:
#   referrer_id: INTEGER
#   invitee_id: INTEGER
#   timestamp: DATETIME

# ========== KEY HANDLERS ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    # Save new user to DB with balance=0, invites=0, verified=False
    
    # Force channel joins
    keyboard = [
        [InlineKeyboardButton("✅ JOIN WITHDRAWAL CHANNEL", url=WITHDRAWAL_CHANNEL)],
        [InlineKeyboardButton("✅ REGISTER AT ARENA LIVE", url=ARENA_LIVE_URL)],
        [InlineKeyboardButton("I'VE COMPLETED BOTH", callback_data="start_verification")]
    ]
    await update.message.reply_text(
        "🎮 *WELCOME TO GAME CASH PH* 🎮\n\n"
        "💰 *EARN UP TO ₱10,000 DAILY!*\n\n"
        "⚠️ *REQUIRED VERIFICATION STEPS:*\n"
        "1. Join withdrawal channel: [INVITOR CASHPH]({})\n"
        "2. Register at our partner: [Arena Live]({})\n\n"
        "🚫 *Bot locked until verification complete*".format(WITHDRAWAL_CHANNEL, ARENA_LIVE_URL),
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
        disable_web_page_preview=True
    )
    return VERIFYING

async def start_verification(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    # Start 2-minute verification period
    await query.edit_message_text(
        "⏳ *VERIFICATION IN PROGRESS* ⏳\n\n"
        "Processing your Arena Live registration...\n"
        "Estimated time: 2 minutes\n\n"
        "⚠️ Do NOT use bot during this process\n"
        "We'll notify you when verification completes"
    )
    
    # Set verification end time (2 minutes from now)
    verify_until = datetime.now() + timedelta(minutes=2)
    context.user_data['verify_until'] = verify_until
    
    # Move to waiting state
    return AWAITING_REGISTRATION

async def check_verification(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Check if 2 minutes have passed
    if datetime.now() >= context.user_data['verify_until']:
        # Update DB: user.verified = True
        await update.message.reply_text(
            "✅ *VERIFICATION SUCCESSFUL!*\n\n"
            "You now have full access to:\n"
            "• 🎮 Puzzle Game: Win ₱200 per correct answer\n"
            "• 👥 Referral Program: Earn ₱30 per friend\n"
            "• 💰 Withdrawals: Min ₱5,000 after 5 invites"
        )
        return await main_menu(update, context)
    else:
        remaining = (context.user_data['verify_until'] - datetime.now()).seconds // 60
        await update.message.reply_text(
            "⏳ Verification still in progress\n"
            f"Estimated time remaining: {remaining} minutes\n\n"
            "Please wait without using any commands"
        )
        return AWAITING_REGISTRATION

async def main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Fetch user data from DB
    user_balance = 0.0  # Replace with actual DB fetch
    user_invites = 0    # Replace with actual DB fetch
    
    keyboard = [
        ["💰 ACCOUNT BALANCE", "🎮 PLAY PUZZLE GAME"],
        ["📤 WITHDRAW FUNDS", "👥 INVITE FRIENDS"],
        ["ℹ️ HELP & SUPPORT"]
    ]
    await update.message.reply_text(
        f"🏦 *MAIN MENU* • BALANCE: ₱{user_balance:.2f}\n\n"
        "1. 🎮 Play Puzzle Game - Win ₱200 per correct answer\n"
        "2. 👥 Invite Friends - Earn ₱30 per successful referral\n"
        "3. 📤 Withdraw - Min ₱5,000 (requires 5 invites)\n\n"
        f"Your current invites: {user_invites}/5",
        reply_markup=ReplyKeyboardMarkup(
            keyboard, 
            one_time_keyboard=True,
            resize_keyboard=True
        )
    )
    return MAIN_MENU

# ========== PUZZLE GAME HANDLERS ==========
async def start_puzzle_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Generate puzzle options
    options = ["A", "B", "C", "D"]
    correct = random.choice(options)
    context.user_data['correct_answer'] = correct
    
    keyboard = [
        [InlineKeyboardButton(opt, callback_data=f"puzzle_{opt}") 
        for opt in options]
    ]
    
    await update.message.reply_text(
        "🧩 *PUZZLE GAME* 🧩\n\n"
        "Find the missing piece to win ₱200!\n\n"
        "SELECT YOUR ANSWER:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return GAME

async def handle_puzzle_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    selected = query.data.split('_')[1]
    correct = context.user_data['correct_answer']
    
    if selected == correct:
        # Update DB: balance += PUZZLE_REWARD
        new_balance = 0.0  # Replace with actual DB update
        
        await query.edit_message_text(
            f"🎉 *CONGRATULATIONS!* 🎉\n\n"
            f"Your answer is correct!\n"
            f"+₱{PUZZLE_REWARD} credited to your account\n"
            f"New balance: ₱{new_balance:.2f}\n\n"
            "Play again to earn more!"
        )
    else:
        await query.edit_message_text(
            "❌ Incorrect! Try again?\n\n"
            "You can still win ₱200!",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("TRY AGAIN", callback_data="retry_puzzle")]
            )
        )
    
    return MAIN_MENU

async def retry_puzzle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    return await start_puzzle_game(update, context)

# ========== REFERRAL SYSTEM ==========
async def handle_invites(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    ref_link = f"https://t.me/{context.bot.username}?start=ref_{user_id}"
    
    await update.message.reply_text(
        "👥 *INVITE & EARN PROGRAM* 👥\n\n"
        "• Earn ₱30 for every friend who completes verification\n"
        "• No limits - invite unlimited friends\n"
        "• Withdrawals require 5 successful invites\n\n"
        "Your unique referral link:\n"
        f"`{ref_link}`\n\n"
        "Share this link with friends to start earning!",
        parse_mode="Markdown"
    )

async def track_referral(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # When user starts with referral link: /start ref_12345
    if context.args and context.args[0].startswith('ref_'):
        referrer_id = int(context.args[0][4:])
        invitee_id = update.effective_user.id
        
        # Save to DB: referrer_id + invitee_id
        # When invitee completes verification:
        #   referrer.balance += 30
        #   referrer.invites += 1
        #   Send notification to referrer

# ========== WITHDRAWAL SYSTEM ==========
async def handle_withdrawal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Fetch user data from DB
    user_balance = 0.0
    user_invites = 0
    
    if user_invites < 5:
        await update.message.reply_text(
            "⚠️ *WITHDRAWAL REQUIREMENT*\n\n"
            "You need 5 successful invites to withdraw\n"
            f"Current invites: {user_invites}/5\n\n"
            "Invite more friends using /invite"
        )
        return MAIN_MENU
    
    await update.message.reply_text(
        "📤 *WITHDRAW FUNDS*\n\n"
        f"Current Balance: ₱{user_balance:.2f}\n"
        "• Minimum: ₱5,000\n"
        "• Maximum: ₱20,000\n\n"
        "Enter amount to withdraw:"
    )
    return WITHDRAWAL

async def process_withdrawal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    amount_text = update.message.text
    try:
        amount = float(amount_text)
        # Validate amount
        if amount < 5000:
            await update.message.reply_text("❌ Minimum withdrawal is ₱5,000")
            return WITHDRAWAL
        if amount > 20000:
            await update.message.reply_text("❌ Maximum withdrawal is ₱20,000")
            return WITHDRAWAL
        
        # Check sufficient balance
        user_balance = 0.0  # Fetch from DB
        if amount > user_balance:
            await update.message.reply_text("❌ Insufficient funds")
            return WITHDRAWAL
        
        # Save amount in context
        context.user_data['withdraw_amount'] = amount
        
        # Request wallet info
        await update.message.reply_text(
            "💳 *ENTER WALLET INFORMATION*\n\n"
            "Format:\n"
            "Name: Your Full Name\n"
            "Number: 09XXXXXXXXX\n"
            "Wallet: GCash/PayMaya\n\n"
            "Example:\n"
            "Name: Juan Dela Cruz\n"
            "Number: 09123456789\n"
            "Wallet: GCash"
        )
        return WITHDRAWAL
    
    except ValueError:
        await update.message.reply_text("❌ Invalid amount. Please enter a number")
        return WITHDRAWAL

async def confirm_withdrawal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    wallet_info = update.message.text
    # Validate and parse wallet info
    context.user_data['wallet_info'] = wallet_info
    
    amount = context.user_data['withdraw_amount']
    
    keyboard = [[InlineKeyboardButton("CONFIRM WITHDRAWAL", callback_data="withdraw_confirm")]]
    
    await update.message.reply_text(
        f"⚠️ *CONFIRM WITHDRAWAL: ₱{amount:.2f}*\n\n"
        f"Wallet Details:\n{wallet_info}\n\n"
        "This action cannot be undone",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def execute_withdrawal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    amount = context.user_data['withdraw_amount']
    wallet_info = context.user_data['wallet_info']
    
    # Update DB: 
    #   balance -= amount
    #   Add withdrawal record (status: PENDING)
    
    # Get current invites
    user_invites = 0  # Fetch from DB
    
    await query.edit_message_text(
        f"✅ WITHDRAWAL REQUESTED: ₱{amount:.2f}\n\n"
        "📝 *ADMIN APPROVAL REQUIRED*\n\n"
        "To complete withdrawal:\n"
        "1. Invite 5 friends using your link\n"
        f"   Current: {user_invites}/5 invites\n"
        "2. Wait 20-30 minutes for processing\n\n"
        "Your referral link:\n"
        f"https://t.me/{context.bot.username}?start=ref_{query.from_user.id}"
    )
    return MAIN_MENU

# ========== BOT SETUP ==========
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            VERIFYING: [
                CallbackQueryHandler(start_verification, pattern="^start_verification$")
            ],
            AWAITING_REGISTRATION: [
                MessageHandler(filters.ALL, check_verification)
            ],
            MAIN_MENU: [
                MessageHandler(filters.Regex(r"^🎮 PLAY PUZZLE GAME$"), start_puzzle_game),
                MessageHandler(filters.Regex(r"^👥 INVITE FRIENDS$"), handle_invites),
                MessageHandler(filters.Regex(r"^📤 WITHDRAW FUNDS$"), handle_withdrawal),
                MessageHandler(filters.Regex(r"^💰 ACCOUNT BALANCE$"), show_balance),
            ],
            WITHDRAWAL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, process_withdrawal),
                MessageHandler(filters.Regex(r"^💰 ACCOUNT BALANCE$"), show_balance),
            ],
            GAME: [
                CallbackQueryHandler(handle_puzzle_answer, pattern="^puzzle_"),
                CallbackQueryHandler(retry_puzzle, pattern="^retry_puzzle$"),
            ]
        },
        fallbacks=[CommandHandler("start", start)],
        allow_reentry=True
    )
    
    # Add referral tracking
    app.add_handler(CommandHandler("start", track_referral, filters=filters.Regex(r'ref_\d+'))
    
    app.add_handler(conv_handler)
    app.add_handler(CallbackQueryHandler(execute_withdrawal, pattern="^withdraw_confirm$"))
    
    app.run_polling()

if __name__ == "__main__":
    main()
