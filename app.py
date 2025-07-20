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
from telegram import (Update, InlineKeyboardButton, InlineKeyboardMarkup,
                      ReplyKeyboardMarkup, ReplyKeyboardRemove, InputFile)
from telegram.ext import (Updater, CommandHandler, MessageHandler, Filters,
                          CallbackContext, ConversationHandler,
                          CallbackQueryHandler)
from apscheduler.schedulers.background import BackgroundScheduler
import pytz

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[logging.FileHandler("bot.log"),
              logging.StreamHandler()])
logger = logging.getLogger(__name__)

# Bot configuration
TOKEN = "8161112328:AAEgZCq_RPbqklrfSsE-p0YVbhiNH53snP4"

# Global variables
updater = None
REQUIRED_CHANNEL = "@INVITORCASHPH"
ARENA_LIVE_LINK = "https://arenalive.ph/s/rzRkoGR"
MAIN_GROUP_LINK = "https://t.me/+Z3fNuDvJO5BjNGZl"
FREE_2000_LINK = "https://www.17ph.com/o/s23/20656601"
CAPTCHA_REWARD = 50
INVITE_REWARD = 30
DAILY_SIGNIN_REWARD = 50
MIN_WITHDRAWAL = 5000
MAX_WITHDRAWAL = 20000
REQUIRED_INVITES = 10
PORT = int(os.environ.get('PORT', 5000))
VERIFICATION_WAIT_TIME = 180  # 3 minutes in seconds
QUIZ_QUESTIONS_PER_PERIOD = 10
QUIZ_COOLDOWN_HOURS = 6
BONUS_QUESTIONS_PER_INVITE = 5
BONUS_QUESTIONS_THRESHOLD = 5
BONUS_CASH_REWARD = 100
FREE_CLAIM_REWARD = 100
PESO_MINING_RATE = 0.001  # 0.001 PHP per 15 minutes per invite
PESO_MINING_INTERVAL = 900  # 15 minutes in seconds
MIN_MINING_CLAIM = 20  # Minimum 20 PHP to claim

# Create Flask app for keep-alive
app = Flask(__name__)

@app.route('/')
def home():
    return "INVITOR CASH PH BOT is running!", 200

def run_flask():
    app.run(host='0.0.0.0', port=PORT)

