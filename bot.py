import os
import logging
import random
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import google.generativeai as genai
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    CallbackQueryHandler,
    ConversationHandler,
)

# ===== YOUR CONFIGURATION =====
BOT_TOKEN = "7426089629:AAGh7bX2_ohMRzSkG0UP6Ve4wX3338p1jy8"
GEMINI_API_KEY = "AIzaSyCjjL21bQZzJIWEWYJvKGTpfr94f0up2VA"
ADMIN_ID = 6654508928  # Your Telegram user ID
# =============================

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Gemini setup
genai.configure(api_key=GEMINI_API_KEY)
generation_config = {
    "temperature": 0.7,
    "top_p": 1,
    "top_k": 40,
    "max_output_tokens": 2048,
}
safety_settings = [
    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
]
model = genai.GenerativeModel(
    model_name="gemini-pro",
    generation_config=generation_config,
    safety_settings=safety_settings
)

# Quiz states
SELECT_SUBJECT, QUIZ_IN_PROGRESS = range(2)

# Group activity tracking
group_activity: Dict[int, datetime] = {}
conversation_starters = [
    "What's your favorite subject in school?",
    "If you could visit any country, where would you go?",
    "What's the most interesting fact you know?",
]

# Rate limiting
user_last_message: Dict[int, datetime] = {}
MESSAGE_COOLDOWN = 10  # seconds

# ========================
# HELPER FUNCTIONS
# ========================
async def generate_gemini_response(prompt: str) -> str:
    """Generate a response using Gemini API."""
    try:
        response = model.generate_content(
            "You're a helpful assistant in a Telegram chat. "
            "Respond concisely and friendly to: " + prompt
        )
        return response.text
    except Exception as e:
        logger.error(f"Gemini error: {e}")
        return "Sorry, I couldn't process that. Please try again later."

def is_admin(user_id: int) -> bool:
    """Check if user is admin."""
    return user_id == ADMIN_ID

# ========================
# COMMAND HANDLERS
# ========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send welcome message."""
    user = update.effective_user
    await update.message.reply_text(
        f"👋 Hi {user.first_name}! I'm your Gemini-powered Telegram bot.\n\n"
        "Available commands:\n"
        "/start - Show this message\n"
        "/quiz - Start a quiz\n"
        "/ask [question] - Ask me anything"
    )

async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show admin stats."""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ Admin only.")
        return
    
    stats = (
        f"📊 Bot Stats\n"
        f"Admin ID: {ADMIN_ID}\n"
        f"Active groups: {len(group_activity)}"
    )
    await update.message.reply_text(stats)

# ========================
# QUIZ SYSTEM
# ========================
async def quiz_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start quiz menu."""
    keyboard = [
        [InlineKeyboardButton("Math", callback_data="subject_math")],
        [InlineKeyboardButton("Science", callback_data="subject_science")],
        [InlineKeyboardButton("General Knowledge", callback_data="subject_gk")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "📚 Choose a quiz subject:",
        reply_markup=reply_markup
    )
    return SELECT_SUBJECT

async def handle_quiz_subject(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generate quiz question."""
    query = update.callback_query
    await query.answer()
    
    subject = query.data.split("_")[1]
    prompt = (
        f"Create one multiple-choice quiz question for grade 8 students about {subject}. "
        "Format: Question: [question]\nA) [option1]\nB) [option2]\nC) [option3]\nD) [option4]\n"
        "Correct: [letter]"
    )
    
    try:
        response = await generate_gemini_response(prompt)
        lines = response.split("\n")
        question = lines[0].replace("Question: ", "")
        options = lines[1:5]
        correct = lines[5].split(": ")[1].strip().upper()
        
        context.user_data['correct_answer'] = correct
        
        keyboard = [
            [InlineKeyboardButton(opt, callback_data=f"ans_{opt[0]}")]
            for opt in options if ")" in opt
        ]
        
        await query.edit_message_text(
            text=f"❓ {question}",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return QUIZ_IN_PROGRESS
    except Exception as e:
        await query.edit_message_text("⚠️ Failed to generate quiz. Try again later.")
        return ConversationHandler.END

# ========================
# MESSAGE HANDLING
# ========================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle all messages."""
    # Ignore messages from bots
    if update.message.from_user.is_bot:
        return
    
    # Rate limiting
    user_id = update.message.from_user.id
    now = datetime.now()
    if user_id in user_last_message and (now - user_last_message[user_id]).seconds < MESSAGE_COOLDOWN:
        return
    user_last_message[user_id] = now
    
    # Track group activity
    if update.message.chat.type in ['group', 'supergroup']:
        group_activity[update.message.chat.id] = now
    
    # Check if bot is mentioned or message is a reply to bot
    is_direct = (
        update.message.text and 
        (f"@{context.bot.username}" in update.message.text or
         update.message.reply_to_message and 
         update.message.reply_to_message.from_user.id == context.bot.id)
    )
    
    # Respond to direct messages or mentions
    if update.message.chat.type == 'private' or is_direct:
        prompt = update.message.text.replace(f"@{context.bot.username}", "").strip()
        response = await generate_gemini_response(prompt)
        await update.message.reply_text(response[:4000])  # Truncate long messages

# ========================
# MAIN BOT SETUP
# ========================
def main():
    """Start the bot."""
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("stats", admin_stats))
    
    # Quiz conversation handler
    quiz_conv = ConversationHandler(
        entry_points=[CommandHandler("quiz", quiz_start)],
        states={
            SELECT_SUBJECT: [CallbackQueryHandler(handle_quiz_subject, pattern="^subject_")],
            QUIZ_IN_PROGRESS: [CallbackQueryHandler(handle_quiz_answer, pattern="^ans_")],
        },
        fallbacks=[CommandHandler("cancel", lambda u,c: ConversationHandler.END)],
    )
    application.add_handler(quiz_conv)
    
    # Message handler
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Error handler
    application.add_error_handler(lambda u,c: logger.error(c.error))
    
    # Start polling
    application.run_polling()

if __name__ == '__main__':
    main()
