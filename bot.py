import json
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

SALUDOS = {"hola", "buenas", "hey", "hi", "buen dia", "buen día", "buenas tardes",
           "buenas noches", "buenos dias", "buenos días", "ola", "holaa", "holis"}

RESPUESTAS_SALUDO = [
    "¡Hola! 👋 Soy Flynow, tu asistente de vuelos baratos.\n\n"
    "Puedo ayudarte a encontrar los mejores precios. Solo contame a dónde querés ir, por ejemplo:\n\n"
    "✈️ _\"quiero ir a Barcelona en julio\"_\n"
    "✈️ _\"vuelos de Mendoza a Miami en junio\"_\n"
    "✈️ _\"fechas baratas para ir a Madrid\"_\n\n"
    "También podés mandarme un 🎙️ *audio* y te entiendo igual.\n\n"
    "¿A dónde soñás viajar? 😊",

    "¡Buenas! ✈️ Acá Flynow, tu copiloto para encontrar vuelos baratos.\n\n"
    "Contame tu plan de viaje y yo busco los mejores precios. Por ejemplo:\n\n"
    "🗓️ _\"mendoza a ezeiza la semana que viene\"_\n"
    "🗓️ _\"quiero una semana en Roma en agosto\"_\n\n"
    "¿A dónde querés ir? 🌍",
]

HELP_TEXT = (
    "✈️ *Flynow — Buscador de Vuelos*\n\n"
    "Hablame como si le hablaras a un amigo. Entiendo texto libre y audios 🎙️\n\n"
    "*Ejemplos:*\n"
    "• _\"quiero ir a Barcelona en julio, una semana\"_\n"
    "• _\"vuelos baratos de mendoza a miami en junio\"_\n"
    "• _\"fechas baratas mdz eze\"_\n\n"
    "*Comandos directos:*\n"
    "• /vuelos `MDZ EZE 2026-04-15` — vuelos en fecha específica\n"
    "• /fechas `MDZ BCN 90 7` — fechas baratas (90 días, 7 noches)\n\n"
    "💡 *Tip:* Si no sabés el código del aeropuerto, escribí el nombre de la ciudad nomás."
)


def find_fli():
    fli = shutil.which("fli")
    if fli:
        return [fli]
    for candidate in ["/opt/venv/bin/fli", os.path.expanduser("~/.local/bin/fli")]:
        if os.path.isfile(candidate):
            return [candidate]
    return [sys.executable, "-m", "fli"]


