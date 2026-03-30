import json
import os
import random
import re
import shutil
import subprocess
import sys
from datetime import datetime, timedelta
import telebot
import requests

TOKEN = os.environ["BOT_TOKEN"]
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")

# Estado conversacional por usuario { chat_id: { step, destino, origen, mes, duracion } }
user_states: dict = {}

bot = telebot.TeleBot(TOKEN)

# ── Datos ─────────────────────────────────────────────────────────────────────

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
    "punta cana": "PUJ", "puj": "PUJ",
    "maldivas": "MLE", "mle": "MLE",
    "tokio": "HND", "haneda": "HND",
    "sydney": "SYD", "syd": "SYD",
    "zurich": "ZRH", "zúrich": "ZRH", "zrh": "ZRH",
    "milan": "MXP", "milán": "MXP", "mxp": "MXP",
}

MESES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4,
    "mayo": 5, "junio": 6, "julio": 7, "agosto": 8,
    "septiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
}

DIAS_ES = {
    "Monday": "Lunes", "Tuesday": "Martes", "Wednesday": "Miércoles",
    "Thursday": "Jueves", "Friday": "Viernes", "Saturday": "Sábado", "Sunday": "Domingo",
}
MESES_ES = {
    "01": "ene", "02": "feb", "03": "mar", "04": "abr", "05": "may", "06": "jun",
    "07": "jul", "08": "ago", "09": "sep", "10": "oct", "11": "nov", "12": "dic",
}

# ── Copy / Voz del bot ────────────────────────────────────────────────────────

SALUDOS = {
    "hola", "buenas", "hey", "hi", "buen dia", "buen día", "buenas tardes",
    "buenas noches", "buenos dias", "buenos días", "ola", "holaa", "holis",
    "hello", "que tal", "qué tal", "como estas", "cómo estás", "buenas!",
}

AGRADECIMIENTOS = {
    "gracias", "gracias!", "muchas gracias", "grax", "genial", "perfecto",
    "ok gracias", "excelente", "buenisimo", "buenísimo", "re bien", "copado",
}

RESPUESTAS_SALUDO = [
    "¡Hola! 👋 Soy *Flynow*, tu asistente para encontrar vuelos baratos.\n\n"
    "Contame a dónde querés ir y yo me encargo de buscar los mejores precios 🔍\n\n"
    "Por ejemplo podés decirme:\n"
    "✈️ _\"quiero ir a Barcelona en julio\"_\n"
    "✈️ _\"fechas baratas de Mendoza a Miami\"_\n"
    "✈️ _\"mendoza madrid una semana\"_\n\n"
    "También entiendo audios 🎙️ ¡hablame nomás!\n\n"
    "¿A dónde soñás viajar? 🌍",

    "¡Buenas! ✈️ Soy *Flynow*.\n\n"
    "Puedo buscar vuelos baratos en Google Flights por vos.\n\n"
    "Solo contame el plan:\n"
    "🗓️ _\"mendoza a ezeiza, cualquier fecha de mayo\"_\n"
    "🗓️ _\"vuelos baratos a Roma en agosto, 10 días\"_\n\n"
    "¿Adónde querés ir? 😊",

    "¡Hey! Soy *Flynow* 🛫\n\n"
    "Mi trabajo es conseguirte los precios más baratos. Solo decime destino y mes aproximado y me pongo a buscar.\n\n"
    "Ejemplo: _\"quiero ir a Madrid en octubre, una semana\"_\n\n"
    "¿Cuál es tu próximo destino? 🌎",
]

RESPUESTAS_GRACIAS = [
    "¡Con gusto! 😊 Si querés buscar otro destino, avisame.",
    "¡Para eso estoy! ✈️ ¿Hay algo más que quieras explorar?",
    "¡De nada! Si encontrás algo que te guste, no dejes de reservar 🎉",
]

MENSAJES_BUSCANDO = [
    "Un momento, estoy consultando Google Flights... 🔍",
    "Buscando los mejores precios para vos... ✈️",
    "Revisando todas las opciones disponibles... 🗓️",
    "Dame un segundo que esto tarda un poquito... 🔎",
]

MENSAJES_BUSCANDO_VUELO = [
    "Buscando vuelos disponibles... ✈️",
    "Consultando Google Flights para esa fecha... 🔍",
    "Un momento, revisando opciones... 🗓️",
]


