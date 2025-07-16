import os
import random
import time
import sqlite3
import logging
import string
import threading
from datetime import datetime, timedelta
from captcha.image import ImageCaptcha
from flask import Flask, request
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    InputFile
)
from telegram.ext import (
    Updater,
    CommandHandler,
    MessageHandler,
    Filters,
    CallbackContext,
    ConversationHandler,
    CallbackQueryHandler
)

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', 
    level=logging.INFO,
    handlers=[
        logging.FileHandler("bot.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Bot configuration
TOKEN = "8161112328:AAEgZCq_RPbqklrfSsE-p0YVbhiNH53snP4"
REQUIRED_CHANNEL = "@INVITORCASHPH"  # Users must join this channel
ARENA_LIVE_LINK = "https://arenalive.ph/s/9dKo9ss"  # Updated partner link
CAPTCHA_REWARD = 50
INVITE_REWARD = 30
MIN_WITHDRAWAL = 5000
MAX_WITHDRAWAL = 20000
REQUIRED_INVITES = 10
PORT = int(os.environ.get('PORT', 5000))
VERIFICATION_WAIT_TIME = 180  # 3 minutes in seconds

# Create Flask app for keep-alive
app = Flask(__name__)

@app.route('/')
def home():
    return "INVITOR CASH PH BOT is running!", 200

def run_flask():
    app.run(host='0.0.0.0', port=PORT)

# Conversation states
VERIFICATION, CHANNEL_JOIN, CAPTCHA_GAME, WITHDRAW_AMOUNT, WITHDRAW_INFO = range(5)

# Database setup
conn = sqlite3.connect('game_cash.db', check_same_thread=False)
c = conn.cursor()

# Create tables
c.execute('''CREATE TABLE IF NOT EXISTS users
             (user_id INTEGER PRIMARY KEY, 
              username TEXT,
              balance INTEGER DEFAULT 0,
              invite_code TEXT,
              invited_by INTEGER DEFAULT 0,
              invite_count INTEGER DEFAULT 0,
              verified BOOLEAN DEFAULT 0,
              verification_time TEXT,
              withdrawal_pending BOOLEAN DEFAULT 0,
              registration_time TEXT,
              channel_joined BOOLEAN DEFAULT 0)''')  # Added channel_joined

c.execute('''CREATE TABLE IF NOT EXISTS captchas
             (id INTEGER PRIMARY KEY AUTOINCREMENT,
              user_id INTEGER,
              captcha_solution TEXT,
              timestamp TEXT)''')

c.execute('''CREATE TABLE IF NOT EXISTS withdrawals
             (id INTEGER PRIMARY KEY AUTOINCREMENT,
              user_id INTEGER,
              amount INTEGER,
              wallet_info TEXT,
              status TEXT DEFAULT 'PENDING',
              timestamp TEXT)''')
conn.commit()

# Database helper functions
def get_user(user_id):
    try:
        c.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
        return c.fetchone()
    except Exception as e:
        logger.error(f"Database error in get_user: {e}")
        return None

def create_user(user_id, username, invited_by=None):
    try:
        invite_code = f"ref{random.randint(10000, 99999)}"
        registration_time = datetime.now().isoformat()
        if invited_by:
            c.execute("INSERT INTO users (user_id, username, invite_code, invited_by, registration_time) VALUES (?, ?, ?, ?, ?)", 
                     (user_id, username, invite_code, invited_by, registration_time))
        else:
            c.execute("INSERT INTO users (user_id, username, invite_code, registration_time) VALUES (?, ?, ?, ?)", 
                     (user_id, username, invite_code, registration_time))
        conn.commit()
        return invite_code
    except Exception as e:
        logger.error(f"Database error in create_user: {e}")
        return None

def update_balance(user_id, amount):
    try:
        c.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (amount, user_id))
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Database error in update_balance: {e}")
        return False

def increment_invite_count(user_id):
    try:
        c.execute("UPDATE users SET invite_count = invite_count + 1 WHERE user_id=?", (user_id,))
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Database error in increment_invite_count: {e}")
        return False

def set_verified(user_id):
    try:
        verification_time = datetime.now().isoformat()
        c.execute("UPDATE users SET verified=1, verification_time=? WHERE user_id=?", 
                 (verification_time, user_id))
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Database error in set_verified: {e}")
        return False

def set_channel_joined(user_id):
    try:
        c.execute("UPDATE users SET channel_joined=1 WHERE user_id=?", (user_id,))
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Database error in set_channel_joined: {e}")
        return False

def set_withdrawal_pending(user_id, status):
    try:
        c.execute("UPDATE users SET withdrawal_pending=? WHERE user_id=?", (status, user_id))
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Database error in set_withdrawal_pending: {e}")
        return False

def save_withdrawal(user_id, amount, wallet_info):
    try:
        timestamp = datetime.now().isoformat()
        c.execute("INSERT INTO withdrawals (user_id, amount, wallet_info, timestamp) VALUES (?, ?, ?, ?)",
                 (user_id, amount, wallet_info, timestamp))
        conn.commit()
        return update_balance(user_id, -amount)
    except Exception as e:
        logger.error(f"Database error in save_withdrawal: {e}")
        return False

def save_captcha(user_id, solution):
    try:
        timestamp = datetime.now().isoformat()
        c.execute("INSERT INTO captchas (user_id, captcha_solution, timestamp) VALUES (?, ?, ?)",
                 (user_id, solution, timestamp))
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Database error in save_captcha: {e}")
        return False

def can_verify(user_id):
    """Check if user can verify (3 minutes have passed since registration)"""
    try:
        user_data = get_user(user_id)
        if not user_data or not user_data[9]:  # registration_time
            return False
        
        registration_time = datetime.fromisoformat(user_data[9])
        current_time = datetime.now()
        time_diff = current_time - registration_time
        
        return time_diff.total_seconds() >= VERIFICATION_WAIT_TIME
    except Exception as e:
        logger.error(f"Error in can_verify: {e}")
        return False

def get_remaining_wait_time(user_id):
    """Get remaining wait time in seconds"""
    try:
        user_data = get_user(user_id)
        if not user_data or not user_data[9]:
            return 0
        
        registration_time = datetime.fromisoformat(user_data[9])
        current_time = datetime.now()
        elapsed = current_time - registration_time
        remaining = VERIFICATION_WAIT_TIME - elapsed.total_seconds()
        
        return max(0, int(remaining))
    except Exception as e:
        logger.error(f"Error in get_remaining_wait_time: {e}")
        return 0

# Generate CAPTCHA image
def generate_captcha():
    try:
        # Generate random 5-character string
        captcha_text = ''.join(random.choices(string.ascii_uppercase + string.digits, k=5))
        
        # Create image captcha
        image = ImageCaptcha(width=280, height=90)
        data = image.generate(captcha_text)
        
        # Save to temporary file
        filename = f"captcha_{captcha_text}.png"
        image.write(captcha_text, filename)
        
        return filename, captcha_text
    except Exception as e:
        logger.error(f"CAPTCHA generation error: {e}")
        return None, None

# Start command handler
def start(update: Update, context: CallbackContext) -> int:
    try:
        user = update.effective_user
        username = user.username or user.first_name or "User"
        user_data = get_user(user.id)
        
        # Check if user exists
        if not user_data:
            # Check if coming from referral
            invited_by = None
            if context.args and context.args[0].startswith('ref'):
                try:
                    invited_by = int(context.args[0][3:])
                except ValueError:
                    pass
            invite_code = create_user(user.id, username, invited_by)
            
            # Reward referrer
            if invited_by:
                update_balance(invited_by, INVITE_REWARD)
                increment_invite_count(invited_by)
        
        # Get updated user data
        user_data = get_user(user.id)
        
        # Check if user can verify
        if not user_data[6] and can_verify(user.id):
            # Show verification button
            context.bot.send_message(
                chat_id=user.id,
                text=f"🌟 *Welcome to Game Cash PH!* 🌟\n\n"
                     "You can now complete verification:\n"
                     f"1. Register at our partner site: [Arena Live]({ARENA_LIVE_LINK})\n"
                     "2. Click the button below after registration\n\n"
                     "⚠️ You MUST join our channel to withdraw funds!",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("✅ I've Completed Registration", callback_data="verify")
                ]])
            )
            return VERIFICATION
        
        # If not verified and can't verify yet
        if not user_data[6]:
            remaining_time = get_remaining_wait_time(user.id)
            minutes = remaining_time // 60
            seconds = remaining_time % 60
            
            context.bot.send_message(
                chat_id=user.id,
                text=f"⏳ *Please wait {minutes:02d}:{seconds:02d}*\n\n"
                     "You need to wait 3 minutes after registration before you can verify.\n\n"
                     "Please come back in a few minutes!",
                parse_mode="Markdown"
            )
            return -1
        
        # If verified but hasn't joined channel
        if user_data[6] and not user_data[10]:
            context.bot.send_message(
                chat_id=user.id,
                text="📢 *CHANNEL JOIN REQUIRED* 📢\n\n"
                     "To access all features, you MUST join our official channel:\n"
                     f"👉 {REQUIRED_CHANNEL}\n\n"
                     "Please join and click the button below:",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("✅ I've Joined the Channel", callback_data="join_channel")
                ]])
            )
            return CHANNEL_JOIN
        
        # Show main menu if fully verified
        show_main_menu(update, context)
        return -1
    except Exception as e:
        logger.error(f"Error in start command: {e}")
        context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="⚠️ An error occurred. Please try again later."
        )
        return -1

