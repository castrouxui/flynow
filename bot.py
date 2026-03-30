import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timedelta
import telebot
import requests

TOKEN = os.environ["BOT_TOKEN"]
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")

bot = telebot.TeleBot(TOKEN)

# Ciudades/países → código IATA
CIUDAD_A_IATA = {
    "mendoza": "MDZ", "mdz": "MDZ",
    "buenos aires": "EZE", "ezeiza": "EZE", "eze": "EZE",
    "aeroparque": "AEP", "aep": "AEP",
    "barcelona": "BCN", "bcn": "BCN",
    "madrid": "MAD", "mad": "MAD",
    "miami": "MIA", "mia": "MIA",
    "new york": "JFK", "nueva york": "JFK", "jfk": "JFK",
    "roma": "FCO", "rome": "FCO", "fco": "FCO",
    "paris": "CDG", "parís": "CDG", "cdg": "CDG",
    "london": "LHR", "londres": "LHR", "lhr": "LHR",
    "cancun": "CUN", "cancún": "CUN", "cun": "CUN",
    "lima": "LIM", "lim": "LIM",
    "santiago": "SCL", "scl": "SCL",
    "bogota": "BOG", "bogotá": "BOG", "bog": "BOG",
    "sao paulo": "GRU", "são paulo": "GRU", "gru": "GRU",
    "rio": "GIG", "río": "GIG", "gig": "GIG",
    "cordoba": "COR", "córdoba": "COR", "cor": "COR",
    "rosario": "ROS", "ros": "ROS",
    "bariloche": "BRC", "brc": "BRC",
    "iguazu": "IGR", "iguazú": "IGR", "igr": "IGR",
    "dubai": "DXB", "dxb": "DXB",
    "tokio": "NRT", "tokyo": "NRT", "nrt": "NRT",
    "amsterdam": "AMS", "ams": "AMS",
    "frankfurt": "FRA", "fra": "FRA",
    "orlando": "MCO", "mco": "MCO",
    "los angeles": "LAX", "lax": "LAX",
    "toronto": "YYZ", "yyz": "YYZ",
    "ciudad de mexico": "MEX", "mexico": "MEX", "mex": "MEX",
    "tenerife": "TFN", "tfn": "TFN",
    "lisboa": "LIS", "lisbon": "LIS", "lis": "LIS",
}

MESES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4,
    "mayo": 5, "junio": 6, "julio": 7, "agosto": 8,
    "septiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
}

HELP_TEXT = """
✈️ *Buscador de Vuelos*

Escribime de forma natural o mandame un audio 🎙️:

_"vuelos de mendoza a barcelona en mayo"_
_"quiero ir a madrid desde mendoza, 7 días"_
_"fechas baratas mdz eze"_
_"mendoza miami junio semana"_

O usá comandos:
*/vuelos* `MDZ EZE 2026-04-15`
*/fechas* `MDZ BCN 90 7`
"""


def strip_ansi(text):
    return re.sub(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])', '', text)


def find_fli():
    fli = shutil.which("fli")
    if fli:
        return [fli]
    for candidate in ["/opt/venv/bin/fli", os.path.expanduser("~/.local/bin/fli")]:
        if os.path.isfile(candidate):
            return [candidate]
    return [sys.executable, "-m", "fli"]