# ── Utilidades ────────────────────────────────────────────────────────────────

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
        return "__timeout__"
    except Exception:
        return "__error__"


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


def fmt_date_es(iso: str) -> str:
    try:
        p = iso.split("-")
        return f"{int(p[2])} {MESES_ES[p[1]]}"
    except Exception:
        return iso


# ── Formatters ────────────────────────────────────────────────────────────────

def format_flights(data: dict, return_date: str = None) -> str:
    flights = data.get("flights", [])
    if not flights:
        return (
            "No encontré vuelos para esa ruta y fecha 😕\n\n"
            "Podés intentar con fechas cercanas o con /fechas para ver qué días son más baratos."
        )

    origin = data["query"]["origin"]
    dest = data["query"]["destination"]
    dep_date = data["query"]["departure_date"]

    lines = []
    for i, f in enumerate(flights[:5], 1):
        price = fmt_price(f["price"])
        duration = fmt_duration(f["duration"])
        stops = "Directo" if f["stops"] == 0 else f"{f['stops']} escala{'s' if f['stops'] > 1 else ''}"

        airlines, segments = [], []
        for leg in f.get("legs", []):
            name = leg.get("airline", {}).get("name", "")
            if name and name not in airlines:
                airlines.append(name)
            dep = fmt_time(leg.get("departure_time", ""))
            arr = fmt_time(leg.get("arrival_time", ""))
            orig = leg["departure_airport"]["code"]
            dst = leg["arrival_airport"]["code"]
            fn = leg.get("flight_number", "")
            segments.append(f"{orig} {dep} → {dst} {arr}" + (f"  _#{fn}_" if fn else ""))

        link = google_flights_url(origin, dest, dep_date, return_date)
        airline_str = " / ".join(airlines) or "—"
        stop_icon = "🟢" if f["stops"] == 0 else "🟡"

        lines.append(
            f"{stop_icon} *{price}* — {duration} — {stops}\n"
            f"✈️ {airline_str}\n"
            + "\n".join(f"   {s}" for s in segments) +
            f"\n[Ver y comprar en Google Flights →]({link})"
        )

    footer = f"\n💡 _Precios orientativos de Google Flights. Pueden variar al momento de comprar._"
    return "\n\n".join(lines) + footer


def format_dates_table(raw: str, origen: str, destino: str, duracion: int) -> str:
    rows = []
    for line in raw.splitlines():
        m = re.match(
            r'\s*[│|╭╰├]\s*(\d{4}-\d{2}-\d{2})\s*[│|]\s*(\w+)\s*[│|]\s*(\d{4}-\d{2}-\d{2})\s*[│|]\s*(\w+)\s*[│|]\s*\$?([\d,\.]+)',
            line
        )
        if m:
            dep, dep_day, ret, ret_day, price_raw = m.groups()
            price = float(price_raw.replace(",", ""))
            rows.append((dep, dep_day, ret, ret_day, price))

    if not rows:
        return "No encontré fechas disponibles para esa ruta 😕\nProbá con un rango de fechas más amplio."

    rows.sort(key=lambda x: x[4])
    top = rows[:10]
    cheapest = top[0]
    dur_txt = f"{duracion} noche{'s' if duracion != 1 else ''}"

    lines = [f"Estas son las *{len(top)} fechas más baratas* para ir y volver ({dur_txt}):\n"]

    for i, (dep, dep_day, ret, ret_day, price) in enumerate(top, 1):
        medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"  {i}."
        dep_es = DIAS_ES.get(dep_day, dep_day)
        ret_es = DIAS_ES.get(ret_day, ret_day)
        # Link individual por fecha
        link = google_flights_url(origen, destino, dep, ret)
        lines.append(
            f"{medal} *{fmt_price(price)}* — {fmt_date_es(dep)} ({dep_es}) → {fmt_date_es(ret)} ({ret_es})\n"
            f"   [Comprar este vuelo →]({link})"
        )

    savings = top[-1][4] - top[0][4]
    if savings > 0:
        lines.append(
            f"\n💰 Saliendo el {fmt_date_es(cheapest[0])} ahorrás hasta *{fmt_price(savings)}* "
            f"vs la opción más cara del listado."
        )

    lines.append(f"\n💡 _¿Querés ver los vuelos de una fecha en particular? Decime cuál._")
    return "\n".join(lines)


# ── NLP ───────────────────────────────────────────────────────────────────────