# Conversation states
(VERIFICATION, CHANNEL_JOIN, CAPTCHA_GAME, WITHDRAW_AMOUNT, WITHDRAW_INFO, QUIZ_GAME) = range(6)

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
              channel_joined BOOLEAN DEFAULT 0,
              last_signin_date TEXT,
              quiz_questions_answered INTEGER DEFAULT 0,
              bonus_questions_available INTEGER DEFAULT 0,
              last_quiz_reset_time TEXT,
              free_claim_used BOOLEAN DEFAULT 0,
              mining_start_time TEXT,
              last_mining_claim_date TEXT)''')

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

c.execute('''CREATE TABLE IF NOT EXISTS quiz_questions
             (id INTEGER PRIMARY KEY AUTOINCREMENT,
              question TEXT,
              option1 TEXT,
              option2 TEXT,
              option3 TEXT,
              option4 TEXT,
              correct_option INTEGER)''')

c.execute('''CREATE TABLE IF NOT EXISTS daily_signins
             (user_id INTEGER,
              signin_date TEXT,
              PRIMARY KEY (user_id, signin_date))''')

c.execute('''CREATE TABLE IF NOT EXISTS user_quiz_progress
             (user_id INTEGER,
              question_id INTEGER,
              answered_correctly BOOLEAN,
              timestamp TEXT)''')

# Add new columns for existing users if they don't exist
try:
    c.execute("ALTER TABLE users ADD COLUMN last_quiz_reset_time TEXT")
    conn.commit()
except sqlite3.OperationalError:
    # Column already exists
    pass

try:
    c.execute("ALTER TABLE users ADD COLUMN free_claim_used BOOLEAN DEFAULT 0")
    conn.commit()
except sqlite3.OperationalError:
    # Column already exists
    pass

try:
    c.execute("ALTER TABLE users ADD COLUMN mining_start_time TEXT")
    conn.commit()
except sqlite3.OperationalError:
    # Column already exists
    pass

try:
    c.execute("ALTER TABLE users ADD COLUMN last_mining_claim_date TEXT")
    conn.commit()
except sqlite3.OperationalError:
    # Column already exists
    pass

# Create 40 quiz questions if none exist
c.execute("SELECT COUNT(*) FROM quiz_questions")
if c.fetchone()[0] == 0:
    sample_questions = [
        ("What is the capital of the Philippines?", "Manila", "Cebu", "Davao", "Quezon City", 1),
        ("Which color is not in the Philippine flag?", "Red", "Blue", "Yellow", "Green", 4),
        ("What is the national bird of the Philippines?", "Eagle", "Maya", "Parrot", "Crow", 1),
        ("How many islands are there in the Philippines?", "7,107", "5,000", "10,000", "3,500", 1),
        ("What is the national fruit of the Philippines?", "Mango", "Banana", "Pineapple", "Papaya", 1),
        ("Which sea surrounds the Philippines?", "South China Sea", "Caribbean Sea", "Mediterranean Sea", "Baltic Sea", 1),
        ("What is the currency of the Philippines?", "Peso", "Dollar", "Euro", "Yen", 1),
        ("Which festival is celebrated in Cebu?", "Sinulog", "Ati-Atihan", "Dinagyang", "Pahiyas", 1),
        ("What is the tallest mountain in the Philippines?", "Mt. Apo", "Mt. Pulag", "Mt. Mayon", "Mt. Pinatubo", 1),
        ("Which Philippine president served the longest?", "Ferdinand Marcos", "Gloria Arroyo", "Rodrigo Duterte", "Benigno Aquino", 1),
        ("What is the national flower of the Philippines?", "Sampaguita", "Rose", "Orchid", "Tulip", 1),
        ("Which Philippine hero is known as the 'Great Plebeian'?", "Andres Bonifacio", "Jose Rizal", "Apolinario Mabini", "Emilio Aguinaldo", 1),
        ("What is the traditional Filipino Christmas greeting?", "Maligayang Pasko", "Salamat", "Kumusta", "Paalam", 1),
        ("Which province is known as the 'Rice Granary of the Philippines'?", "Nueva Ecija", "Pampanga", "Bulacan", "Tarlac", 1),
        ("What is the traditional Filipino martial art?", "Arnis", "Karate", "Taekwondo", "Kung Fu", 1),
        ("Which Philippine city is known as the 'City of Smiles'?", "Bacolod", "Cebu", "Davao", "Manila", 1),
        ("What is the most popular Filipino dessert?", "Halo-halo", "Leche Flan", "Buko Pie", "Mais Con Yelo", 1),
        ("Which Philippine island is known for its chocolate hills?", "Bohol", "Palawan", "Boracay", "Siargao", 1),
        ("What is the national tree of the Philippines?", "Narra", "Acacia", "Mahogany", "Mango Tree", 1),
        ("Which Philippine volcano is known for its perfect cone shape?", "Mayon", "Taal", "Pinatubo", "Kanlaon", 1),
        ("What is the traditional Filipino boat?", "Bangka", "Yacht", "Speedboat", "Canoe", 1),
        ("Which Philippine fruit is known as the 'poor man's apple'?", "Chico", "Mango", "Banana", "Pineapple", 1),
        ("What is the national dance of the Philippines?", "Tinikling", "Cariñosa", "Pandanggo", "Singkil", 1),
        ("Which Philippine province is known as the 'Land of the Ugs'?", "Quezon", "Laguna", "Cavite", "Batangas", 1),
        ("What is the traditional Filipino shirt?", "Barong Tagalog", "Kimono", "Saya", "Terno", 1),
        ("Which Philippine city is known as the 'Summer Capital'?", "Baguio", "Tagaytay", "Baguio", "Davao", 1),
        ("What is the national animal of the Philippines?", "Carabao", "Tamaraw", "Philippine Eagle", "Monkey", 2),
        ("Which Philippine festival features street dancing with colorful costumes?", "Sinulog", "Pahiyas", "Panagbenga", "Kadayawan", 1),
        ("What is the traditional Filipino breakfast?", "Tapsilog", "Adobo", "Sinigang", "Kare-Kare", 1),
        ("Which Philippine province is known for its pottery?", "Ilocos Sur", "Pampanga", "Bohol", "Albay", 1),
        ("What is the national gem of the Philippines?", "Pearl", "Diamond", "Ruby", "Emerald", 1),
        ("Which Philippine island is known for its whale sharks?", "Donsol", "Palawan", "Siargao", "Cebu", 1),
        ("What is the traditional Filipino courtship dance?", "Cariñosa", "Tinikling", "Pandanggo", "Kuratsa", 1),
        ("Which Philippine city is known as the 'Walled City'?", "Intramuros", "Vigan", "Cebu", "Davao", 1),
        ("What is the national leaf of the Philippines?", "Anahaw", "Bamboo", "Coconut", "Banana", 1),
        ("Which Philippine province is known for its surfing spots?", "Siargao", "La Union", "Baler", "Zambales", 1),
        ("What is the traditional Filipino noodle dish?", "Pancit", "Spaghetti", "Lasagna", "Carbonara", 1),
        ("Which Philippine hero wrote 'Noli Me Tangere'?", "Jose Rizal", "Andres Bonifacio", "Apolinario Mabini", "Emilio Aguinaldo", 1),
        ("What is the national costume for Filipino women?", "Baro't Saya", "Kimono", "Sari", "Ao Dai", 1),
        ("Which Philippine province is known for its rice terraces?", "Ifugao", "Benguet", "Mountain Province", "Kalinga", 1)
    ]
    
    c.executemany(
        "INSERT INTO quiz_questions (question, option1, option2, option3, option4, correct_option) VALUES (?, ?, ?, ?, ?, ?)",
        sample_questions
    )
    conn.commit()

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
            c.execute(
                "INSERT INTO users (user_id, username, invite_code, invited_by, registration_time) VALUES (?, ?, ?, ?, ?)",
                (user_id, username, invite_code, invited_by, registration_time)
            )
            logger.info(f"New user {user_id} created with referrer {invited_by}")
        else:
            c.execute(
                "INSERT INTO users (user_id, username, invite_code, registration_time) VALUES (?, ?, ?, ?)",
                (user_id, username, invite_code, registration_time)
            )
        conn.commit()
        return invite_code
    except Exception as e:
        logger.error(f"Database error in create_user: {e}")
        return None

def update_balance(user_id, amount):
    try:
        # Get current balance first
        c.execute("SELECT balance FROM users WHERE user_id=?", (user_id,))
        result = c.fetchone()
        current_balance = result[0] if result else 0
        
        c.execute("UPDATE users SET balance = ? WHERE user_id=?", 
                 (current_balance + amount, user_id))
        conn.commit()
        logger.info(f"Updated balance for {user_id}: +₱{amount} (New balance: {current_balance + amount})")
        return True
    except Exception as e:
        logger.error(f"Database error in update_balance for user {user_id}: {e}")
        return False

def increment_invite_count(user_id):
    try:
        # Get current count first
        c.execute("SELECT invite_count, mining_start_time FROM users WHERE user_id=?", (user_id,))
        result = c.fetchone()
        current_count = result[0] if result else 0
        mining_start_time = result[1] if result and len(result) > 1 else None
        
        # If this is the first invite and mining hasn't started, initialize mining
        if current_count == 0 and not mining_start_time:
            mining_start_time = datetime.now().isoformat()
            c.execute("UPDATE users SET invite_count = ?, mining_start_time = ? WHERE user_id=?", 
                     (current_count + 1, mining_start_time, user_id))
        else:
            c.execute("UPDATE users SET invite_count = ? WHERE user_id=?", 
                     (current_count + 1, user_id))
            
        conn.commit()
        logger.info(f"Incremented invite count for {user_id} (New count: {current_count + 1})")
        return True
    except Exception as e:
        logger.error(f"Database error in increment_invite_count for user {user_id}: {e}")
        return False

def set_verified(user_id):
    try:
        verification_time = datetime.now().isoformat()
        c.execute(
            "UPDATE users SET verified=1, verification_time=? WHERE user_id=?",
            (verification_time, user_id)
        )
        
        # Reward referrer after successful verification
        c.execute("SELECT invited_by FROM users WHERE user_id=?", (user_id,))
        referrer = c.fetchone()
        if referrer and referrer[0]:
            update_balance(referrer[0], INVITE_REWARD)
            increment_invite_count(referrer[0])
            logger.info(f"Rewarded referrer {referrer[0]} for verified user {user_id}")
        
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
        c.execute(
            "INSERT INTO withdrawals (user_id, amount, wallet_info, timestamp) VALUES (?, ?, ?, ?)",
            (user_id, amount, wallet_info, timestamp)
        )
        conn.commit()
        return update_balance(user_id, -amount)
    except Exception as e:
        logger.error(f"Database error in save_withdrawal: {e}")
        return False

def save_captcha(user_id, solution):
    try:
        timestamp = datetime.now().isoformat()
        c.execute(
            "INSERT INTO captchas (user_id, captcha_solution, timestamp) VALUES (?, ?, ?)",
            (user_id, solution, timestamp)
        )
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

def can_sign_in_today(user_id):
    """Check if user can sign in today"""
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        c.execute(
            "SELECT 1 FROM daily_signins WHERE user_id=? AND signin_date=?",
            (user_id, today)
        )
        return c.fetchone() is None
    except Exception as e:
        logger.error(f"Error in can_sign_in_today: {e}")
        return False

def can_claim_free_100(user_id):
    """Check if user can claim free 100 PHP"""
    try:
        user_data = get_user(user_id)
        if not user_data:
            return False
        # Check if free_claim_used exists and is False
        free_claim_used = user_data[15] if len(user_data) > 15 else 0
        return not free_claim_used
    except Exception as e:
        logger.error(f"Error in can_claim_free_100: {e}")
        return False

def claim_free_100(user_id):
    """Claim free 100 PHP reward"""
    try:
        c.execute("UPDATE users SET free_claim_used = 1 WHERE user_id = ?", (user_id,))
        conn.commit()
        return update_balance(user_id, FREE_CLAIM_REWARD)
    except Exception as e:
        logger.error(f"Error in claim_free_100: {e}")
        return False

def record_daily_signin(user_id):
    """Record today's sign-in and reward user"""
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        c.execute(
            "INSERT INTO daily_signins (user_id, signin_date) VALUES (?, ?)",
            (user_id, today)
        )
        conn.commit()
        return update_balance(user_id, DAILY_SIGNIN_REWARD)
    except Exception as e:
        logger.error(f"Error in record_daily_signin: {e}")
        return False

def get_available_quiz_questions(user_id):
    """Get available quiz questions for user based on 6-hour cooldown"""
    try:
        user_data = get_user(user_id)
        if not user_data:
            return 0
        
        # Check if we need to reset the quiz count
        reset_quiz_count_if_needed(user_id)
        
        # Get updated user data after potential reset
        user_data = get_user(user_id)
        if not user_data:
            return 0
            
        # Available questions = base allowance - answered + bonus questions
        available = (
            QUIZ_QUESTIONS_PER_PERIOD - user_data[12]  # quiz_questions_answered
        ) + user_data[13]  # bonus_questions_available
        
        return max(0, available)
    except Exception as e:
        logger.error(f"Error in get_available_quiz_questions: {e}")
        return 0

def reset_quiz_count_if_needed(user_id):
    """Reset quiz count if 6 hours have passed"""
    try:
        user_data = get_user(user_id)
        if not user_data:
            return False
            
        last_reset_time = user_data[14] if len(user_data) > 14 else None  # last_quiz_reset_time
        current_time = datetime.now()
        
        # If no reset time recorded, set it to now and reset count
        if not last_reset_time:
            c.execute(
                "UPDATE users SET quiz_questions_answered = 0, last_quiz_reset_time = ? WHERE user_id = ?",
                (current_time.isoformat(), user_id)
            )
            conn.commit()
            logger.info(f"Initialized quiz reset time for user {user_id}")
            return True
            
        # Check if 6 hours have passed
        try:
            last_reset = datetime.fromisoformat(last_reset_time)
            time_diff = current_time - last_reset
            
            if time_diff.total_seconds() >= (QUIZ_COOLDOWN_HOURS * 3600):
                # Reset the quiz count
                c.execute(
                    "UPDATE users SET quiz_questions_answered = 0, last_quiz_reset_time = ? WHERE user_id = ?",
                    (current_time.isoformat(), user_id)
                )
                conn.commit()
                logger.info(f"Reset quiz count for user {user_id} after {QUIZ_COOLDOWN_HOURS} hours")
                return True
        except ValueError:
            # Invalid datetime format, reset it
            c.execute(
                "UPDATE users SET quiz_questions_answered = 0, last_quiz_reset_time = ? WHERE user_id = ?",
                (current_time.isoformat(), user_id)
            )
            conn.commit()
            logger.info(f"Fixed invalid quiz reset time for user {user_id}")
            return True
            
        return False
    except Exception as e:
        logger.error(f"Error in reset_quiz_count_if_needed: {e}")
        return False

def get_quiz_reset_time_remaining(user_id):
    """Get remaining time until quiz questions reset"""
    try:
        user_data = get_user(user_id)
        if not user_data or len(user_data) <= 14:
            return 0
            
        last_reset_time = user_data[14]  # last_quiz_reset_time
        if not last_reset_time:
            return 0
            
        last_reset = datetime.fromisoformat(last_reset_time)
        current_time = datetime.now()
        elapsed = current_time - last_reset
        remaining = (QUIZ_COOLDOWN_HOURS * 3600) - elapsed.total_seconds()
        
        return max(0, int(remaining))
    except Exception as e:
        logger.error(f"Error in get_quiz_reset_time_remaining: {e}")
        return 0

def get_random_quiz_question():
    """Get a random quiz question"""
    try:
        c.execute("SELECT * FROM quiz_questions ORDER BY RANDOM() LIMIT 1")
        return c.fetchone()
    except Exception as e:
        logger.error(f"Error in get_random_quiz_question: {e}")
        return None

def record_quiz_answer(user_id, question_id, is_correct):
    """Record quiz answer and update user progress"""
    try:
        timestamp = datetime.now().isoformat()
        c.execute(
            "INSERT INTO user_quiz_progress (user_id, question_id, answered_correctly, timestamp) VALUES (?, ?, ?, ?)",
            (user_id, question_id, int(is_correct), timestamp)
        )
        
        # Update answered questions count
        if is_correct:
            c.execute(
                "UPDATE users SET quiz_questions_answered = quiz_questions_answered + 1 WHERE user_id=?",
                (user_id,)
            )
        else:
            # Only count when bonus questions are used
            c.execute(
                "UPDATE users SET bonus_questions_available = bonus_questions_available - 1 WHERE user_id=? AND bonus_questions_available > 0",
                (user_id,)
            )
        
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Error in record_quiz_answer: {e}")
        return False

def check_invites_for_bonus(user_id):
    """Check if user qualifies for bonus questions and cash reward"""
    try:
        user_data = get_user(user_id)
        if not user_data:
            return False
            
        invites = user_data[5]  # invite_count
        if invites >= BONUS_QUESTIONS_THRESHOLD:
            # Calculate how many bonus questions to grant
            bonus_sets = invites // BONUS_QUESTIONS_THRESHOLD
            bonus_questions = bonus_sets * BONUS_QUESTIONS_PER_INVITE
            
            # Only update if there's a change
            current_bonus = user_data[13]  # bonus_questions_available
            if bonus_questions != current_bonus:
                c.execute(
                    "UPDATE users SET bonus_questions_available = ? WHERE user_id=?",
                    (bonus_questions, user_id)
                )
                
                # Award cash bonus for reaching milestone (every 5 invites = 100 PHP)
                if bonus_questions > current_bonus:
                    cash_bonus = (bonus_sets * BONUS_CASH_REWARD)
                    update_balance(user_id, cash_bonus)
                    logger.info(f"Awarded ₱{cash_bonus} bonus to user {user_id} for reaching {invites} invites")
                
                conn.commit()
                logger.info(f"Updated bonus questions for user {user_id}: {bonus_questions}")
            return True
            
        return False
    except Exception as e:
        logger.error(f"Error in check_invites_for_bonus: {e}")
        return False

def calculate_mining_earnings(user_id):
    """Calculate total peso mining earnings based on invites and 15-minute intervals"""
    try:
        user_data = get_user(user_id)
        if not user_data:
            return 0, 0
            
        invites = user_data[5]  # invite_count
        if invites == 0:
            return 0, 0
            
        # Get mining start time - if none exists but user has invites, start from now
        mining_start_time = user_data[16] if len(user_data) > 16 else None  # mining_start_time
        
        if not mining_start_time:
            # Initialize mining for existing users with invites
            mining_start_time = datetime.now().isoformat()
            c.execute("UPDATE users SET mining_start_time = ? WHERE user_id=?", 
                     (mining_start_time, user_id))
            conn.commit()
        
        # Calculate time elapsed since mining started
        try:
            start_time = datetime.fromisoformat(mining_start_time)
        except ValueError:
            # Invalid format, reset to now
            start_time = datetime.now()
            c.execute("UPDATE users SET mining_start_time = ? WHERE user_id=?", 
                     (start_time.isoformat(), user_id))
            conn.commit()
            
        current_time = datetime.now()
        elapsed_seconds = (current_time - start_time).total_seconds()
        
        # Calculate total earnings based on 15-minute intervals
        intervals_passed = elapsed_seconds // PESO_MINING_INTERVAL
        total_earnings = invites * PESO_MINING_RATE * intervals_passed
        
        # Calculate today's earnings (from start of today)
        today_start = current_time.replace(hour=0, minute=0, second=0, microsecond=0)
        if start_time >= today_start:
            # Mining started today
            today_seconds = (current_time - start_time).total_seconds()
        else:
            # Mining started before today
            today_seconds = (current_time - today_start).total_seconds()
            
        today_intervals = today_seconds // PESO_MINING_INTERVAL
        today_earnings = invites * PESO_MINING_RATE * today_intervals
        
        return total_earnings, today_earnings
        
    except Exception as e:
        logger.error(f"Error in calculate_mining_earnings: {e}")
        return 0, 0

def can_claim_mining_today(user_id):
    """Check if user can claim mining earnings today"""
    try:
        user_data = get_user(user_id)
        if not user_data:
            return False
            
        last_claim_date = user_data[17] if len(user_data) > 17 else None  # last_mining_claim_date
        today = datetime.now().strftime("%Y-%m-%d")
        
        return last_claim_date != today
    except Exception as e:
        logger.error(f"Error in can_claim_mining_today: {e}")
        return False

def claim_mining_earnings(user_id):
    """Claim mining earnings and reset mining start time"""
    try:
        total_earnings, today_earnings = calculate_mining_earnings(user_id)
        
        if total_earnings < MIN_MINING_CLAIM:
            return False, f"Minimum claim amount is ₱{MIN_MINING_CLAIM:.2f}"
            
        # Add earnings to balance
        if update_balance(user_id, total_earnings):
            # Reset mining start time and record claim date
            today = datetime.now().strftime("%Y-%m-%d")
            new_start_time = datetime.now().isoformat()
            c.execute(
                "UPDATE users SET mining_start_time = ?, last_mining_claim_date = ? WHERE user_id=?",
                (new_start_time, today, user_id)
            )
            conn.commit()
            logger.info(f"User {user_id} claimed ₱{total_earnings:.2f} mining earnings")
            return True, f"₱{total_earnings:.2f}"
        
        return False, "Failed to process claim"
        
    except Exception as e:
        logger.error(f"Error in claim_mining_earnings: {e}")
        return False, "An error occurred"

def reset_all_mining_data():
    """Reset all peso mining data for the new update (preserving invites)"""
    try:
        # Reset all mining start times and claim dates, but keep invite counts
        c.execute(
            "UPDATE users SET mining_start_time = NULL, last_mining_claim_date = NULL WHERE invite_count > 0"
        )
        conn.commit()
        logger.info("Reset all peso mining data for new update")
        return True
    except Exception as e:
        logger.error(f"Error in reset_all_mining_data: {e}")
        return False

# Generate CAPTCHA image
def generate_captcha():
    try:
        # Generate random 5-character string
        captcha_text = ''.join(random.choices(string.ascii_uppercase + string.digits, k=5))
        
        # Create image captcha with font size as single value for compatibility
        image = ImageCaptcha(width=280, height=90, font_sizes=[48])
        
        # Save to temporary file
        filename = f"captcha_{captcha_text}_{int(time.time())}.png"
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
        user_id = user.id
        user_data = get_user(user_id)
        
        # Check if user exists
        if not user_data:
            # Check if coming from referral
            invited_by = None
            if context.args and context.args[0].startswith('ref'):
                try:
                    # Extract invite code from URL
                    invite_code = context.args[0]
                    
                    # Find user with this invite code
                    c.execute("SELECT user_id FROM users WHERE invite_code=?", (invite_code,))
                    referrer = c.fetchone()
                    
                    if referrer:
                        invited_by = referrer[0]
                        logger.info(f"New user {user_id} came from referral by {invited_by}")
                    else:
                        logger.warning(f"Invalid invite code: {invite_code}")
                except Exception as e:
                    logger.error(f"Error processing referral: {e}")
            
            # Create user with referral info
            invite_code = create_user(user_id, username, invited_by)
            logger.info(f"Created new user {user_id} with invite code {invite_code}")
            
            # Show registration message for new users
            context.bot.send_message(
                chat_id=user_id,
                text=f"🌟 *Welcome to INVITOR CASH PH!* 🌟\n\n"
                     "💰 *REGISTRATION REQUIRED* 💰\n\n"
                     "To start earning money with our bot, you need to register first at our official partner site:\n\n"
                     f"🔗 **[Click here to Register at Arena Live]({ARENA_LIVE_LINK})**\n\n"
                     "📋 **Why do you need to register?**\n"
                     "• Arena Live is our trusted gaming partner\n"
                     "• Registration helps us verify legitimate users\n"
                     "• It ensures secure transactions and withdrawals\n"
                     "• Partners like Arena Live help us provide better rewards\n"
                     "• Your account will be linked for exclusive bonuses\n\n"
                     "⏳ **After registration, you need to wait 3 minutes before verification**\n\n"
                     "📝 **Steps to follow:**\n"
                     "1. Click the link above and complete registration\n"
                     "2. Join our official group (required)\n"
                     "3. Wait for 3 minutes (this is for security)\n"
                     "4. Come back and use /start again to verify\n"
                     "5. Start earning money immediately!\n\n"
                     f"💵 Earn ₱{CAPTCHA_REWARD} per captcha solved\n"
                     f"👥 Earn ₱{INVITE_REWARD} per friend invited\n"
                     f"📅 Earn ₱{DAILY_SIGNIN_REWARD} daily sign-in bonus\n\n"
                     "The 3-minute countdown starts now! ⏰",
                parse_mode="Markdown",
                disable_web_page_preview=False,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("📝 Register Here", url=ARENA_LIVE_LINK)],
                    [InlineKeyboardButton("👥 Join Here", url=MAIN_GROUP_LINK)]
                ])
            )
            return -1
        
        # Get updated user data
        user_data = get_user(user_id)
        
        # Check if user can verify
        if not user_data[6] and can_verify(user_id):
            # Show verification button
            context.bot.send_message(
                chat_id=user_id,
                text=f"🌟 *Welcome back to INVITOR CASH PH!* 🌟\n\n"
                     "⏰ Your 3-minute waiting period is complete!\n\n"
                     "You can now complete verification:\n"
                     f"1. Make sure you've registered at: [Arena Live]({ARENA_LIVE_LINK})\n"
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
            remaining_time = get_remaining_wait_time(user_id)
            minutes = remaining_time // 60
            seconds = remaining_time % 60
            
            context.bot.send_message(
                chat_id=user_id,
                text=f"⏳ *Please wait {minutes:02d}:{seconds:02d}*\n\n"
                     "You need to wait 3 minutes after registration before you can verify.\n\n"
                     "💡 **Don't forget to:**\n"
                     f"1. Register at [Arena Live]({ARENA_LIVE_LINK})\n"
                     "2. Join our official group using the button below\n\n"
                     "Please come back when the timer reaches 00:00!",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("👥 Join Here", url=MAIN_GROUP_LINK)],
                    [InlineKeyboardButton("✅ I've Joined the Group", callback_data="group_joined")]
                ])
            )
            return -1
        
        # If verified but hasn't joined channel
        if user_data[6] and not user_data[10]:
            context.bot.send_message(
                chat_id=user_id,
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

# Group join confirmation callback
def group_join_callback(update: Update, context: CallbackContext) -> int:
    try:
        query = update.callback_query
        query.answer()
        user_id = query.from_user.id
        
        query.edit_message_text(
            text="✅ *Thank you for joining our group!* ✅\n\n"
                 "🎉 You're now part of our community!\n\n"
                 "Please continue with the registration process:\n"
                 f"🔗 Make sure you've registered at [Arena Live]({ARENA_LIVE_LINK})\n\n"
                 "⏰ Wait for the 3-minute countdown to complete, then use /start again to verify your account.",
            parse_mode="Markdown"
        )
        return -1
    except Exception as e:
        logger.error(f"Error in group_join_callback: {e}")
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
                     f"👥 Earn ₱{INVITE_REWARD} for each friend invited\n"
                     f"📅 Earn ₱{DAILY_SIGNIN_REWARD} daily sign-in bonus",
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

# Daily sign-in handler
def daily_signin(update: Update, context: CallbackContext):
    try:
        user_id = update.effective_user.id
        user_data = get_user(user_id)
        
        if not user_data:
            if update.message:
                update.message.reply_text("⚠️ Please restart with /start to register your account.")
            return
            
        # Check if user has joined channel
        if not user_data[10]:
            update.message.reply_text("⚠️ You must join our group first!\n"
                                      f"Please join: {REQUIRED_CHANNEL}\n"
                                      "and try again.")
            return
            
        if can_sign_in_today(user_id):
            if record_daily_signin(user_id):
                new_balance = get_user(user_id)[2]
                update.message.reply_text(
                    f"🎉 *Daily Sign-in Successful!* 🎉\n\n"
                    f"➕ ₱{DAILY_SIGNIN_REWARD:.2f} has been credited to your account\n"
                    f"💰 New Balance: ₱{new_balance:.2f}\n\n"
                    "Come back tomorrow for another bonus!",
                    parse_mode="Markdown"
                )
            else:
                update.message.reply_text(
                    "⚠️ Failed to process sign-in. Please try again later."
                )
        else:
            update.message.reply_text(
                "⏳ *You've already signed in today!*\n\n"
                "Please come back tomorrow to claim your next daily bonus.",
                parse_mode="Markdown"
            )
    except Exception as e:
        logger.error(f"Error in daily_signin: {e}")

# Quiz game handler
def start_quiz_game(update: Update, context: CallbackContext) -> int:
    try:
        user_id = update.effective_user.id
        user_data = get_user(user_id)
        
        if not user_data:
            if update.message:
                update.message.reply_text("⚠️ Please restart with /start to register your account.")
            return -1
            
        # Check if user has joined channel
        if not user_data[10]:
            if update.message:
                update.message.reply_text("⚠️ You must join our group first!\n"
                                          f"Please join: {REQUIRED_CHANNEL}\n"
                                          "and try again.")
            return -1
            
        # Check available questions
        available = get_available_quiz_questions(user_id)
        if available <= 0:
            remaining_time = get_quiz_reset_time_remaining(user_id)
            hours = remaining_time // 3600
            minutes = (remaining_time % 3600) // 60
            
            if update.message:
                if remaining_time > 0:
                    update.message.reply_text(
                        "❌ *No Quiz Questions Available!*\n\n"
                        f"You've answered all {QUIZ_QUESTIONS_PER_PERIOD} questions for this period.\n\n"
                        f"⏰ *Next {QUIZ_QUESTIONS_PER_PERIOD} questions available in: {hours:02d}h {minutes:02d}m*\n\n"
                        f"💡 *Want more questions? Invite 5 friends to get {BONUS_QUESTIONS_PER_INVITE} bonus questions + ₱{BONUS_CASH_REWARD}!*\n"
                        f"For every 5 invites, you get {BONUS_QUESTIONS_PER_INVITE} bonus questions + ₱{BONUS_CASH_REWARD}!",
                        parse_mode="Markdown"
                    )
                else:
                    update.message.reply_text(
                        "❌ *No Quiz Questions Available!*\n\n"
                        f"You've answered all {QUIZ_QUESTIONS_PER_PERIOD} questions for this period.\n\n"
                        f"💡 *Invite 5 friends to get {BONUS_QUESTIONS_PER_INVITE} bonus questions + ₱{BONUS_CASH_REWARD}!*\n"
                        f"For every 5 invites, you get {BONUS_QUESTIONS_PER_INVITE} bonus questions + ₱{BONUS_CASH_REWARD}!",
                        parse_mode="Markdown"
                    )
            return -1
            
        # Get a random question
        question_data = get_random_quiz_question()
        if not question_data:
            if update.message:
                update.message.reply_text("⚠️ Failed to load quiz questions. Please try again later.")
            return -1
            
        # Store question in context
        context.user_data['current_question'] = question_data
        question_id, question, opt1, opt2, opt3, opt4, correct = question_data
        
        # Create options keyboard
        keyboard = [
            [InlineKeyboardButton(opt1, callback_data=f"quiz_{question_id}_1")],
            [InlineKeyboardButton(opt2, callback_data=f"quiz_{question_id}_2")],
            [InlineKeyboardButton(opt3, callback_data=f"quiz_{question_id}_3")],
            [InlineKeyboardButton(opt4, callback_data=f"quiz_{question_id}_4")],
            [InlineKeyboardButton("➡️ Next Question", callback_data="next_question")]
        ]
        
        # Send question
        if update.message:
            update.message.reply_text(
                f"❓ *QUIZ QUESTION* ❓\n\n"
                f"{question}\n\n"
                "Select your answer:",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        
        return QUIZ_GAME
    except Exception as e:
        logger.error(f"Error in start_quiz_game: {e}")
        return -1

# Quiz answer handler
def handle_quiz_answer(update: Update, context: CallbackContext) -> int:
    try:
        query = update.callback_query
        query.answer()
        user_id = query.from_user.id
        data = query.data
        
        # Parse callback data
        parts = data.split('_')
        question_id = int(parts[1])
        selected_option = int(parts[2])
        
        # Get question data
        question_data = context.user_data.get('current_question')
        if not question_data:
            query.edit_message_text("⚠️ Question data missing. Please start a new quiz.")
            return -1
            
        # Check answer
        correct_option = question_data[6]
        is_correct = selected_option == correct_option
        
        # Record answer
        record_quiz_answer(user_id, question_id, is_correct)
        
        # Reward if correct
        if is_correct:
            update_balance(user_id, CAPTCHA_REWARD)
            new_balance = get_user(user_id)[2]
            
            query.edit_message_text(
                f"✅ *Correct Answer!* ✅\n\n"
                f"➕ ₱{CAPTCHA_REWARD:.2f} has been credited to your account\n"
                f"💰 New Balance: ₱{new_balance:.2f}",
                parse_mode="Markdown"
            )
        else:
            correct_text = question_data[correct_option]
            query.edit_message_text(
                f"❌ *Incorrect Answer!* ❌\n\n"
                f"The correct answer was: {correct_text}",
                parse_mode="Markdown"
            )
        
        # Check for bonus questions after invites
        check_invites_for_bonus(user_id)
        
        return -1
    except Exception as e:
        logger.error(f"Error in handle_quiz_answer: {e}")
        return -1

# Next question callback
def next_question_callback(update: Update, context: CallbackContext) -> int:
    try:
        query = update.callback_query
        query.answer()
        return start_quiz_game(update, context)
    except Exception as e:
        logger.error(f"Error in next_question_callback: {e}")
        return -1

# Main menu display
def show_main_menu(update: Update, context: CallbackContext):
    try:
        user_id = update.effective_user.id
        user_data = get_user(user_id)
        if not user_data:
            context.bot.send_message(
                user_id,
                "⚠️ Your account couldn't be loaded. Please restart with /start"
            )
            return

        balance = user_data[2]
        invite_count = user_data[5]
        available_questions = get_available_quiz_questions(user_id)
        
        today = datetime.now().strftime("%Y-%m-%d")
        can_sign_in = can_sign_in_today(user_id)
        
        # Get quiz reset time info
        remaining_time = get_quiz_reset_time_remaining(user_id)
        hours = remaining_time // 3600
        minutes = (remaining_time % 3600) // 60

        menu_options = [
            ["🎮 Play Captcha Game", "❓ Play Quiz Game"],
            ["👥 Invite & Earn", "📅 Daily Sign-in"],
            ["💰 Withdraw", "💼 My Balance"],
            ["⛏️ Peso Mining"],
            ["👥 Join Channel", "🆓 FREE 2000PHP", "🎰 ArenaLive Register"]
        ]
        
        # Add free claim button if user can claim
        if can_claim_free_100(user_id):
            menu_options.insert(2, ["🎁 Claim FREE ₱100"])
        
        # Add sign-in status to message
        signin_status = "✅ (Claimed)" if not can_sign_in else "❌ (Not Claimed)"
        
        # Quiz status message
        quiz_status = f"❓ Quiz Questions Available: {available_questions}"
        if available_questions == 0 and remaining_time > 0:
            quiz_status += f" (Reset in {hours:02d}h {minutes:02d}m)"
        
        context.bot.send_message(
            chat_id=user_id,
            text=f"🏦 *Account Balance: ₱{balance:.2f}*\n"
                 f"👥 Total Invites: {invite_count}\n"
                 f"{quiz_status}\n"
                 f"📅 Daily Sign-in: {signin_status}\n\n"
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

# Claim free 100 PHP handler
def claim_free_100_handler(update: Update, context: CallbackContext):
    try:
        user_id = update.effective_user.id
        user_data = get_user(user_id)
        
        if not user_data:
            update.message.reply_text("⚠️ Please restart with /start to register your account.")
            return
            
        # Check if user has joined channel
        if not user_data[10]:
            update.message.reply_text("⚠️ You must join our group first!\n"
                                      f"Please join: {REQUIRED_CHANNEL}\n"
                                      "and try again.")
            return
        
        if can_claim_free_100(user_id):
            if claim_free_100(user_id):
                new_balance = get_user(user_id)[2]
                update.message.reply_text(
                    f"🎉 *FREE ₱100 CLAIMED!* 🎉\n\n"
                    f"➕ ₱{FREE_CLAIM_REWARD} has been credited to your account\n"
                    f"💰 New Balance: ₱{new_balance:.2f}\n\n"
                    "This was a one-time bonus. Keep earning with our games!",
                    parse_mode="Markdown"
                )
                # Show updated menu without the free claim button
                show_main_menu(update, context)
            else:
                update.message.reply_text(
                    "⚠️ Failed to process your claim. Please try again later."
                )
        else:
            update.message.reply_text(
                "❌ *Already Claimed!*\n\n"
                "You have already claimed your free ₱100 bonus.\n"
                "This was a one-time reward.",
                parse_mode="Markdown"
            )
    except Exception as e:
        logger.error(f"Error in claim_free_100_handler: {e}")

def peso_mining_handler(update: Update, context: CallbackContext):
    try:
        user_id = update.effective_user.id
        user_data = get_user(user_id)
        
        if not user_data:
            update.message.reply_text("⚠️ Please restart with /start to register your account.")
            return
            
        # Check if user has joined channel
        if not user_data[10]:
            update.message.reply_text("⚠️ You must join our group first!\n"
                                      f"Please join: {REQUIRED_CHANNEL}\n"
                                      "and try again.")
            return
        
        invites = user_data[5]  # invite_count
        invite_code = user_data[3]  # invite_code
        invite_link = f"https://t.me/{context.bot.username}?start={invite_code}"
        
        if invites == 0:
            # No invites yet
            update.message.reply_text(
                "⛏️ *PESO MINING* ⛏️\n\n"
                "💡 *How it works:*\n"
                f"• Earn ₱{PESO_MINING_RATE:.3f} every 15 minutes for each person you invite\n"
                f"• Minimum claim: ₱{MIN_MINING_CLAIM:.2f}\n"
                "• Claim once per day\n\n"
                "👥 *Current Status:*\n"
                f"• Total Invites: {invites}\n"
                "• Mining Rate: ₱0.000/15min\n"
                "• Today's Earnings: ₱0.00\n"
                "• Total Earnings: ₱0.00\n\n"
                "❌ *You need at least 1 invite to start mining!*\n\n"
                "Start inviting friends to activate peso mining!",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("👥 Invite Friends to Earn", url=f"https://t.me/share/url?url={invite_link}&text=Join%20Invitor%20Cash%20PH%20and%20start%20earning%20money!")]
                ])
            )
            return
        
        # Calculate earnings
        total_earnings, today_earnings = calculate_mining_earnings(user_id)
        mining_rate = invites * PESO_MINING_RATE
        can_claim_today = can_claim_mining_today(user_id)
        
        # Create buttons
        buttons = []
        if total_earnings >= MIN_MINING_CLAIM and can_claim_today:
            buttons.append([InlineKeyboardButton(f"💰 Claim ₱{total_earnings:.2f}", callback_data="claim_mining")])
        
        buttons.append([InlineKeyboardButton("👥 Invite More to Earn", url=f"https://t.me/share/url?url={invite_link}&text=Join%20Invitor%20Cash%20PH%20and%20start%20earning%20money!")])
        
        # Status message
        claim_status = ""
        if not can_claim_today:
            claim_status = "\n🕐 *You've already claimed today. Come back tomorrow!*"
        elif total_earnings < MIN_MINING_CLAIM:
            claim_status = f"\n⏳ *Minimum claim: ₱{MIN_MINING_CLAIM:.2f} (₱{MIN_MINING_CLAIM - total_earnings:.2f} more needed)*"
        
        update.message.reply_text(
            "⛏️ *PESO MINING* ⛏️\n\n"
            "💡 *How it works:*\n"
            f"• Earn ₱{PESO_MINING_RATE:.3f} every 15 minutes for each person you invite\n"
            f"• Minimum claim: ₱{MIN_MINING_CLAIM:.2f}\n"
            "• Claim once per day\n\n"
            "👥 *Your Mining Status:*\n"
            f"• Total Invites: {invites}\n"
            f"• Mining Rate: ₱{mining_rate:.3f}/15min\n"
            f"• Today's Earnings: ₱{today_earnings:.2f}\n"
            f"• Total Earnings: ₱{total_earnings:.2f}{claim_status}",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
        
    except Exception as e:
        logger.error(f"Error in peso_mining_handler: {e}")

def claim_mining_callback(update: Update, context: CallbackContext):
    try:
        query = update.callback_query
        query.answer()
        user_id = query.from_user.id
        
        if not can_claim_mining_today(user_id):
            query.edit_message_text(
                "❌ *Already Claimed Today!*\n\n"
                "You can only claim mining earnings once per day.\n"
                "Come back tomorrow to claim again!",
                parse_mode="Markdown"
            )
            return
        
        success, result = claim_mining_earnings(user_id)
        
        if success:
            new_balance = get_user(user_id)[2]
            query.edit_message_text(
                f"🎉 *MINING EARNINGS CLAIMED!* 🎉\n\n"
                f"➕ {result} has been added to your account\n"
                f"💰 New Balance: ₱{new_balance:.2f}\n\n"
                "✨ Your mining counter has been reset!\n"
                "Keep inviting friends to earn more!",
                parse_mode="Markdown"
            )
        else:
            query.edit_message_text(
                f"❌ *Claim Failed!*\n\n{result}",
                parse_mode="Markdown"
            )
            
    except Exception as e:
        logger.error(f"Error in claim_mining_callback: {e}")

# Show freeze cash rewards
def show_freeze_cash(update: Update, context: CallbackContext):
    try:
        user_id = update.effective_user.id
        user_data = get_user(user_id)
        
        if not user_data:
            update.message.reply_text("⚠️ Please restart with /start to register your account.")
            return
        
        invite_count = user_data[5]
        
        message = (
            "🧊 *FREEZE CASH REWARDS* 🧊\n\n"
            "Earn massive rewards by inviting friends!\n\n"
            "💰 Reward Tiers:\n"
            f"• Invite 5 friends = ₱500\n"
            f"• Invite 8 friends = ₱700\n"
            f"• Invite 10 friends = ₱1000\n"
            f"• Invite 20 friends = ₱2000\n"
            f"• Invite 50 friends = ₱5000\n"
            f"• Invite 100 friends = ₱10000\n"
            f"• Invite 200 friends = ₱20000\n\n"
            f"📊 Your current invites: {invite_count}\n\n"
            "To claim your reward, simply reach the required number of invites!"
        )
        
        update.message.reply_text(
            message,
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Error in show_freeze_cash: {e}")

# Captcha game handler
def start_captcha_game(update: Update, context: CallbackContext) -> int:
    try:
        user_id = update.effective_user.id
        user_data = get_user(user_id)
        
        # Check if user exists and is verified
        if not user_data:
            update.message.reply_text(
                "⚠️ Please restart with /start to register your account.")
            return -1

        if not user_data[6]:  # Not verified
            update.message.reply_text(
                "⚠️ Please complete verification first by using /start")
            return -1

        # Check if user has joined channel
        if not user_data[10]:
            update.message.reply_text("⚠️ You must join our group first!\n"
                                      f"Please join: {REQUIRED_CHANNEL}\n"
                                      "and try again.")
            return -1

        # Clear any existing captchas for this user
        c.execute("DELETE FROM captchas WHERE user_id=?", (user_id,))
        conn.commit()

        # Generate captcha
        captcha_file, captcha_solution = generate_captcha()
        if not captcha_file or not captcha_solution:
            update.message.reply_text(
                "⚠️ Failed to generate CAPTCHA. Please try again later.")
            return -1

        # Save captcha solution
        save_captcha(user_id, captcha_solution)

        # Send captcha image
        try:
            with open(captcha_file, 'rb') as photo:
                context.bot.send_photo(
                    chat_id=user_id,
                    photo=photo,
                    caption="🔍 *CAPTCHA GAME* 🔍\n\n"
                    f"Enter the text shown in the image to earn ₱{CAPTCHA_REWARD:.2f}!\n\n"
                    "Type your answer (case insensitive):",
                    parse_mode="Markdown",
                    reply_markup=ReplyKeyboardRemove())
        except Exception as e:
            logger.error(f"Error sending captcha image: {e}")
            update.message.reply_text(
                "⚠️ Failed to send CAPTCHA image. Please try again.")
            return -1
        finally:
            # Clean up captcha file
            try:
                if os.path.exists(captcha_file):
                    os.remove(captcha_file)
            except Exception as e:
                logger.error(f"Error removing captcha file: {e}")

        return CAPTCHA_GAME
    except Exception as e:
        logger.error(f"Error in start_captcha_game: {e}")
        update.message.reply_text("⚠️ An error occurred. Please try again.")
        return -1

# Captcha answer handler
def handle_captcha_answer(update: Update, context: CallbackContext) -> int:
    try:
        user_id = update.effective_user.id
        user_answer = update.message.text.upper().strip()

        # Get last captcha solution for this user
        c.execute(
            "SELECT captcha_solution FROM captchas WHERE user_id=? ORDER BY timestamp DESC LIMIT 1",
            (user_id,)
        )
        captcha_row = c.fetchone()

        if not captcha_row:
            update.message.reply_text(
                "❌ No captcha found. Please start a new captcha game.",
                parse_mode="Markdown")
            show_main_menu(update, context)
            return -1

        correct_answer = captcha_row[0]

        if user_answer == correct_answer:
            # Correct answer - delete the used captcha
            c.execute(
                "DELETE FROM captchas WHERE user_id=? AND captcha_solution=?",
                (user_id, correct_answer))
            conn.commit()

            update_balance(user_id, CAPTCHA_REWARD)
            user_data = get_user(user_id)
            new_balance = user_data[2] if user_data else 0

            update.message.reply_text(
                f"🎉 *Congratulations!* 🎉\n\n"
                f"Your answer '{user_answer}' is correct!\n"
                f"➕ ₱{CAPTCHA_REWARD:.2f} has been credited to your account\n"
                f"💰 New Balance: ₱{new_balance:.2f}",
                parse_mode="Markdown")
        else:
            # Incorrect answer
            update.message.reply_text(
                f"❌ *Incorrect Answer!*\n\n"
                f"You entered: '{user_answer}'\n"
                f"Correct answer was: '{correct_answer}'\n\n"
                "Don't worry! Try the captcha game again to earn money.\n"
                f"You can still earn ₱{CAPTCHA_REWARD:.2f} on your next try!",
                parse_mode="Markdown")

            # Delete the failed captcha
            c.execute(
                "DELETE FROM captchas WHERE user_id=? AND captcha_solution=?",
                (user_id, correct_answer))
            conn.commit()

        show_main_menu(update, context)
        return -1
    except Exception as e:
        logger.error(f"Error in handle_captcha_answer: {e}")
        update.message.reply_text(
            "⚠️ An error occurred while checking your answer. Please try again.",
            parse_mode="Markdown")
        show_main_menu(update, context)
        return -1

# Invite system with different links
def invite_friends(update: Update, context: CallbackContext):
    try:
        user_id = update.effective_user.id
        user_data = get_user(user_id)
        if not user_data:
            update.message.reply_text(
                "⚠️ Your account couldn't be loaded. Please restart with /start"
            )
            return

        # Check if user has joined channel
        if not user_data[10]:
            update.message.reply_text("⚠️ You must join our group first!\n"
                                      f"Please join: {REQUIRED_CHANNEL}\n"
                                      "and try again.")
            return

        invite_code = user_data[3]
        
        # Different invite links for variety
        invite_links = [
            f"https://t.me/{context.bot.username}?start={invite_code}",
            f"https://telegram.me/{context.bot.username}?start={invite_code}",
            f"https://t.me/share/url?url=join&text=Join%20Invitor%20Cash%20PH%20to%20earn%20money!&start={invite_code}"
        ]
        
        # Select a random invite link
        invite_link = random.choice(invite_links)

        update.message.reply_text(
            "👥 *INVITE & EARN* 👥\n\n"
            f"Invite friends and earn *₱{INVITE_REWARD:.2f}* for each successful referral!\n\n"
            f"Your unique invite link:\n`{invite_link}`\n\n"
            "You'll be notified when someone joins using your link!\n"
            f"Total invites: {user_data[5]}\n"
            f"Total earned: ₱{user_data[5] * INVITE_REWARD:.2f}\n\n"
            f"🎁 *BONUS*: Every 5 invites = 5 bonus quiz questions + ₱{BONUS_CASH_REWARD}!\n"
            f"💰 *Next bonus at*: {((user_data[5] // 5) + 1) * 5} invites",
            parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error in invite_friends: {e}")

# Open join channel link
def open_join_channel(update: Update, context: CallbackContext):
    try:
        context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="👥 *JOIN OUR MAIN GROUP* 👥\n\n"
                 "Join our main group for updates and exclusive rewards!\n\n"
                 "Click the button below to join:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("👉 Join Group Here", url=MAIN_GROUP_LINK)
            ]])
        )
    except Exception as e:
        logger.error(f"Error in open_join_channel: {e}")

# Open free 2000 PHP link
def open_free_2000(update: Update, context: CallbackContext):
    try:
        context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="🆓 *GET FREE ₱2000!* 🆓\n\n"
                 "Claim your free ₱2000 bonus now!\n\n"
                 "Click the button below to claim:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("💰 Claim Free ₱2000", url=FREE_2000_LINK)
            ]])
        )
    except Exception as e:
        logger.error(f"Error in open_free_2000: {e}")

# Open Arena Live link
def open_arena_live(update: Update, context: CallbackContext):
    try:
        context.bot.send_message(
            chat_id=update.effective_chat.id,
            text="🎰 *ARENA LIVE REGISTRATION* 🎰\n\n"
                 "Register at Arena Live and get ₱500 free bonus!\n\n"
                 "Click the button below to register:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("📝 Register Now", url=ARENA_LIVE_LINK)
            ]])
        )
    except Exception as e:
        logger.error(f"Error in open_arena_live: {e}")

# Withdrawal process
def start_withdrawal(update: Update, context: CallbackContext) -> int:
    try:
        user_id = update.effective_user.id
        user_data = get_user(user_id)
        if not user_data:
            update.message.reply_text(
                "⚠️ Your account couldn't be loaded. Please restart with /start"
            )
            return -1

        # Check if user has joined channel
        if not user_data[10]:
            update.message.reply_text("⚠️ You must join our group first!\n"
                                      f"Please join: {REQUIRED_CHANNEL}\n"
                                      "and try again.")
            return -1

        balance = user_data[2]

        if balance < MIN_WITHDRAWAL:
            update.message.reply_text(
                f"❌ Minimum withdrawal is ₱{MIN_WITHDRAWAL:.2f}\n"
                f"Your current balance: ₱{balance:.2f}")
            return -1

        # Require re-registration verification before withdrawal
        update.message.reply_text(
            "🔐 *WITHDRAWAL VERIFICATION REQUIRED* 🔐\n\n"
            "Before you can withdraw, you must verify your registration with our partner:\n\n"
            f"🔗 **[Click here to Register/Verify at Arena Live]({ARENA_LIVE_LINK})**\n\n"
            "📋 **Why is this required?**\n"
            "• Ensures you're registered with our trusted partner\n"
            "• Verifies legitimate withdrawal requests\n"
            "• Required for secure fund transfers\n"
            "• Prevents fraudulent activities\n\n"
            "Please complete registration/verification and click the button below:\n\n"
            "⚠️ *Note: Currently we only support GCash withdrawals. Support for Maya, Lazada, and banks coming soon!*",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    "✅ I've Completed Registration/Verification",
                    callback_data="verify_withdrawal")
            ]]))
        return -1
    except Exception as e:
        logger.error(f"Error in start_withdrawal: {e}")
        return -1

# Withdrawal verification callback
def verify_withdrawal_callback(update: Update, context: CallbackContext) -> int:
    try:
        query = update.callback_query
        query.answer()
        user_id = query.from_user.id
        user_data = get_user(user_id)

        if not user_data:
            query.edit_message_text(
                "⚠️ Your account couldn't be loaded. Please restart with /start"
            )
            return -1

        balance = user_data[2]

        query.edit_message_text(
            text="✅ *REGISTRATION VERIFIED!* ✅\n\n"
                 "Thank you for completing the registration verification!\n"
                 "You can now proceed with your withdrawal.",
            parse_mode="Markdown"
        )

        # Now proceed to withdrawal amount input
        context.bot.send_message(
            chat_id=user_id,
            text=f"💰 *WITHDRAW FUNDS* 💰\n\n"
                 f"Account Balance: ₱{balance:.2f}\n"
                 f"Min: ₱{MIN_WITHDRAWAL:.2f} | Max: ₱{MAX_WITHDRAWAL:.2f}\n\n"
                 "Enter amount to withdraw:",
            parse_mode="Markdown",
            reply_markup=ReplyKeyboardRemove()
        )
        return WITHDRAW_AMOUNT
    except Exception as e:
        logger.error(f"Error in verify_withdrawal_callback: {e}")
        return -1

def handle_withdrawal_amount(update: Update, context: CallbackContext) -> int:
    try:
        amount = float(update.message.text)
        user_id = update.effective_user.id
        user_data = get_user(user_id)
        if not user_data:
            update.message.reply_text(
                "⚠️ Your account couldn't be loaded. Please restart with /start"
            )
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
            "📝 *ENTER GCASH DETAILS* 📝\n\n"
            "Please provide your GCash information in this format:\n\n"
            "**Name:** Your full name (as registered in GCash)\n"
            "**Number:** Your GCash mobile number\n\n"
            "Example:\n"
            "Name: Juan Dela Cruz\n"
            "Number: 09123456789\n\n"
            "⚠️ *Note: Currently we only support GCash withdrawals. Support for Maya, Lazada, and banks coming soon!*",
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
        wallet_info = update.message.text.strip()
        amount = context.user_data['withdrawal_amount']
        user_id = update.effective_user.id
        user_data = get_user(user_id)
        if not user_data:
            update.message.reply_text(
                "⚠️ Your account couldn't be loaded. Please restart with /start"
            )
            return -1

        # Validate GCash format
        lines = wallet_info.split('\n')
        if len(lines) < 2:
            update.message.reply_text(
                "❌ *Invalid Format!*\n\n"
                "Please provide your GCash details in this format:\n\n"
                "Name: Your full name\n"
                "Number: Your GCash number\n\n"
                "Example:\n"
                "Name: Juan Dela Cruz\n"
                "Number: 09123456789",
                parse_mode="Markdown"
            )
            return WITHDRAW_INFO

        # Check if format contains "Name:" and "Number:"
        has_name = any("name:" in line.lower() for line in lines)
        has_number = any("number:" in line.lower() for line in lines)

        if not has_name or not has_number:
            update.message.reply_text(
                "❌ *Missing Information!*\n\n"
                "Please include both:\n"
                "• Name: (Your full name)\n"
                "• Number: (Your GCash number)\n\n"
                "Example:\n"
                "Name: Juan Dela Cruz\n"
                "Number: 09123456789",
                parse_mode="Markdown"
            )
            return WITHDRAW_INFO

        invite_count = user_data[5]
        invite_code = user_data[3]
        invite_link = f"https://t.me/{context.bot.username}?start={invite_code}"

        # Format wallet info for storage
        formatted_wallet_info = f"GCash Details:\n{wallet_info}"

        # Save withdrawal request
        if not save_withdrawal(user_id, amount, formatted_wallet_info):
            update.message.reply_text(
                "⚠️ Failed to process withdrawal. Please try again later.")
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
            update.message.reply_text(
                "⚠️ Your account couldn't be loaded. Please restart with /start"
            )
            return

        # Check if user has joined channel
        if not user_data[10]:
            update.message.reply_text("⚠️ You must join our group first!\n"
                                      f"Please join: {REQUIRED_CHANNEL}\n"
                                      "and try again.")
            return

        balance = user_data[2]
        invite_count = user_data[5]
        total_earned = invite_count * INVITE_REWARD
        available_questions = get_available_quiz_questions(user_id)

        update.message.reply_text(
            f"💰 *Account Balance: ₱{balance:.2f}*\n"
            f"👥 Total Invites: {invite_count}\n"
            f"💸 Total Earned from Invites: ₱{total_earned:.2f}\n"
            f"❓ Quiz Questions Available: {available_questions}",
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Error in check_balance: {e}")

# Handle other messages
def handle_other_messages(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    user_data = get_user(user_id)
    
    if not user_data:
        context.bot.send_message(user_id, "Please start with /start to begin")
        return
    
    if not user_data[6]:  # Not verified
        remaining_time = get_remaining_wait_time(user_id)
        minutes = remaining_time // 60
        seconds = remaining_time % 60
        
        if can_verify(user_id):
            context.bot.send_message(
                user_id,
                "✅ You can now complete verification!\n"
                "Please use /start to continue",
            )
        else:
            context.bot.send_message(
                user_id,
                f"⏳ Please wait {minutes:02d}:{seconds:02d} before you can verify\n\n"
                "💡 **Don't forget to register first:**\n"
                f"🔗 [Register at Arena Live]({ARENA_LIVE_LINK})\n\n"
                "Use /start after the waiting period",
                parse_mode="Markdown"
            )
        return
    
    if user_data[6] and not user_data[10]:  # Verified but not joined channel
        context.bot.send_message(
            user_id,
            "⚠️ You must join our group to continue!\n"
            f"Please join: {REQUIRED_CHANNEL}\n"
            "and use /start again",
        )
        return
    
    # Show main menu for other messages
    show_main_menu(update, context)

# Promotional messaging system
def send_promotional_message():
    """Send promotional message to all verified users every 50 minutes"""
    try:
        # Get all verified users who have joined the channel
        c.execute(
            "SELECT user_id, invite_code FROM users WHERE verified=1 AND channel_joined=1"
        )
        users = c.fetchall()

        if not users:
            logger.info("No verified users found for promotional message")
            return

        successful_sends = 0
        failed_sends = 0

        for user_id, invite_code in users:
            try:
                # Send promotional message with image
                with open('attached_assets/IMG_20250720_115734_1752983888931.jpg', 'rb') as photo:
                    updater.bot.send_photo(
                        chat_id=user_id,
                        photo=photo,
                        caption="𝙃𝙊𝙒 𝘿𝙊 𝙔𝙊𝙐 𝙀𝘼𝙍𝙉 𝙄𝙉 𝘼𝙍𝙀𝙉𝘼𝙇𝙄𝙑𝙀? 🔊\n\n"
                               "1.𝙍𝙚𝙜𝙞𝙨𝙩𝙚𝙧 𝙁𝙞𝙧𝙨𝙩 : (𝙍𝙀𝘾𝙊𝙈𝙈𝙀𝙉𝘿 𝙈𝙊𝘽𝙄𝙇𝙀 𝙉𝙐𝙈𝘽𝙀𝙍 𝙏𝙊 𝙍𝙀𝙂𝙄𝙎𝙏𝙀𝙍)\n"
                               "https://arenalive.ph/s/rzRkoGR\n"
                               "2.𝙂𝙊 𝙏𝙊 𝙇𝙄𝙑𝙀 𝙎𝙀𝘾𝙏𝙄𝙊𝙉 𝙋𝙄𝘾𝙆 𝘼 𝙇𝙄𝙑𝙀 𝘿𝙊 𝙔𝙊𝙐 𝙒𝘼𝙉𝙏 𝙏𝙊 𝙒𝘼𝙏𝘾𝙃 𝘼𝙉𝘿 𝙒𝘼𝙏𝘾𝙃 20 𝙈𝙄𝙉𝙐𝙏𝙀𝙎 𝙄𝙉 𝙇𝙄𝙑𝙀.\n"
                               "3.𝙏𝙃𝙀𝙉 𝙍𝙀𝙋𝙀𝘼𝙏 𝙏𝙃𝘼𝙏 𝙀𝙑𝙀𝙍𝙔𝘿𝘼𝙔 𝙊𝙍 3 𝘿𝘼𝙔𝙎 𝙊𝙁 𝙒𝘼𝙏𝘾𝙃𝙄𝙉𝙂 20 𝙈𝙄𝙉𝙐𝙏𝙀𝙎 𝘼 𝘿𝘼𝙔 ,𝙏𝙃𝙀𝙉 𝘼𝙐𝙏𝙊𝙈𝘼𝙏𝙄𝘾𝘼𝙇𝙇𝙔 𝙏𝙃𝙀 (✅💲𝙇𝙄𝙑𝙀 𝙀𝘼𝙍𝙉𝙄𝙉𝙂) 𝙒𝙄𝙇𝙇 𝘼𝘾𝙏𝙄𝙑𝘼𝙏𝙀.\n\n"
                               "☢️𝙉𝙊𝙏𝙀. 𝙏𝙃𝙄𝙎 𝙒𝙄𝙇𝙇 𝙉𝙊𝙏 𝙃𝘼𝙋𝙋𝙀𝙉 𝙄𝙁 𝙔𝙊𝙐 𝘿𝙊 𝙉𝙊𝙏 𝘿𝙊 𝙏𝙃𝙀 𝙒𝘼𝙏𝘾𝙃𝙄𝙉𝙂 𝘼 3 𝘿𝘼𝙔𝙎 𝙊𝙁 𝙇𝙄𝙑𝙀 𝘼𝙉𝘿 20 𝙈𝙄𝙉𝙐𝙏𝙀𝙎 𝙒𝘼𝙏𝘾𝙃𝙄𝙉𝙂 𝙇𝙄𝙑𝙀\n\n"
                               "𝙃𝙤𝙬 𝙈𝙪𝙘𝙝 𝘿𝙤 𝙔𝙤𝙪 𝙀𝙖𝙧𝙣 𝙞𝙣 (𝙇𝙄𝙑𝙀 𝙀𝘼𝙍𝙉𝙄𝙉𝙂)?\n"
                               "20 𝙢𝙞𝙣𝙪𝙩𝙚𝙨 = 50 𝙥𝙝𝙥\n"
                               "60 𝙢𝙞𝙣𝙪𝙩𝙚𝙨 = 150 𝙥𝙝𝙥\n"
                               "120 𝙢𝙞𝙣𝙪𝙩𝙚𝙨 = 300 𝙥𝙝𝙥\n"
                               "☢️𝙉𝙊𝙏𝙀. 𝙏𝙃𝙄𝙎 𝙒𝙄𝙇𝙇 𝙉𝙊𝙏 𝙃𝘼𝙋𝙋𝙀𝙉 𝙄𝙁 𝙔𝙊𝙐 𝘿𝙊 𝙉𝙊𝙏 𝘿𝙊 𝙏𝙃𝙀 𝙒𝘼𝙏𝘾𝙃𝙄𝙉𝙂 𝘼 3 𝘿𝘼𝙔𝙎 𝙊𝙁 𝙇𝙄𝙑𝙀 𝘼𝙉𝘿 20 𝙈𝙄𝙉𝙐𝙏𝙀𝙎 𝙒𝘼𝙏𝘾𝙃𝙄𝙉𝙂 𝙇𝙄𝙑𝙀"
                    )
                successful_sends += 1

                # Small delay to avoid rate limiting
                time.sleep(0.1)

            except Exception as e:
                failed_sends += 1
                logger.error(f"Failed to send promotional message to user {user_id}: {e}")
                continue

        logger.info(f"Promotional message sent: {successful_sends} successful, {failed_sends} failed")

    except Exception as e:
        logger.error(f"Error in send_promotional_message: {e}")

# Mining reset command handler (admin only)
def reset_mining_command(update: Update, context: CallbackContext):
    try:
        user_id = update.effective_user.id
        
        # Add admin user IDs here - replace with actual admin IDs
        admin_ids = [2074976711, 7407991772]  # Add your admin user IDs here
        
        if user_id not in admin_ids:
            update.message.reply_text("⚠️ You don't have permission to use this command.")
            return
            
        if reset_all_mining_data():
            update.message.reply_text(
                "✅ *PESO MINING RESET COMPLETE!* ✅\n\n"
                "• All mining start times have been reset\n"
                "• All claim dates have been cleared\n"
                "• Invite counts are preserved\n"
                "• Users can start mining fresh with new rates",
                parse_mode="Markdown"
            )
        else:
            update.message.reply_text("❌ Failed to reset mining data. Check logs for details.")
            
    except Exception as e:
        logger.error(f"Error in reset_mining_command: {e}")
        update.message.reply_text("❌ An error occurred while resetting mining data.")

# Main bot function
def main() -> None:
    global updater

    # Reset all mining data on startup for the new update
    logger.info("Resetting peso mining data for new update...")
    if reset_all_mining_data():
        logger.info("Peso mining data reset successfully")
    else:
        logger.error("Failed to reset peso mining data")

    # Start Flask server in a separate thread
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()
    logger.info("Flask server started for keep-alive")

    # Start Telegram bot
    updater = Updater(TOKEN)
    dispatcher = updater.dispatcher

    # Initialize and start scheduler for promotional messages
    scheduler = BackgroundScheduler(timezone=pytz.UTC)
    scheduler.add_job(send_promotional_message,
                      'interval',
                      minutes=50,
                      id='promotional_message',
                      replace_existing=True)
    scheduler.start()
    logger.info("Promotional message scheduler started - messages will be sent every 50 minutes")

    # Add handlers
    dispatcher.add_handler(CommandHandler('start', start))
    dispatcher.add_handler(CommandHandler('resetmining', reset_mining_command))
    dispatcher.add_handler(CallbackQueryHandler(verify_callback, pattern='^verify$'))
    dispatcher.add_handler(CallbackQueryHandler(join_channel_callback, pattern='^join_channel$'))
    dispatcher.add_handler(CallbackQueryHandler(group_join_callback, pattern='^group_joined$'))
    dispatcher.add_handler(CallbackQueryHandler(verify_withdrawal_callback, pattern='^verify_withdrawal$'))
    dispatcher.add_handler(CallbackQueryHandler(claim_mining_callback, pattern='^claim_mining$'))
    dispatcher.add_handler(CallbackQueryHandler(handle_quiz_answer, pattern='^quiz_'))
    dispatcher.add_handler(CallbackQueryHandler(next_question_callback, pattern='^next_question$'))

    # Menu handlers
    dispatcher.add_handler(MessageHandler(Filters.regex('^🎮 Play Captcha Game$'), start_captcha_game))
    dispatcher.add_handler(MessageHandler(Filters.regex('^❓ Play Quiz Game$'), start_quiz_game))
    dispatcher.add_handler(MessageHandler(Filters.regex('^👥 Invite & Earn$'), invite_friends))
    dispatcher.add_handler(MessageHandler(Filters.regex('^📅 Daily Sign-in$'), daily_signin))
    dispatcher.add_handler(MessageHandler(Filters.regex('^💰 Withdraw$'), start_withdrawal))
    dispatcher.add_handler(MessageHandler(Filters.regex('^💼 My Balance$'), check_balance))
    
    dispatcher.add_handler(MessageHandler(Filters.regex('^🎁 Claim FREE ₱100$'), claim_free_100_handler))
    dispatcher.add_handler(MessageHandler(Filters.regex('^⛏️ Peso Mining$'), peso_mining_handler))
    dispatcher.add_handler(MessageHandler(Filters.regex('^👥 Join Channel$'), open_join_channel))
    dispatcher.add_handler(MessageHandler(Filters.regex('^🆓 FREE 2000PHP$'), open_free_2000))
    dispatcher.add_handler(MessageHandler(Filters.regex('^🎰 ArenaLive Register$'), open_arena_live))

    # Conversation handlers
    captcha_conv = ConversationHandler(
        entry_points=[],
        states={
            CAPTCHA_GAME: [
                MessageHandler(Filters.text & ~Filters.command, handle_captcha_answer)
            ],
        },
        fallbacks=[CommandHandler('cancel', show_main_menu)]
    )

    withdrawal_conv = ConversationHandler(
        entry_points=[],
        states={
            WITHDRAW_AMOUNT: [
                MessageHandler(Filters.text & ~Filters.command, handle_withdrawal_amount)
            ],
            WITHDRAW_INFO: [
                MessageHandler(Filters.text & ~Filters.command, handle_wallet_info)
            ],
        },
        fallbacks=[CommandHandler('cancel', show_main_menu)]
    )

    # Handle all other messages
    dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_other_messages))
    
    dispatcher.add_handler(captcha_conv)
    dispatcher.add_handler(withdrawal_conv)

    # Start the Bot with error handling
    try:
        updater.start_polling()
        logger.info("Telegram bot started successfully")
        updater.idle()
    except Exception as e:
        logger.error(f"Bot polling error: {e}")
        # Restart polling after a delay
        import time
        time.sleep(5)
        try:
            updater.start_polling()
            logger.info("Telegram bot restarted successfully")
            updater.idle()
        except Exception as e2:
            logger.error(f"Bot restart failed: {e2}")

if __name__ == '__main__':
    main()