def run_fli(args: list, timeout=60) -> str:
    try:
        result = subprocess.run(
            find_fli() + args,
            capture_output=True, text=True, timeout=timeout,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
        return strip_ansi((result.stdout or result.stderr)).strip()
    except subprocess.TimeoutExpired:
        return "⏱ La búsqueda tardó demasiado. Intentá con un rango más corto."
    except Exception as e:
        return f"❌ Error: {e}"


def format_output(raw: str) -> str:
    lines = raw.splitlines()
    table_lines, in_table = [], False
    for line in lines:
        if "Cheapest Dates" in line or "Flight Results" in line:
            in_table = True
        if in_table:
            table_lines.append(line)
    return "\n".join(table_lines) if table_lines else raw


def resolve_iata(word: str) -> str | None:
    return CIUDAD_A_IATA.get(word.lower().strip())


def parse_natural(text: str) -> dict | None:
    text_lower = text.lower()
    found_iata = []

    for word in text.split():
        clean = re.sub(r'[^a-zA-Z]', '', word).upper()
        if len(clean) == 3 and clean.isalpha():
            resolved = resolve_iata(clean.lower())
            if resolved and resolved not in found_iata:
                found_iata.append(resolved)
            elif clean in CIUDAD_A_IATA.values() and clean not in found_iata:
                found_iata.append(clean)

    for city, code in sorted(CIUDAD_A_IATA.items(), key=lambda x: -len(x[0])):
        if city in text_lower and code not in found_iata:
            found_iata.append(code)

    if len(found_iata) < 2:
        return None

    mes = None
    for nombre, num in MESES.items():
        if nombre in text_lower:
            mes = num
            break

    duracion = 3
    match = re.search(r'(\d+)\s*(día|noche|dias|noches|nights?|days?|semana)', text_lower)
    if match:
        val = match.group(1)
        unit = match.group(2)
        duracion = int(val) * 7 if "semana" in unit else int(val)

    return {"origen": found_iata[0], "destino": found_iata[1], "mes": mes, "duracion": duracion}


def transcribe_audio(file_path: str) -> str | None:
    if not GROQ_API_KEY:
        return None
    try:
        with open(file_path, "rb") as f:
            response = requests.post(
                "https://api.groq.com/openai/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
                files={"file": (os.path.basename(file_path), f, "audio/ogg")},
                data={"model": "whisper-large-v3", "language": "es"},
                timeout=30,
            )
        if response.status_code == 200:
            return response.json().get("text", "").strip()
    except Exception:
        pass
    return None


def download_voice(file_id: str) -> str | None:
    try:
        file_info = bot.get_file(file_id)
        file_url = f"https://api.telegram.org/file/bot{TOKEN}/{file_info.file_path}"
        response = requests.get(file_url, timeout=30)
        tmp_path = f"/tmp/voice_{file_id}.ogg"
        with open(tmp_path, "wb") as f:
            f.write(response.content)
        return tmp_path
    except Exception:
        return None


def do_fechas(chat_id, reply_to_id, origen, destino, mes=None, duracion=3):
    if mes:
        year = datetime.today().year
        now = datetime.today()
        if mes < now.month or (mes == now.month and now.day > 20):
            year += 1
        desde = datetime(year, mes, 1).strftime("%Y-%m-%d")
        hasta_dt = datetime(year + 1, 1, 1) - timedelta(days=1) if mes == 12 \
            else datetime(year, mes + 1, 1) - timedelta(days=1)
        hasta = hasta_dt.strftime("%Y-%m-%d")
        rango_txt = list(MESES.keys())[mes - 1].capitalize()
    else:
        desde = datetime.today().strftime("%Y-%m-%d")
        hasta = (datetime.today() + timedelta(days=60)).strftime("%Y-%m-%d")
        rango_txt = "próximos 60 días"

    msg = bot.send_message(chat_id, f"🔍 Buscando {origen} → {destino} ({rango_txt})...",
                           reply_to_message_id=reply_to_id)
    result = run_fli(["dates", origen, destino, "--from", desde, "--to", hasta,
                      "--duration", str(duracion), "--round", "--sort"])
    output = format_output(result) or "No se encontraron resultados."
    bot.edit_message_text(
        f"📅 *{origen} → {destino}* — {rango_txt}, {duracion} noches\n\n```\n{output[:3800]}\n```",
        chat_id=chat_id, message_id=msg.message_id, parse_mode="Markdown",
    )


def do_vuelos(chat_id, reply_to_id, origen, destino, fecha_ida, fecha_vuelta=None):
    extra = ["--return", fecha_vuelta] if fecha_vuelta else []
    msg = bot.send_message(chat_id, f"🔍 Buscando vuelos {origen} → {destino}...",
                           reply_to_message_id=reply_to_id)
    result = run_fli(["flights", origen, destino, fecha_ida] + extra + ["--sort", "CHEAPEST"])
    output = format_output(result) or "No se encontraron vuelos."
    label = fecha_ida + (f" → {fecha_vuelta}" if fecha_vuelta else "")
    bot.edit_message_text(
        f"✈️ *{origen} → {destino}* — {label}\n\n```\n{output[:3800]}\n```",
        chat_id=chat_id, message_id=msg.message_id, parse_mode="Markdown",
    )


def process_text(chat_id, message_id, text):
    parsed = parse_natural(text)
    if parsed:
        do_fechas(chat_id, message_id, parsed["origen"], parsed["destino"],
                  mes=parsed.get("mes"), duracion=parsed.get("duracion", 3))
    else:
        bot.send_message(
            chat_id,
            "No entendí la ruta 🤔\n\nEjemplos:\n_\"mendoza barcelona mayo\"_\n_\"mdz eze junio 7 días\"_\n\nO usá /help",
            reply_to_message_id=message_id, parse_mode="Markdown",
        )


# ── Handlers ────────────────────────────────────────────────────────────────

@bot.message_handler(commands=["start", "help", "ayuda"])
def cmd_help(message):
    bot.send_message(message.chat.id, HELP_TEXT, parse_mode="Markdown")


@bot.message_handler(commands=["vuelos"])
def cmd_vuelos(message):
    parts = message.text.split()[1:]
    if len(parts) < 3:
        bot.reply_to(message, "Uso: `/vuelos ORIGEN DESTINO FECHA [VUELTA]`\nEj: `/vuelos MDZ EZE 2026-04-15`",
                     parse_mode="Markdown")
        return
    origen = resolve_iata(parts[0]) or parts[0].upper()
    destino = resolve_iata(parts[1]) or parts[1].upper()
    do_vuelos(message.chat.id, message.message_id, origen, destino, parts[2],
              parts[3] if len(parts) >= 4 else None)


@bot.message_handler(commands=["fechas"])
def cmd_fechas(message):
    parts = message.text.split()[1:]
    if len(parts) < 2:
        bot.reply_to(message, "Uso: `/fechas ORIGEN DESTINO [DIAS] [DURACION]`\nEj: `/fechas MDZ BCN 90 7`",
                     parse_mode="Markdown")
        return
    origen = resolve_iata(parts[0]) or parts[0].upper()
    destino = resolve_iata(parts[1]) or parts[1].upper()
    dias = int(parts[2]) if len(parts) >= 3 else 60
    duracion = int(parts[3]) if len(parts) >= 4 else 3
    desde = datetime.today().strftime("%Y-%m-%d")
    hasta = (datetime.today() + timedelta(days=dias)).strftime("%Y-%m-%d")
    msg = bot.reply_to(message, f"🔍 Buscando {origen} → {destino}...")
    result = run_fli(["dates", origen, destino, "--from", desde, "--to", hasta,
                      "--duration", str(duracion), "--round", "--sort"])
    output = format_output(result) or "No se encontraron resultados."
    bot.edit_message_text(
        f"📅 *{origen} → {destino}* — próximos {dias} días, {duracion} noches\n\n```\n{output[:3800]}\n```",
        chat_id=message.chat.id, message_id=msg.message_id, parse_mode="Markdown",
    )


@bot.message_handler(content_types=["voice"])
def handle_voice(message):
    if not GROQ_API_KEY:
        bot.reply_to(message, "🎙️ Audio no disponible aún (falta configurar GROQ_API_KEY).")
        return
    msg = bot.reply_to(message, "🎙️ Transcribiendo audio...")
    path = download_voice(message.voice.file_id)
    if not path:
        bot.edit_message_text("❌ No pude descargar el audio.", message.chat.id, msg.message_id)
        return
    text = transcribe_audio(path)
    try:
        os.remove(path)
    except Exception:
        pass
    if not text:
        bot.edit_message_text("❌ No pude transcribir el audio.", message.chat.id, msg.message_id)
        return
    bot.edit_message_text(f"🎙️ _{text}_", message.chat.id, msg.message_id, parse_mode="Markdown")
    process_text(message.chat.id, message.message_id, text)


@bot.message_handler(content_types=["text"])
def handle_text(message):
    process_text(message.chat.id, message.message_id, message.text)


if __name__ == "__main__":
    print("Bot iniciado...")
    bot.infinity_polling()