def resolve_iata(word: str) -> str | None:
    return CIUDAD_A_IATA.get(word.lower().strip())


def find_cities_in_order(text_lower: str) -> list:
    matches = []

    for word in text_lower.split():
        clean = re.sub(r'[^a-z]', '', word)
        code = CIUDAD_A_IATA.get(clean) or CIUDAD_A_IATA.get(clean.upper().lower())
        if not code and clean.upper() in CIUDAD_A_IATA.values():
            code = clean.upper()
        if code:
            pos = text_lower.find(clean)
            if not any(pos == m[0] for m in matches):
                matches.append((pos, code))

    for city, code in sorted(CIUDAD_A_IATA.items(), key=lambda x: -len(x[0])):
        idx = text_lower.find(city)
        if idx >= 0 and not any(code == m[1] for m in matches):
            matches.append((idx, code))

    matches.sort(key=lambda x: x[0])
    return [code for _, code in matches]


def parse_natural(text: str) -> dict | None:
    text_lower = text.lower()

    # "de X a Y" / "desde X hacia Y"
    patron = re.search(
        r'(?:de|desde)\s+(.+?)\s+(?:a|hasta|para|hacia)\s+(.+?)(?:\s+en\s+|\s+para\s+|\s+el\s+|\s*$)',
        text_lower
    )
    if patron:
        orig_str, dest_str = patron.group(1).strip(), patron.group(2).strip()
        orig_code = next((CIUDAD_A_IATA[c] for c in sorted(CIUDAD_A_IATA, key=len, reverse=True) if c in orig_str), None)
        dest_code = next((CIUDAD_A_IATA[c] for c in sorted(CIUDAD_A_IATA, key=len, reverse=True) if c in dest_str), None)
        found_iata = [orig_code, dest_code] if orig_code and dest_code else find_cities_in_order(text_lower)
    else:
        found_iata = find_cities_in_order(text_lower)

    if len(found_iata) < 2:
        return None

    # Mes
    mes = None
    for nombre, num in MESES.items():
        if nombre in text_lower:
            mes = num
            break

    # Duración
    duracion = 3
    m_dur = re.search(r'(\d+)\s*(día|dias|noches|noche|nights?|days?)', text_lower)
    if m_dur:
        duracion = int(m_dur.group(1))
    elif re.search(r'\buna\s+semana\b|\bla\s+semana\b|\bsemana\b', text_lower):
        duracion = 7
    elif re.search(r'\bdos\s+semanas\b|\b2\s+semanas\b', text_lower):
        duracion = 14
    elif re.search(r'\bfinde\b|\bfin\s+de\s+semana\b', text_lower):
        duracion = 2

    # Solo ida
    solo_ida = bool(re.search(r'\bsolo\s+ida\b|\bsin\s+vuelta\b|\bida\s+sola\b', text_lower))

    return {
        "origen": found_iata[0],
        "destino": found_iata[1],
        "mes": mes,
        "duracion": duracion,
        "solo_ida": solo_ida,
    }


# ── Transcripción ─────────────────────────────────────────────────────────────

def transcribe_audio(file_path: str) -> str | None:
    if not GROQ_API_KEY:
        return None
    try:
        with open(file_path, "rb") as f:
            r = requests.post(
                "https://api.groq.com/openai/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
                files={"file": (os.path.basename(file_path), f, "audio/ogg")},
                data={"model": "whisper-large-v3", "language": "es"},
                timeout=30,
            )
        if r.status_code == 200:
            return r.json().get("text", "").strip()
    except Exception:
        pass
    return None


def download_voice(file_id: str) -> str | None:
    try:
        info = bot.get_file(file_id)
        url = f"https://api.telegram.org/file/bot{TOKEN}/{info.file_path}"
        r = requests.get(url, timeout=30)
        path = f"/tmp/voice_{file_id}.ogg"
        with open(path, "wb") as f:
            f.write(r.content)
        return path
    except Exception:
        return None


# ── Acciones ──────────────────────────────────────────────────────────────────