# Verification process
def verify_callback(update: Update, context: CallbackContext) -> int:
    try:
        query = update.callback_query
        query.answer()
        user_id = query.from_user.id
        
        # Set user as verified
        if set_verified(user_id):
            query.edit_message_text(
                text="✅ *Verification Complete!*\n\n"
                     "You're almost ready to start earning!\n\n"
                     "📢 *JOIN OUR CHANNEL REQUIRED* 📢\n"
                     f"Please join: {REQUIRED_CHANNEL}\n"
                     "to access all features and withdraw funds.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("✅ I've Joined the Channel", callback_data="join_channel")
                ]])
            )
            return CHANNEL_JOIN
        else:
            query.edit_message_text(
                text="⚠️ Verification failed. Please try again later."
            )
            return -1
    except Exception as e:
        logger.error(f"Error in verify_callback: {e}")
        return -1

# Channel join verification
def join_channel_callback(update: Update, context: CallbackContext) -> int:
    try:
        query = update.callback_query
        query.answer()
        user_id = query.from_user.id
        
        # Set user as joined channel
        if set_channel_joined(user_id):
            query.edit_message_text(
                text="🎉 *Setup Complete!* 🎉\n\n"
                     "You're now ready to start earning with INVITOR CASH PH!\n\n"
                     f"⚡ Earn ₱{CAPTCHA_REWARD} for each captcha solved\n"
                     f"👥 Earn ₱{INVITE_REWARD} for each friend invited",
                parse_mode="Markdown"
            )
            show_main_menu(update, context)
            return -1
        else:
            query.edit_message_text(
                text="⚠️ Failed to verify channel join. Please try again."
            )
            return CHANNEL_JOIN
    except Exception as e:
        logger.error(f"Error in join_channel_callback: {e}")
        return -1

