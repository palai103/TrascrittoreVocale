from dataclasses import dataclass, field
from pathlib import Path
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    ContextTypes,
    CallbackContext,
    CallbackQueryHandler,
    MessageHandler,
    filters,
)
from telegram.constants import ChatMemberStatus
from google import genai
import os

from dotenv import load_dotenv

load_dotenv(override=True)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI = genai.Client(api_key=GEMINI_API_KEY)
PROMPT = """
## Istruzioni

1. **Trascrivi l'audio in italiano:** Trascrivi accuratamente il contenuto del file audio allegato, in italiano.

2. **Analizza, correggi e migliora:** Analizza il contesto dell'audio, correggi eventuali errori di sintassi, semantica o grammatica e migliora il flusso del discorso.

3. **Post-processing:** Elimina ripetizioni, esitazioni o informazioni irrilevanti.

4. **Restituisci solo il testo:** Restituisci *esclusivamente* il testo post-processato in italiano, senza ulteriori commenti o spiegazioni.
"""


@dataclass
class WhitelistLoader:
    whitelist: list[int] = field(default_factory=list)
    file_path: str = "whitelist.txt"

    @property
    def load_from_file(self) -> list[int]:
        self.whitelist = []
        try:
            with open(self.file_path, "r") as file:
                for line in file:
                    line = line.strip()
                    if line.isdigit():
                        self.whitelist.append(int(line))
            return self.whitelist
        except FileNotFoundError:
            print(f"Errore: Il file '{self.file_path}' non esiste.")
            return self.whitelist
        except ValueError as e:
            print(f"Errore nel parsing del file: {e}")
            return self.whitelist


WHITELISTED_USERS = WhitelistLoader()


def is_whitelisted(user_id: int) -> bool:
    """Check if a user is in the whitelist."""
    return user_id in WHITELISTED_USERS.load_from_file


async def is_whitelisted_member(chat_id: int, context: CallbackContext) -> bool:
    """Check if at least one whitelisted user is in the group."""
    for user_id in WHITELISTED_USERS.load_from_file:
        try:
            member = await context.bot.get_chat_member(chat_id, user_id)
            if member.status in [
                ChatMemberStatus.ADMINISTRATOR,
                ChatMemberStatus.OWNER,
                ChatMemberStatus.MEMBER,
            ]:
                return True
        except Exception as e:
            print(e)
            pass
    return False


async def transcribe_audio(audio_file_path: Path) -> str | None:
    try:
        myfile = GEMINI.files.upload(file=audio_file_path)

        response = GEMINI.models.generate_content(
            model="gemini-2.0-flash", contents=[PROMPT, myfile]
        )

        return response.text
    except Exception as e:
        return f"Errore: {str(e)}"


async def transcribe_btn_callback(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(text="Sto traducendo ⏳")

    response = await transcribe_audio(audio_file_path=query.data.split("@")[1])
    await query.edit_message_text(response)

    os.remove(query.data.split("@")[1])


async def handle_audio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    chat = message.chat

    if chat.type == "private":
        # Private chat: Only allow whitelisted users
        if not is_whitelisted(message.from_user.id):
            return
    else:
        # Group chat: Check if any whitelisted user is present
        if not await is_whitelisted_member(chat.id, context):
            return

    audio_file = await context.bot.getFile(update.message.voice.file_id)  # type: ignore
    audio_file_path = await audio_file.download_to_drive()

    # Ask the user if wants to translate the audio
    keyboard = [
        [
            InlineKeyboardButton(
                "Trascrivi ➡️", callback_data=f"transcribe@{audio_file_path}"
            )
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "Vuoi trascrivere questo audio?", reply_markup=reply_markup
    )


def main():
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    application.add_handler(MessageHandler(filters.VOICE, handle_audio))

    application.add_handler(
        CallbackQueryHandler(transcribe_btn_callback, pattern="^transcribe@.*")
    )

    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