def do_vuelos(chat_id, reply_to_id, origen, destino, fecha_ida, fecha_vuelta=None, edit_msg_id=None):
    args = ["flights", origen, destino, fecha_ida]
    if fecha_vuelta:
        args += ["--return", fecha_vuelta]
    args += ["--sort", "CHEAPEST"]

    if edit_msg_id:
        bot.edit_message_text(random.choice(MENSAJES_BUSCANDO_VUELO), chat_id, edit_msg_id)
        msg_id = edit_msg_id
    else:
        m = bot.send_message(chat_id, random.choice(MENSAJES_BUSCANDO_VUELO),
                             reply_to_message_id=reply_to_id)
        msg_id = m.message_id

    data = run_fli_json(args)

    if not data or not data.get("success"):
        bot.edit_message_text(
            "Ups, no pude conectarme con Google Flights en este momento 😕\n"
            "Intentá de nuevo en unos segundos.",
            chat_id, msg_id
        )
        return

    label = fmt_date_es(fecha_ida) + (f" → {fmt_date_es(fecha_vuelta)}" if fecha_vuelta else " (solo ida)")
    header = f"✈️ *{origen} → {destino}* — {label}\n\n"
    body = format_flights(data, fecha_vuelta)

    bot.edit_message_text(
        header + body,
        chat_id=chat_id, message_id=msg_id,
        parse_mode="Markdown", disable_web_page_preview=True,
    )


def do_fechas(chat_id, reply_to_id, origen, destino, mes=None, duracion=3, edit_msg_id=None):
    if mes:
        year = datetime.today().year
        now = datetime.today()
        if mes < now.month or (mes == now.month and now.day > 20):
            year += 1
        desde = datetime(year, mes, 1).strftime("%Y-%m-%d")
        hasta_dt = (datetime(year + 1, 1, 1) - timedelta(days=1)) if mes == 12 \
            else (datetime(year, mes + 1, 1) - timedelta(days=1))
        hasta = hasta_dt.strftime("%Y-%m-%d")
        rango_txt = list(MESES.keys())[mes - 1].capitalize()
    else:
        desde = datetime.today().strftime("%Y-%m-%d")
        hasta = (datetime.today() + timedelta(days=60)).strftime("%Y-%m-%d")
        rango_txt = "los próximos 60 días"

    loading = f"{random.choice(MENSAJES_BUSCANDO)}"
    if edit_msg_id:
        bot.edit_message_text(loading, chat_id, edit_msg_id)
        msg_id = edit_msg_id
    else:
        m = bot.send_message(chat_id, loading, reply_to_message_id=reply_to_id)
        msg_id = m.message_id

    raw = run_fli_text(["dates", origen, destino, "--from", desde, "--to", hasta,
                        "--duration", str(duracion), "--round", "--sort"])

    if raw == "__timeout__":
        bot.edit_message_text(
            "La búsqueda tardó demasiado 😕 Probá con un rango de fechas más corto.",
            chat_id, msg_id
        )
        return
    if raw == "__error__":
        bot.edit_message_text(
            "Ups, algo salió mal al conectarme con Google Flights 😕 Intentá de nuevo en un momento.",
            chat_id, msg_id
        )
        return

    table = format_dates_table(raw, origen, destino, duracion)
    header = f"📅 *{origen} → {destino}* — {rango_txt}\n\n"

    bot.edit_message_text(
        header + table,
        chat_id=chat_id, message_id=msg_id,
        parse_mode="Markdown", disable_web_page_preview=True,
    )


# ── Procesamiento central ─────────────────────────────────────────────────────

def send_or_edit(chat_id, message_id, text, edit_msg_id=None, **kwargs):
    if edit_msg_id:
        bot.edit_message_text(text, chat_id, edit_msg_id, **kwargs)
    else:
        bot.send_message(chat_id, text, reply_to_message_id=message_id, **kwargs)


def find_single_city(text_lower: str) -> str | None:
    """Detecta si el texto menciona exactamente una ciudad conocida."""
    found = find_cities_in_order(text_lower)
    return found[0] if len(found) == 1 else None