# Main menu display
def show_main_menu(update: Update, context: CallbackContext):
    try:
        user_id = update.effective_user.id
        user_data = get_user(user_id)
        if not user_data:
            context.bot.send_message(user_id, "⚠️ Your account couldn't be loaded. Please restart with /start")
            return
            
        balance = user_data[2]
        invite_count = user_data[5]
        
        menu_options = [
            ["🎮 Play Captcha Game", "👥 Invite & Earn"],
            ["💰 Withdraw", "💼 My Balance"]
        ]
        
        context.bot.send_message(
            chat_id=user_id,
            text=f"🏦 *Account Balance: ₱{balance:.2f}*\n"
                 f"👥 Total Invites: {invite_count}\n\n"
                 "Select an option:",
            parse_mode="Markdown",
            reply_markup=ReplyKeyboardMarkup(
                menu_options, 
                resize_keyboard=True,
                one_time_keyboard=False
            )
        )
    except Exception as e:
        logger.error(f"Error in show_main_menu: {e}")

# Captcha game handler
def start_captcha_game(update: Update, context: CallbackContext) -> int:
    try:
        user_id = update.effective_user.id
        user_data = get_user(user_id)
        
        # Check if user has joined channel
        if not user_data or not user_data[10]:
            update.message.reply_text(
                "⚠️ You must join our channel first!\n"
                f"Please join: {REQUIRED_CHANNEL}\n"
                "and try again."
            )
            return -1
        
        # Generate captcha
        captcha_file, captcha_solution = generate_captcha()
        if not captcha_file or not captcha_solution:
            update.message.reply_text("⚠️ Failed to generate CAPTCHA. Please try again later.")
            return -1
        
        # Save captcha solution
        save_captcha(user_id, captcha_solution)
        
        # Send captcha image
        with open(captcha_file, 'rb') as photo:
            context.bot.send_photo(
                chat_id=user_id,
                photo=InputFile(photo),
                caption="🔍 *CAPTCHA GAME* 🔍\n\n"
                        "Enter the text shown in the image to earn ₱50.00!\n\n"
                        "Type your answer:",
                parse_mode="Markdown"
            )
        
        # Clean up captcha file
        os.remove(captcha_file)
        
        return CAPTCHA_GAME
    except Exception as e:
        logger.error(f"Error in start_captcha_game: {e}")
        return -1

