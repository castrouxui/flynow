import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timedelta
import telebot

TOKEN = os.environ["BOT_TOKEN"]
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
}

MESES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4,
    "mayo": 5, "junio": 6, "julio": 7, "agosto": 8,
    "septiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
}

HELP_TEXT = """
✈️ *Buscador de Vuelos*

Podés escribirme de forma natural:

_"vuelos de mendoza a barcelona en mayo"_
_"quiero ir a madrid desde mendoza, 7 días"_
_"fechas baratas mdz eze"_
_"mdz miami junio"_

O usar comandos:
*/vuelos* `MDZ EZE 2026-04-15`
*/fechas* `MDZ BCN 90 7`

Aeropuertos: `EZE` Ezeiza · `AEP` Aeroparque · `MDZ` Mendoza · `BCN` Barcelona · `MAD` Madrid · `MIA` Miami
"""


def strip_ansi(text):
    return re.sub(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])', '', text)


def find_fli():
    """Find the fli executable."""
    # Try fli in PATH first
    fli = shutil.which("fli")
    if fli:
        return [fli]
    # Try common venv locations
    for candidate in ["/opt/venv/bin/fli", os.path.expanduser("~/.local/bin/fli")]:
        if os.path.isfile(candidate):
            return [candidate]
    # Fall back to python -m fli
    return [sys.executable, "-m", "fli"]


def run_fli(args: list, timeout=60) -> str:
    try:
        cmd = find_fli() + args
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
        output = result.stdout or result.stderr
        return strip_ansi(output).strip()
    except subprocess.TimeoutExpired:
        return "⏱ La búsqueda tardó demasiado. Intentá con un rango más corto."
    except Exception as e:
        return f"❌ Error: {e}"


def format_output(raw: str) -> str:
    """Keep only the results table, drop the ASCII price chart."""
    lines = raw.splitlines()
    table_lines = []
    in_table = False
    for line in lines:
        if "Cheapest Dates" in line or "Flight Results" in line:
            in_table = True
        if in_table:
            table_lines.append(line)
    return "\n".join(table_lines) if table_lines else raw


def resolve_iata(word: str) -> str | None:
    return CIUDAD_A_IATA.get(word.lower().strip())


def parse_natural(text: str) -> dict | None:
    """
    Try to extract origen, destino, mes, duracion from free text.
    Returns dict with keys: origen, destino, mes (optional), duracion (optional)
    or None if can't parse.
    """
    text_lower = text.lower()

    # Find IATA codes or city names
    found_iata = []

    # Try explicit 3-letter uppercase codes first
    for word in text.split():
        clean = re.sub(r'[^a-zA-Z]', '', word).upper()
        if len(clean) == 3 and clean.isalpha():
            # Check if it resolves or looks like a valid code
            resolved = resolve_iata(clean.lower())
            if resolved:
                found_iata.append(resolved)
            elif clean in CIUDAD_A_IATA.values():
                found_iata.append(clean)

    # Try multi-word city names
    for city, code in sorted(CIUDAD_A_IATA.items(), key=lambda x: -len(x[0])):
        if city in text_lower and code not in found_iata:
            found_iata.append(code)

    if len(found_iata) < 2:
        return None

    origen, destino = found_iata[0], found_iata[1]

    # Find month
    mes = None
    for nombre, num in MESES.items():
        if nombre in text_lower:
            mes = num
            break

    # Find duration (número de días/noches)
    duracion = 3
    match = re.search(r'(\d+)\s*(día|noche|dias|noches|nights?|days?)', text_lower)
    if match:
        duracion = int(match.group(1))

    return {"origen": origen, "destino": destino, "mes": mes, "duracion": duracion}


def do_fechas(chat_id, reply_to_id, origen, destino, mes=None, duracion=3):
    if mes:
        year = datetime.today().year
        now = datetime.today()
        # If month already passed this year, use next year
        if mes < now.month:
            year += 1
        desde = datetime(year, mes, 1).strftime("%Y-%m-%d")
        # Last day of that month
        if mes == 12:
            hasta = datetime(year + 1, 1, 1) - timedelta(days=1)
        else:
            hasta = datetime(year, mes + 1, 1) - timedelta(days=1)
        hasta = hasta.strftime("%Y-%m-%d")
        rango_txt = f"en {list(MESES.keys())[mes-1].capitalize()}"
    else:
        desde = datetime.today().strftime("%Y-%m-%d")
        hasta = (datetime.today() + timedelta(days=60)).strftime("%Y-%m-%d")
        rango_txt = "próximos 60 días"

    msg = bot.send_message(chat_id, f"🔍 Buscando fechas baratas {origen} → {destino} ({rango_txt})...",
                           reply_to_message_id=reply_to_id)
    result = run_fli(["dates", origen, destino, "--from", desde, "--to", hasta,
                      "--duration", str(duracion), "--round", "--sort"])
    output = format_output(result)
    if not output:
        output = "No se encontraron resultados para esa ruta."

    bot.edit_message_text(
        f"📅 *{origen} → {destino}* — {rango_txt}, {duracion} noches\n\n```\n{output[:3800]}\n```",
        chat_id=chat_id,
        message_id=msg.message_id,
        parse_mode="Markdown",
    )


def do_vuelos(chat_id, reply_to_id, origen, destino, fecha_ida, fecha_vuelta=None):
    extra = ["--return", fecha_vuelta] if fecha_vuelta else []
    msg = bot.send_message(chat_id, f"🔍 Buscando vuelos {origen} → {destino}...",
                           reply_to_message_id=reply_to_id)
    result = run_fli(["flights", origen, destino, fecha_ida] + extra + ["--sort", "CHEAPEST"])
    output = format_output(result)
    if not output:
        output = "No se encontraron vuelos para esa ruta y fecha."

    label = f"{fecha_ida}" + (f" → {fecha_vuelta}" if fecha_vuelta else "")
    bot.edit_message_text(
        f"✈️ *{origen} → {destino}* — {label}\n\n```\n{output[:3800]}\n```",
        chat_id=chat_id,
        message_id=msg.message_id,
        parse_mode="Markdown",
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
    fecha_ida = parts[2]
    fecha_vuelta = parts[3] if len(parts) >= 4 else None
    do_vuelos(message.chat.id, message.message_id, origen, destino, fecha_ida, fecha_vuelta)


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
    output = format_output(result)
    if not output:
        output = "No se encontraron resultados."
    bot.edit_message_text(
        f"📅 *{origen} → {destino}* — próximos {dias} días, {duracion} noches\n\n```\n{output[:3800]}\n```",
        chat_id=message.chat.id, message_id=msg.message_id, parse_mode="Markdown",
    )


@bot.message_handler(content_types=["text"])
def handle_text(message):
    parsed = parse_natural(message.text)
    if parsed:
        do_fechas(
            message.chat.id, message.message_id,
            parsed["origen"], parsed["destino"],
            mes=parsed.get("mes"),
            duracion=parsed.get("duracion", 3),
        )
    else:
        bot.reply_to(
            message,
            "No entendí la ruta 🤔\n\nProbá con:\n_\"vuelos mendoza barcelona mayo\"_\n_\"mdz eze junio 7 días\"_\n\nO usá /help",
            parse_mode="Markdown",
        )


if __name__ == "__main__":
    print("Bot iniciado...")
    bot.infinity_polling()