def process_text(chat_id, message_id, text, edit_msg_id=None):
    normalized = text.lower().strip().rstrip("!").rstrip("?").rstrip(".")

    if normalized in SALUDOS:
        bot.send_message(chat_id, random.choice(RESPUESTAS_SALUDO),
                         reply_to_message_id=message_id, parse_mode="Markdown")
        return

    if normalized in AGRADECIMIENTOS:
        bot.send_message(chat_id, random.choice(RESPUESTAS_GRACIAS),
                         reply_to_message_id=message_id, parse_mode="Markdown")
        return

    # ── Flujo conversacional pendiente ──────────────────────────────────────
    state = user_states.get(chat_id)

    if state:
        step = state.get("step")

        if step == "ask_origen":
            # El usuario responde con su ciudad de origen
            origen = find_single_city(normalized) or resolve_iata(normalized.upper())
            if not origen:
                # Intentar como código directo
                code = normalized.upper().strip()
                if len(code) == 3 and code.isalpha():
                    origen = code
            if origen:
                user_states.pop(chat_id, None)
                do_fechas(chat_id, message_id, origen, state["destino"],
                          mes=state.get("mes"), duracion=state.get("duracion", 3),
                          edit_msg_id=edit_msg_id)
            else:
                send_or_edit(
                    chat_id, message_id,
                    "No reconocí esa ciudad 😅 ¿Podés escribirla diferente o usar el código? "
                    "Por ejemplo: _Mendoza_ o _MDZ_",
                    edit_msg_id=edit_msg_id, parse_mode="Markdown"
                )
            return

        if step == "ask_destino":
            destino = find_single_city(normalized) or resolve_iata(normalized.upper())
            if not destino:
                code = normalized.upper().strip()
                if len(code) == 3 and code.isalpha():
                    destino = code
            if destino:
                user_states.pop(chat_id, None)
                do_fechas(chat_id, message_id, state["origen"], destino,
                          mes=state.get("mes"), duracion=state.get("duracion", 3),
                          edit_msg_id=edit_msg_id)
            else:
                send_or_edit(
                    chat_id, message_id,
                    "No reconocí ese destino 😅 ¿Lo podés escribir diferente? "
                    "Por ejemplo: _Barcelona_ o _BCN_",
                    edit_msg_id=edit_msg_id, parse_mode="Markdown"
                )
            return

    # ── Parseo normal ────────────────────────────────────────────────────────
    parsed = parse_natural(text)

    if parsed:
        do_fechas(
            chat_id, message_id,
            parsed["origen"], parsed["destino"],
            mes=parsed.get("mes"),
            duracion=parsed.get("duracion", 3),
            edit_msg_id=edit_msg_id,
        )
        return

    # ── Solo detecté un destino → preguntar origen ──────────────────────────
    single = find_single_city(text.lower())
    if single:
        user_states[chat_id] = {
            "step": "ask_origen",
            "destino": single,
            "mes": next((num for nombre, num in MESES.items() if nombre in text.lower()), None),
            "duracion": 7 if "semana" in text.lower() else 3,
        }
        send_or_edit(
            chat_id, message_id,
            f"¡Buena elección, *{single}* es un destino genial! 😍\n\n"
            f"¿Desde qué ciudad salís?",
            edit_msg_id=edit_msg_id, parse_mode="Markdown"
        )
        return

    # ── No entendí nada ──────────────────────────────────────────────────────
    send_or_edit(
        chat_id, message_id,
        "Hmm, no pude identificar la ruta 🤔\n\n"
        "Contame a dónde querés ir, por ejemplo:\n"
        "✈️ _\"quiero ir a Barcelona en mayo\"_\n"
        "✈️ _\"mendoza a miami, una semana\"_\n"
        "✈️ _\"mdz eze\"_\n\n"
        "¿A dónde tenés ganas de volar? 😊",
        edit_msg_id=edit_msg_id, parse_mode="Markdown"
    )


# ── Handlers ──────────────────────────────────────────────────────────────────

@bot.message_handler(commands=["start"])
def cmd_start(message):
    nombre = message.from_user.first_name or "viajero"
    bot.send_message(
        message.chat.id,
        f"¡Hola, {nombre}! 👋 Soy *Flynow*, tu asistente para encontrar vuelos baratos. ✈️\n\n"
        f"Busco precios en Google Flights para que vos elijas el mejor momento para volar.\n\n"
        f"Solo contame:\n"
        f"• ¿A dónde querés ir?\n"
        f"• ¿Más o menos en qué época?\n"
        f"• ¿Cuántos días?\n\n"
        f"Ejemplo: _\"quiero ir a Barcelona en julio, una semana\"_\n\n"
        f"También podés mandarme un 🎙️ *audio* si preferís hablar.\n\n"
        f"¿A dónde soñás viajar? 🌍",
        parse_mode="Markdown",
    )