# Captcha answer handler
def handle_captcha_answer(update: Update, context: CallbackContext) -> int:
    try:
        user_id = update.effective_user.id
        user_answer = update.message.text.upper().replace(" ", "")
        
        # Get last captcha solution
        c.execute("SELECT captcha_solution FROM captchas WHERE user_id=? ORDER BY timestamp DESC LIMIT 1", (user_id,))
        captcha_row = c.fetchone()
        
        if captcha_row and user_answer == captcha_row[0]:
            # Correct answer
            update_balance(user_id, CAPTCHA_REWARD)
            new_balance = get_user(user_id)[2]
            
            update.message.reply_text(
                f"🎉 *Congratulations!* 🎉\n\n"
                f"Your answer is correct!\n"
                f"➕ ₱{CAPTCHA_REWARD:.2f} has been credited to your account\n"
                f"💰 New Balance: ₱{new_balance:.2f}",
                parse_mode="Markdown"
            )
        else:
            # Incorrect answer
            update.message.reply_text(
                "❌ *Incorrect Answer!*\n\n"
                "Uh-oh! That wasn't the right solution, but don't give up!\n"
                f"Try again and you could still snag that ₱{CAPTCHA_REWARD:.2f} reward!\n\n"
                "You've got this, we're cheering for you!",
                parse_mode="Markdown"
            )
        
        show_main_menu(update, context)
        return -1
    except Exception as e:
        logger.error(f"Error in handle_captcha_answer: {e}")
        return -1