def run_fli_json(args: list, timeout=60) -> dict | None:
    try:
        result = subprocess.run(
            find_fli() + args + ["--format", "json"],
            capture_output=True, text=True, timeout=timeout,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
        return json.loads(result.stdout)
    except Exception:
        return None


def run_fli_text(args: list, timeout=60) -> str:
    try:
        result = subprocess.run(
            find_fli() + args,
            capture_output=True, text=True, timeout=timeout,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
        raw = result.stdout or result.stderr
        return re.sub(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])', '', raw).strip()
    except subprocess.TimeoutExpired:
        return "⏱ La búsqueda tardó demasiado. Intentá con un rango más corto."
    except Exception as e:
        return f"❌ Error: {e}"


def google_flights_url(origin, dest, date, return_date=None):
    tt = "r" if return_date else "o"
    url = f"https://www.google.com/flights#search;f={origin};t={dest};d={date};tt={tt}"
    if return_date:
        url += f";r={return_date}"
    return url


def fmt_time(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso).strftime("%H:%M")
    except Exception:
        return iso


def fmt_duration(minutes: int) -> str:
    h, m = divmod(minutes, 60)
    return f"{h}h {m:02d}m" if h else f"{m}m"


def fmt_price(price: float) -> str:
    return f"${price:,.0f}".replace(",", ".")


def format_flights(data: dict, return_date: str = None) -> str:
    flights = data.get("flights", [])
    if not flights:
        return "No se encontraron vuelos."

    origin = data["query"]["origin"]
    dest = data["query"]["destination"]
    dep_date = data["query"]["departure_date"]

    lines = []
    for i, f in enumerate(flights[:5], 1):
        price = fmt_price(f["price"])
        duration = fmt_duration(f["duration"])
        stops = "✈️ Directo" if f["stops"] == 0 else f"🔄 {f['stops']} escala{'s' if f['stops'] > 1 else ''}"

        # Airline(s) — may be multiple legs
        airlines = []
        segments = []
        for leg in f.get("legs", []):
            airline = leg.get("airline", {}).get("name", "")
            if airline and airline not in airlines:
                airlines.append(airline)
            dep = fmt_time(leg.get("departure_time", ""))
            arr = fmt_time(leg.get("arrival_time", ""))
            orig = leg["departure_airport"]["code"]
            dst = leg["arrival_airport"]["code"]
            fn = leg.get("flight_number", "")
            segments.append(f"{orig} {dep} → {dst} {arr}" + (f" ({fn})" if fn else ""))

        link = google_flights_url(origin, dest, dep_date, return_date)
        airline_str = " / ".join(airlines) if airlines else "—"

        lines.append(
            f"*{i}. {price}* — {duration} — {stops}\n"
            f"🏢 {airline_str}\n"
            f"🕐 {chr(10).join(segments)}\n"
            f"[🔗 Ver en Google Flights]({link})"
        )

    return "\n\n".join(lines)


DIAS_ES = {
    "Monday": "Lunes", "Tuesday": "Martes", "Wednesday": "Miércoles",
    "Thursday": "Jueves", "Friday": "Viernes", "Saturday": "Sábado", "Sunday": "Domingo",
}
MESES_ES = {
    "01": "ene", "02": "feb", "03": "mar", "04": "abr", "05": "may", "06": "jun",
    "07": "jul", "08": "ago", "09": "sep", "10": "oct", "11": "nov", "12": "dic",
}


def fmt_date_es(iso: str) -> str:
    """2026-04-16 → 16 abr"""
    try:
        parts = iso.split("-")
        return f"{int(parts[2])} {MESES_ES[parts[1]]}"
    except Exception:
        return iso


def format_dates_table(raw: str, origen: str, destino: str, duracion: int) -> str:
    """Parse the raw table and return top 10 as clean human-readable Telegram text."""
    rows = []
    for line in raw.splitlines():
        # Match table data rows: │ 2026-04-16 │ Thursday │ 2026-04-19 │ Sunday │ $1,160.00 │
        m = re.match(r'\s*[│|]\s*(\d{4}-\d{2}-\d{2})\s*[│|]\s*(\w+)\s*[│|]\s*(\d{4}-\d{2}-\d{2})\s*[│|]\s*(\w+)\s*[│|]\s*\$?([\d,\.]+)', line)
        if m:
            dep, dep_day, ret, ret_day, price_raw = m.groups()
            price = float(price_raw.replace(",", ""))
            rows.append((dep, dep_day, ret, ret_day, price))

    if not rows:
        return raw  # fallback

    rows.sort(key=lambda x: x[4])
    top = rows[:10]

    link_base = google_flights_url(origen, destino, top[0][0], top[0][2])
    lines = [f"🏆 *Top {len(top)} fechas más baratas* ({duracion} noches, ida y vuelta)\n"]
    for i, (dep, dep_day, ret, ret_day, price) in enumerate(top, 1):
        emoji = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
        dep_es = DIAS_ES.get(dep_day, dep_day)
        ret_es = DIAS_ES.get(ret_day, ret_day)
        lines.append(
            f"{emoji} *${price:,.0f}* — {fmt_date_es(dep)} ({dep_es}) → {fmt_date_es(ret)} ({ret_es})"
        )

    lines.append(f"\n[🔗 Ver todos en Google Flights]({link_base})")
    return "\n".join(lines)


def resolve_iata(word: str) -> str | None:
    return CIUDAD_A_IATA.get(word.lower().strip())


def find_city_in_text(text_lower: str) -> list:
    """Return list of IATA codes in order of appearance in text."""
    # Build a list of (position, iata) by scanning for city names and codes
    matches = []

    # 3-letter codes (by word position)
    for i, word in enumerate(text_lower.split()):
        clean = re.sub(r'[^a-z]', '', word)
        code = CIUDAD_A_IATA.get(clean.upper().lower()) or (clean.upper() if clean.upper() in CIUDAD_A_IATA.values() else None)
        if code:
            pos = text_lower.find(clean)
            if not any(pos == m[0] for m in matches):
                matches.append((pos, code))

    # Multi-word city names
    for city, code in sorted(CIUDAD_A_IATA.items(), key=lambda x: -len(x[0])):
        idx = text_lower.find(city)
        if idx >= 0 and not any(code == m[1] for m in matches):
            matches.append((idx, code))

    matches.sort(key=lambda x: x[0])
    return [code for _, code in matches]


def parse_natural(text: str) -> dict | None:
    text_lower = text.lower()

    # Try "de [origin] a [dest]" pattern first
    patron = re.search(
        r'(?:de|desde)\s+(.+?)\s+(?:a|hasta|para|hacia)\s+(.+?)(?:\s+en\s+|\s+para\s+|\s*$)',
        text_lower
    )
    if patron:
        orig_str = patron.group(1).strip()
        dest_str = patron.group(2).strip()
        orig_code = next((CIUDAD_A_IATA[c] for c in sorted(CIUDAD_A_IATA, key=len, reverse=True) if c in orig_str), None)
        dest_code = next((CIUDAD_A_IATA[c] for c in sorted(CIUDAD_A_IATA, key=len, reverse=True) if c in dest_str), None)
        if orig_code and dest_code:
            found_iata = [orig_code, dest_code]
        else:
            found_iata = find_city_in_text(text_lower)
    else:
        found_iata = find_city_in_text(text_lower)

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
        val = int(match.group(1))
        duracion = val * 7 if "semana" in match.group(2) else val

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
        r = requests.get(file_url, timeout=30)
        tmp = f"/tmp/voice_{file_id}.ogg"
        with open(tmp, "wb") as f:
            f.write(r.content)
        return tmp
    except Exception:
        return None


# ── Actions ──────────────────────────────────────────────────────────────────

def do_vuelos(chat_id, reply_to_id, origen, destino, fecha_ida, fecha_vuelta=None):
    args = ["flights", origen, destino, fecha_ida]
    if fecha_vuelta:
        args += ["--return", fecha_vuelta]
    args += ["--sort", "CHEAPEST"]

    msg = bot.send_message(chat_id, f"🔍 Buscando vuelos {origen} → {destino}...",
                           reply_to_message_id=reply_to_id)
    data = run_fli_json(args)
    if not data or not data.get("success"):
        bot.edit_message_text("❌ No pude obtener resultados.", chat_id, msg.message_id)
        return

    label = fecha_ida + (f" ↔ {fecha_vuelta}" if fecha_vuelta else "")
    header = f"✈️ *{origen} → {destino}* — {label}\n\n"
    body = format_flights(data, fecha_vuelta)

    bot.edit_message_text(
        header + body,
        chat_id=chat_id, message_id=msg.message_id,
        parse_mode="Markdown", disable_web_page_preview=True,
    )


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

    msg = bot.send_message(chat_id, f"🔍 Buscando fechas baratas {origen} → {destino} ({rango_txt})...",
                           reply_to_message_id=reply_to_id)

    raw = run_fli_text(["dates", origen, destino, "--from", desde, "--to", hasta,
                        "--duration", str(duracion), "--round", "--sort"])
    table = format_dates_table(raw, origen, destino, duracion)

    bot.edit_message_text(
        f"📅 *{origen} → {destino}* — {rango_txt}\n\n{table}",
        chat_id=chat_id, message_id=msg.message_id,
        parse_mode="Markdown", disable_web_page_preview=True,
    )


def process_text(chat_id, message_id, text):
    # Detect greetings
    normalized = text.lower().strip().rstrip("!").rstrip("?")
    if normalized in SALUDOS:
        import random
        bot.send_message(chat_id, random.choice(RESPUESTAS_SALUDO),
                         reply_to_message_id=message_id, parse_mode="Markdown")
        return

    parsed = parse_natural(text)
    if parsed:
        do_fechas(chat_id, message_id, parsed["origen"], parsed["destino"],
                  mes=parsed.get("mes"), duracion=parsed.get("duracion", 3))
    else:
        bot.send_message(
            chat_id,
            "Mmm, no logré identificar la ruta 🤔\n\n"
            "Intentá con algo como:\n"
            "✈️ _\"mendoza a barcelona en mayo\"_\n"
            "✈️ _\"mdz miami junio 7 días\"_\n"
            "✈️ _\"quiero ir a Madrid\"_\n\n"
            "¿Me podés contar a dónde querés ir? 😊",
            reply_to_message_id=message_id, parse_mode="Markdown",
        )


# ── Handlers ─────────────────────────────────────────────────────────────────

@bot.message_handler(commands=["start"])
def cmd_start(message):
    nombre = message.from_user.first_name or "viajero"
    bot.send_message(
        message.chat.id,
        f"¡Hola, {nombre}! 👋 Soy *Flynow*, tu asistente para encontrar vuelos baratos. ✈️\n\n"
        f"Puedo buscar precios en Google Flights por vos. Solo contame:\n\n"
        f"🌍 *¿A dónde querés ir?*\n"
        f"📅 *¿Cuándo más o menos?*\n"
        f"🕐 *¿Cuántos días?*\n\n"
        f"Por ejemplo:\n"
        f"_\"quiero ir a Barcelona en julio, una semana\"_\n"
        f"_\"fechas baratas de Mendoza a Miami\"_\n\n"
        f"También podés mandarme un 🎙️ *audio* y te entiendo igual. ¡Empecemos! 😊",
        parse_mode="Markdown",
    )


@bot.message_handler(commands=["help", "ayuda"])
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
    raw = run_fli_text(["dates", origen, destino, "--from", desde, "--to", hasta,
                        "--duration", str(duracion), "--round", "--sort"])
    table = format_dates_table(raw, origen, destino, duracion)
    bot.edit_message_text(
        f"📅 *{origen} → {destino}* — próximos {dias} días\n\n{table}",
        chat_id=message.chat.id, message_id=msg.message_id,
        parse_mode="Markdown", disable_web_page_preview=True,
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
    bot.edit_message_text(f"🎙️ _{text}_\n\n🔍 Buscando...", message.chat.id, msg.message_id,
                          parse_mode="Markdown")
    process_text(message.chat.id, message.message_id, text)


@bot.message_handler(content_types=["text"])
def handle_text(message):
    process_text(message.chat.id, message.message_id, message.text)


if __name__ == "__main__":
    print("Bot iniciado...")
    bot.infinity_polling()