@bot.message_handler(commands=["help", "ayuda"])
def cmd_help(message):
    bot.send_message(
        message.chat.id,
        "✈️ *¿Cómo usar Flynow?*\n\n"
        "Lo más fácil es escribirme en lenguaje natural o mandarme un 🎙️ audio:\n\n"
        "• _\"mendoza a barcelona en mayo, 7 días\"_\n"
        "• _\"vuelos baratos a Miami en junio\"_\n"
        "• _\"quiero ir a Madrid, una semana\"_\n"
        "• _\"mdz eze\"_ (código IATA directo)\n\n"
        "Si querés una fecha específica:\n"
        "• /vuelos `MDZ EZE 2026-04-15`\n"
        "• /vuelos `MDZ EZE 2026-04-15 2026-04-20` _(ida y vuelta)_\n\n"
        "💡 No necesitás saber los códigos de aeropuerto — escribí el nombre de la ciudad nomás.",
        parse_mode="Markdown",
    )


@bot.message_handler(commands=["vuelos"])
def cmd_vuelos(message):
    parts = message.text.split()[1:]
    if len(parts) < 3:
        bot.reply_to(
            message,
            "Para buscar vuelos en una fecha específica necesito:\n"
            "`/vuelos ORIGEN DESTINO FECHA`\n\n"
            "Ejemplo: `/vuelos MDZ EZE 2026-04-15`\n\n"
            "O si preferís, escribime directamente: _\"vuelos de mendoza a ezeiza el 15 de abril\"_ 😊",
            parse_mode="Markdown"
        )
        return
    origen = resolve_iata(parts[0]) or parts[0].upper()
    destino = resolve_iata(parts[1]) or parts[1].upper()
    do_vuelos(message.chat.id, message.message_id, origen, destino, parts[2],
              parts[3] if len(parts) >= 4 else None)


@bot.message_handler(commands=["fechas"])
def cmd_fechas(message):
    parts = message.text.split()[1:]
    if len(parts) < 2:
        bot.reply_to(
            message,
            "Para buscar fechas baratas necesito al menos origen y destino:\n"
            "`/fechas ORIGEN DESTINO`\n\n"
            "Ejemplo: `/fechas MDZ BCN`\n\n"
            "O simplemente escribime: _\"fechas baratas de mendoza a barcelona\"_ 😊",
            parse_mode="Markdown"
        )
        return
    origen = resolve_iata(parts[0]) or parts[0].upper()
    destino = resolve_iata(parts[1]) or parts[1].upper()
    dias = int(parts[2]) if len(parts) >= 3 else 60
    duracion = int(parts[3]) if len(parts) >= 4 else 3
    desde = datetime.today().strftime("%Y-%m-%d")
    hasta = (datetime.today() + timedelta(days=dias)).strftime("%Y-%m-%d")
    msg = bot.reply_to(message, random.choice(MENSAJES_BUSCANDO))
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
        bot.reply_to(
            message,
            "Los audios todavía no están activados 🎙️\n"
            "Pero podés escribirme lo mismo con texto y te ayudo igual 😊"
        )
        return

    msg = bot.reply_to(message, "🎙️ Escuchando tu audio...")
    path = download_voice(message.voice.file_id)

    if not path:
        bot.edit_message_text(
            "No pude procesar el audio 😕 ¿Podés escribirme lo mismo con texto?",
            message.chat.id, msg.message_id
        )
        return

    text = transcribe_audio(path)
    try:
        os.remove(path)
    except Exception:
        pass

    if not text:
        bot.edit_message_text(
            "No pude entender el audio 😕 ¿Podés escribirme lo mismo con texto?",
            message.chat.id, msg.message_id
        )
        return

    # Mostrar transcripción y buscar en el mismo mensaje
    bot.edit_message_text(
        f"🎙️ Escuché: _{text}_\n\n{random.choice(MENSAJES_BUSCANDO)}",
        message.chat.id, msg.message_id, parse_mode="Markdown"
    )
    process_text(message.chat.id, message.message_id, text, edit_msg_id=msg.message_id)


@bot.message_handler(content_types=["text"])
def handle_text(message):
    process_text(message.chat.id, message.message_id, message.text)


@bot.message_handler(content_types=["sticker", "photo", "video", "document", "location"])
def handle_other(message):
    bot.reply_to(
        message,
        "Solo entiendo texto y audios por ahora 😅\n"
        "Contame a dónde querés volar y te busco los precios 🌍"
    )


if __name__ == "__main__":
    print("Bot iniciado...")
    bot.infinity_polling()