# Invite system
def invite_friends(update: Update, context: CallbackContext):
    try:
        user_id = update.effective_user.id
        user_data = get_user(user_id)
        if not user_data:
            update.message.reply_text("⚠️ Your account couldn't be loaded. Please restart with /start")
            return
            
        # Check if user has joined channel
        if not user_data[10]:
            update.message.reply_text(
                "⚠️ You must join our channel first!\n"
                f"Please join: {REQUIRED_CHANNEL}\n"
                "and try again."
            )
            return
            
        invite_code = user_data[3]
        invite_link = f"https://t.me/{context.bot.username}?start={invite_code}"
        
        update.message.reply_text(
            "👥 *INVITE & EARN* 👥\n\n"
            f"Invite friends and earn *₱{INVITE_REWARD:.2f}* for each successful referral!\n\n"
            f"Your unique invite link:\n`{invite_link}`\n\n"
            "You'll be notified when someone joins using your link!\n"
            f"Total invites: {user_data[5]}\n"
            f"Total earned: ₱{user_data[5] * INVITE_REWARD:.2f}",
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Error in invite_friends: {e}")

# Withdrawal process
def start_withdrawal(update: Update, context: CallbackContext) -> int:
    try:
        user_id = update.effective_user.id
        user_data = get_user(user_id)
        if not user_data:
            update.message.reply_text("⚠️ Your account couldn't be loaded. Please restart with /start")
            return -1
            
        # Check if user has joined channel
        if not user_data[10]:
            update.message.reply_text(
                "⚠️ You must join our channel first!\n"
                f"Please join: {REQUIRED_CHANNEL}\n"
                "and try again."
            )
            return -1
            
        balance = user_data[2]
        
        if balance < MIN_WITHDRAWAL:
            update.message.reply_text(
                f"❌ Minimum withdrawal is ₱{MIN_WITHDRAWAL:.2f}\n"
                f"Your current balance: ₱{balance:.2f}"
            )
            return -1
        
        update.message.reply_text(
            f"💰 *WITHDRAW FUNDS* 💰\n\n"
            f"Account Balance: ₱{balance:.2f}\n"
            f"Min: ₱{MIN_WITHDRAWAL:.2f} | Max: ₱{MAX_WITHDRAWAL:.2f}\n\n"
            "Enter amount to withdraw:",
            parse_mode="Markdown",
            reply_markup=ReplyKeyboardRemove()
        )
        return WITHDRAW_AMOUNT
    except Exception as e:
        logger.error(f"Error in start_withdrawal: {e}")
        return -1

def handle_withdrawal_amount(update: Update, context: CallbackContext) -> int:
    try:
        amount = float(update.message.text)
        user_id = update.effective_user.id
        user_data = get_user(user_id)
        if not user_data:
            update.message.reply_text("⚠️ Your account couldn't be loaded. Please restart with /start")
            return -1
            
        balance = user_data[2]
        
        if amount < MIN_WITHDRAWAL or amount > MAX_WITHDRAWAL:
            update.message.reply_text(
                f"❌ Amount must be between ₱{MIN_WITHDRAWAL:.2f} and ₱{MAX_WITHDRAWAL:.2f}"
            )
            return WITHDRAW_AMOUNT
        
        if amount > balance:
            update.message.reply_text(
                f"❌ Insufficient balance. Your current balance: ₱{balance:.2f}"
            )
            return WITHDRAW_AMOUNT
        
        context.user_data['withdrawal_amount'] = amount
        update.message.reply_text(
            "📝 *ENTER WALLET DETAILS* 📝\n\n"
            "Please provide your wallet information:\n"
            "• Name\n• Number\n• Wallet Type\n\n"
            "Example:\n"
            "Juan Dela Cruz\n"
            "09123456789\n"
            "GCash",
            parse_mode="Markdown"
        )
        return WITHDRAW_INFO
        
    except ValueError:
        update.message.reply_text("❌ Please enter a valid number")
        return WITHDRAW_AMOUNT
    except Exception as e:
        logger.error(f"Error in handle_withdrawal_amount: {e}")
        return -1

def handle_wallet_info(update: Update, context: CallbackContext) -> int:
    try:
        wallet_info = update.message.text
        amount = context.user_data['withdrawal_amount']
        user_id = update.effective_user.id
        user_data = get_user(user_id)
        if not user_data:
            update.message.reply_text("⚠️ Your account couldn't be loaded. Please restart with /start")
            return -1
            
        invite_count = user_data[5]
        invite_code = user_data[3]
        invite_link = f"https://t.me/{context.bot.username}?start={invite_code}"
        
        # Save withdrawal request
        if not save_withdrawal(user_id, amount, wallet_info):
            update.message.reply_text("⚠️ Failed to process withdrawal. Please try again later.")
            return -1
        
        # Check if user needs to invite others
        if invite_count < REQUIRED_INVITES:
            update.message.reply_text(
                "📬 *WITHDRAWAL PENDING* 📬\n\n"
                f"Your withdrawal request for ₱{amount:.2f} has been received!\n\n"
                "To complete your withdrawal, you need to invite "
                f"*{REQUIRED_INVITES - invite_count} more friends*:\n"
                f"1. Share your invite link: `{invite_link}`\n"
                f"2. You'll receive ₱{INVITE_REWARD:.2f} for each successful invite\n"
                "3. Withdrawal will be processed automatically when you reach 10 invites\n\n"
                "You can continue playing games while waiting!",
                parse_mode="Markdown"
            )
            set_withdrawal_pending(user_id, True)
        else:
            # Process withdrawal immediately
            update.message.reply_text(
                "✅ *WITHDRAWAL SUCCESSFUL!* ✅\n\n"
                f"Your withdrawal of ₱{amount:.2f} is being processed!\n"
                "Funds will arrive in your account within 20-30 minutes.",
                parse_mode="Markdown"
            )
        
        show_main_menu(update, context)
        return -1
    except Exception as e:
        logger.error(f"Error in handle_wallet_info: {e}")
        return -1

# Balance check
def check_balance(update: Update, context: CallbackContext):
    try:
        user_id = update.effective_user.id
        user_data = get_user(user_id)
        if not user_data:
            update.message.reply_text("⚠️ Your account couldn't be loaded. Please restart with /start")
            return
            
        # Check if user has joined channel
        if not user_data[10]:
            update.message.reply_text(
                "⚠️ You must join our channel first!\n"
                f"Please join: {REQUIRED_CHANNEL}\n"
                "and try again."
            )
            return
            
        balance = user_data[2]
        invite_count = user_data[5]
        total_earned = invite_count * INVITE_REWARD
        
        update.message.reply_text(
            f"💰 *Account Balance: ₱{balance:.2f}*\n"
            f"👥 Total Invites: {invite_count}\n"
            f"💸 Total Earned from Invites: ₱{total_earned:.2f}",
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Error in check_balance: {e}")

# Cancel handler
def cancel(update: Update, context: CallbackContext) -> int:
    try:
        update.message.reply_text(
            "Operation cancelled"
        )
        show_main_menu(update, context)
        return -1
    except Exception as e:
        logger.error(f"Error in cancel: {e}")
        return -1

# Handle other messages
def handle_other_messages(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    user_data = get_user(user_id)
    
    if not user_data:
        context.bot.send_message(
            user_id,
            "Please start with /start to begin"
        )
        return
    
    if not user_data[6]:  # Not verified
        remaining_time = get_remaining_wait_time(user_id)
        minutes = remaining_time // 60
        seconds = remaining_time % 60
        
        if can_verify(user_id):
            context.bot.send_message(
                user_id,
                "You can now complete verification!\n"
                "Please use /start to continue",
            )
        else:
            context.bot.send_message(
                user_id,
                f"⏳ Please wait {minutes:02d}:{seconds:02d} before you can verify\n"
                "Use /start after the waiting period",
            )
        return
    
    if user_data[6] and not user_data[10]:  # Verified but not joined channel
        context.bot.send_message(
            user_id,
            "⚠️ You must join our channel to continue!\n"
            f"Please join: {REQUIRED_CHANNEL}\n"
            "and use /start again",
        )
        return
    
    # Show main menu for other messages
    show_main_menu(update, context)

# Main bot function
def main() -> None:
    # Start Flask server in a separate thread
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()
    logger.info("Flask server started for keep-alive")
    
    # Start Telegram bot
    updater = Updater(TOKEN)
    dispatcher = updater.dispatcher

    # Add handlers
    dispatcher.add_handler(CommandHandler('start', start))
    dispatcher.add_handler(CallbackQueryHandler(verify_callback, pattern='^verify$'))
    dispatcher.add_handler(CallbackQueryHandler(join_channel_callback, pattern='^join_channel$'))
    dispatcher.add_handler(MessageHandler(Filters.regex('^🎮 Play Captcha Game$'), start_captcha_game))
    dispatcher.add_handler(MessageHandler(Filters.regex('^👥 Invite & Earn$'), invite_friends))
    dispatcher.add_handler(MessageHandler(Filters.regex('^💰 Withdraw$'), start_withdrawal))
    dispatcher.add_handler(MessageHandler(Filters.regex('^💼 My Balance$'), check_balance))
    
    # Conversation handlers
    captcha_conv = ConversationHandler(
        entry_points=[],
        states={
            CAPTCHA_GAME: [MessageHandler(Filters.text & ~Filters.command, handle_captcha_answer)],
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )

    withdrawal_conv = ConversationHandler(
        entry_points=[],
        states={
            WITHDRAW_AMOUNT: [MessageHandler(Filters.text & ~Filters.command, handle_withdrawal_amount)],
            WITHDRAW_INFO: [MessageHandler(Filters.text & ~Filters.command, handle_wallet_info)],
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )

    # Handle all other messages
    dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_other_messages))
    
    dispatcher.add_handler(captcha_conv)
    dispatcher.add_handler(withdrawal_conv)
    
    # Start the Bot
    updater.start_polling()
    logger.info("Telegram bot started successfully")
    updater.idle()

if __name__ == '__main__':
    main()
