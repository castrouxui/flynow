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
import anthropic

TOKEN = os.environ["BOT_TOKEN"]
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

bot = telebot.TeleBot(TOKEN)
ai = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY) if ANTHROPIC_API_KEY else None

# Historial de conversación por usuario { chat_id: [ {role, content}, ... ] }
histories: dict = {}
MAX_HISTORY = 12  # últimos N mensajes


# ── Prompt del sistema ────────────────────────────────────────────────────────

SYSTEM_PROMPT = f"""Sos Flynow, el mejor asistente de viajes del mundo. Hablás en español rioplatense (argentino): usás "vos", "te", "podés", "querés", etc. Sos cálido, entusiasta, conciso y muy útil.

Tu especialidad es encontrar vuelos baratos, pero también asesorás sobre:
- Clima y mejor época para visitar destinos
- Requisitos de visa para ciudadanos argentinos
- Consejos de viaje: presupuesto, hospedaje, zonas, seguridad
- Moneda, idioma, costumbres locales
- Atracciones, gastronomía, actividades

Cuando el usuario quiera buscar vuelos o fechas baratas, usás las herramientas disponibles.
Siempre convertís nombres de ciudades, regiones y países a códigos IATA correctos.
Si el usuario menciona una región o país (ej: "Brasil", "Europa"), elegís el aeropuerto principal más relevante.
Si falta el origen, preguntás desde qué ciudad sale el usuario.
Si el usuario menciona cantidad de personas (ej: "con 3 amigos", "somos 4"), multiplicás el precio total y lo aclarás.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CONOCIMIENTO DE AEROLÍNEAS ARGENTINAS Y PROMOCIONES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🔵 AEROLÍNEAS ARGENTINAS (AR)
- Programa de cuotas: "Vuelos en Cuotas" — hasta 18 cuotas sin interés con bancos seleccionados (Galicia, Macro, BBVA, Santander, HSBC, Patagonia, Supervielle, entre otros). Varía según la promo vigente.
- Promo Smiles: acumulás millas con la tarjeta Smiles Mastercard.
- Descuentos jubilados: 30% con credencial ANSES.
- Página de ofertas: https://www.aerolineas.com.ar/es-ar/ofertas
- Página de cuotas: https://www.aerolineas.com.ar/es-ar/cuotas
- Promo del mes: https://www.aerolineas.com.ar/es-ar/promociones

🟠 JETSMART (JA)
- Promo Flash: descuentos de hasta 50% cada semana, generalmente martes y miércoles.
- Códigos de descuento: se publican en su newsletter y redes sociales. Suscribirse en: https://jetsmart.com/ar/es/
- Cuotas: trabaja con Mercado Pago (hasta 12 cuotas con tarjetas seleccionadas) y algunos bancos.
- Página de ofertas: https://jetsmart.com/ar/es/vuelos-baratos/
- Bagaje: el básico no incluye equipaje de bodega — conviene sumar "Smart+" para viajes con valija.

🟡 FLYBONDI (FO)
- "Bondi Sale": promotions flash cada semanas, precios desde $0 (solo tasas).
- Código PRIMERAVEZ: descuento para nuevos usuarios (verificar vigencia).
- Cuotas: acepta Mercado Pago en cuotas y algunas tarjetas de crédito.
- Newsletter con códigos exclusivos: https://www.flybondi.com/ar
- Página de ofertas: https://www.flybondi.com/ar/vuelos-baratos

🔴 LATAM (LA)
- Cuotas sin interés: hasta 12 cuotas con Banco Nación, Galicia, BBVA y otros. Ver: https://www.latamairlines.com/ar/es/cuotas
- Promo "Cyber" y "Hot Sale": descuentos importantes en fechas especiales.
- Programa LATAM Pass: acumulás puntos.
- Ofertas: https://www.latamairlines.com/ar/es/ofertas

💡 CONSEJOS GENERALES SOBRE CUOTAS Y PROMOS:
- Las mejores promos suelen aparecer los MARTES y MIÉRCOLES.
- Hot Sale (mayo), CyberMonday (noviembre) y el "Cyber Lunes" de cada aerolínea son los mejores momentos.
- Para cuotas sin interés: verificar siempre con el banco emisor de la tarjeta, ya que los convenios cambian mensualmente.
- Suscribirse al newsletter de cada aerolínea da acceso a códigos exclusivos antes que al público general.
- Comprar con 2-3 meses de anticipación suele dar mejores precios que las ofertas de último momento (salvo promos flash específicas).

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Cuando mostrés resultados de búsqueda de vuelos, siempre mencionás:
1. El precio por persona Y el total si vinieron más de 1 pasajero
2. Qué aerolínea opera y si tiene programa de cuotas relevante
3. El link directo a la página de ofertas/cuotas de esa aerolínea

Reglas:
- Respondés siempre en español rioplatense
- Sos breve: máximo 3-4 párrafos cuando no hay herramientas
- Usás emojis con moderación (1-3 por mensaje)
- Nunca dejás al usuario sin una respuesta útil
- Hoy es {datetime.today().strftime('%d/%m/%Y')}
"""

# ── Herramientas para Claude ──────────────────────────────────────────────────

TOOLS = [
    {
        "name": "buscar_fechas_baratas",
        "description": (
            "Busca las fechas más baratas para volar entre dos aeropuertos en un rango de fechas. "
            "Usar cuando el usuario quiere saber cuándo es más barato volar, sin fecha fija."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "origen": {"type": "string", "description": "Código IATA del aeropuerto de origen (ej: MDZ)"},
                "destino": {"type": "string", "description": "Código IATA del aeropuerto de destino (ej: GRU)"},
                "fecha_desde": {"type": "string", "description": "Fecha inicio del rango YYYY-MM-DD"},
                "fecha_hasta": {"type": "string", "description": "Fecha fin del rango YYYY-MM-DD"},
                "duracion_noches": {"type": "integer", "description": "Duración del viaje en noches (default 3)"},
                "pasajeros": {"type": "integer", "description": "Cantidad de pasajeros (default 1)"},
            },
            "required": ["origen", "destino", "fecha_desde", "fecha_hasta"],
        },
    },
    {
        "name": "buscar_vuelos_fecha",
        "description": (
            "Busca vuelos disponibles en una fecha específica entre dos aeropuertos."
            "Usar cuando el usuario tiene una fecha concreta en mente."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "origen": {"type": "string", "description": "Código IATA origen"},
                "destino": {"type": "string", "description": "Código IATA destino"},
                "fecha_ida": {"type": "string", "description": "Fecha de ida YYYY-MM-DD"},
                "fecha_vuelta": {"type": "string", "description": "Fecha de vuelta YYYY-MM-DD (opcional)"},
                "pasajeros": {"type": "integer", "description": "Cantidad de pasajeros (default 1)"},
            },
            "required": ["origen", "destino", "fecha_ida"],
        },
    },
]


# ── Cotización del dólar ──────────────────────────────────────────────────────

_dolar_cache: dict = {"ts": None, "blue": None, "oficial": None, "mep": None}


def get_dolar() -> dict:
    """Obtiene cotización del dólar blue, oficial y MEP desde la API de Argentina."""
    import time
    now = time.time()
    # Cache de 15 minutos
    if _dolar_cache["ts"] and now - _dolar_cache["ts"] < 900:
        return _dolar_cache

    try:
        r = requests.get("https://dolarapi.com/v1/dolares", timeout=8)
        if r.status_code == 200:
            data = r.json()
            for d in data:
                casa = d.get("casa", "").lower()
                venta = d.get("venta") or d.get("compra")
                if casa == "blue":
                    _dolar_cache["blue"] = float(venta)
                elif casa == "oficial":
                    _dolar_cache["oficial"] = float(venta)
                elif casa in ("bolsa", "mep"):
                    _dolar_cache["mep"] = float(venta)
            _dolar_cache["ts"] = now
    except Exception:
        pass

    return _dolar_cache


def fmt_precio_completo(usd: float, pasajeros: int = 1) -> str:
    """Devuelve precio en USD + ARS con cotizaciones."""
    cotiz = get_dolar()
    total_usd = usd * pasajeros

    lines = [f"*{fmt_price(usd)} USD* por persona"]
    if pasajeros > 1:
        lines.append(f"*{fmt_price(total_usd)} USD* total ({pasajeros} personas)")

    if cotiz.get("blue"):
        ars_blue = total_usd * cotiz["blue"]
        lines.append(f"≈ *${fmt_price(ars_blue)} ARS* (dólar blue ${cotiz['blue']:,.0f})")
    if cotiz.get("oficial"):
        ars_of = total_usd * cotiz["oficial"]
        lines.append(f"≈ *${fmt_price(ars_of)} ARS* (dólar oficial ${cotiz['oficial']:,.0f})")
    if cotiz.get("blue") and cotiz.get("oficial"):
        ahorro = total_usd * (cotiz["blue"] - cotiz["oficial"])
        lines.append(f"💡 Pagando en USD ahorrás *${fmt_price(ahorro)} ARS* vs. pagar en pesos oficiales")

    return "\n".join(lines)


# ── fli CLI ───────────────────────────────────────────────────────────────────

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


# ── Formatters ────────────────────────────────────────────────────────────────

DIAS_ES = {
    "Monday": "Lun", "Tuesday": "Mar", "Wednesday": "Mié",
    "Thursday": "Jue", "Friday": "Vie", "Saturday": "Sáb", "Sunday": "Dom",
}
MESES_ES = {
    "01": "ene", "02": "feb", "03": "mar", "04": "abr", "05": "may", "06": "jun",
    "07": "jul", "08": "ago", "09": "sep", "10": "oct", "11": "nov", "12": "dic",
}


def fmt_date(iso: str) -> str:
    try:
        p = iso.split("-")
        return f"{int(p[2])} {MESES_ES[p[1]]}"
    except Exception:
        return iso


def fmt_duration(minutes: int) -> str:
    h, m = divmod(minutes, 60)
    return f"{h}h {m:02d}m"


def fmt_price(price: float) -> str:
    return f"${price:,.0f}".replace(",", ".")


def google_flights_url(origin, dest, date, return_date=None):
    """URL de Google Flights — formato /travel/flights con query string, funciona en todos los clientes."""
    if return_date:
        q = f"Flights+from+{origin}+to+{dest}+on+{date}+return+{return_date}"
    else:
        q = f"Flights+from+{origin}+to+{dest}+on+{date}"
    return f"https://www.google.com/travel/flights?q={q}&hl=es"


def execute_buscar_fechas(origen, destino, fecha_desde, fecha_hasta, duracion_noches=3, pasajeros=1) -> str:
    raw = run_fli_text([
        "dates", origen, destino,
        "--from", fecha_desde, "--to", fecha_hasta,
        "--duration", str(duracion_noches),
        "--round", "--sort",
    ])

    if raw in ("__timeout__", "__error__"):
        return "Error al consultar Google Flights."

    rows = []
    for line in raw.splitlines():
        m = re.match(
            r'\s*[│|╭╰├]\s*(\d{4}-\d{2}-\d{2})\s*[│|]\s*(\w+)\s*[│|]\s*(\d{4}-\d{2}-\d{2})\s*[│|]\s*(\w+)\s*[│|]\s*\$?([\d,\.]+)',
            line
        )
        if m:
            dep, dep_day, ret, ret_day, price_raw = m.groups()
            rows.append((dep, dep_day, ret, ret_day, float(price_raw.replace(",", ""))))

    if not rows:
        return "No se encontraron resultados para esa ruta y rango de fechas."

    rows.sort(key=lambda x: x[4])
    top = rows[:10]
    dur_txt = f"{duracion_noches} noche{'s' if duracion_noches != 1 else ''}"

    cotiz = get_dolar()
    blue = cotiz.get("blue")

    dur_txt = f"{duracion_noches} noche{'s' if duracion_noches != 1 else ''}"
    pas_txt = f" · {pasajeros} personas" if pasajeros > 1 else ""
    lines = [f"Top {len(top)} fechas más baratas ({dur_txt}, ida y vuelta{pas_txt}):\n"]

    for i, (dep, dep_day, ret, ret_day, price) in enumerate(top, 1):
        medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
        dep_es = DIAS_ES.get(dep_day, dep_day)
        ret_es = DIAS_ES.get(ret_day, ret_day)
        link = google_flights_url(origen, destino, dep, ret)
        total = price * pasajeros
        ars_txt = f" ≈ ${fmt_price(total * blue)} ARS" if blue else ""
        total_txt = f" ({fmt_price(total)} USD total{ars_txt})" if pasajeros > 1 else (f"{ars_txt}" if ars_txt else "")
        lines.append(
            f"{medal} *{fmt_price(price)} USD*{total_txt}\n"
            f"   📅 {fmt_date(dep)} ({dep_es}) → {fmt_date(ret)} ({ret_es})\n"
            f"   [Reservar →]({link})"
        )

    savings = top[-1][4] - top[0][4]
    if savings > 50:
        lines.append(f"\n💰 Saliendo el {fmt_date(top[0][0])} ahorrás *{fmt_price(savings)} USD* vs la fecha más cara.")

    if blue:
        lines.append(f"💱 Cotización usada: dólar blue *${blue:,.0f}*")

    lines.append(f"\n💡 _¿Querés ver los vuelos de alguna de estas fechas? Decime cuál._")
    return "\n".join(lines)


def execute_buscar_vuelos(origen, destino, fecha_ida, fecha_vuelta=None, pasajeros=1) -> str:
    args = ["flights", origen, destino, fecha_ida]
    if fecha_vuelta:
        args += ["--return", fecha_vuelta]
    args += ["--sort", "CHEAPEST"]

    data = run_fli_json(args)
    if not data or not data.get("success"):
        return "No se encontraron vuelos para esa ruta y fecha."

    flights = data.get("flights", [])
    if not flights:
        return "No hay vuelos disponibles para esa ruta y fecha."

    cotiz = get_dolar()
    blue = cotiz.get("blue")

    lines = []
    for i, f in enumerate(flights[:5], 1):
        usd = f["price"]
        total_usd = usd * pasajeros
        duration = fmt_duration(f["duration"])
        stops = "Directo" if f["stops"] == 0 else f"{f['stops']} escala{'s' if f['stops'] > 1 else ''}"
        stop_icon = "🟢" if f["stops"] == 0 else "🟡"

        airlines, segments = [], []
        for leg in f.get("legs", []):
            name = leg.get("airline", {}).get("name", "")
            if name and name not in airlines:
                airlines.append(name)
            dep = datetime.fromisoformat(leg["departure_time"]).strftime("%H:%M") if leg.get("departure_time") else ""
            arr = datetime.fromisoformat(leg["arrival_time"]).strftime("%H:%M") if leg.get("arrival_time") else ""
            orig = leg["departure_airport"]["code"]
            dst = leg["arrival_airport"]["code"]
            fn = leg.get("flight_number", "")
            segments.append(f"{orig} {dep} → {dst} {arr}" + (f" (#{fn})" if fn else ""))

        link = google_flights_url(origen, destino, fecha_ida, fecha_vuelta)
        airline_str = " / ".join(airlines) or "—"

        price_line = f"*{fmt_price(usd)} USD*"
        if pasajeros > 1:
            price_line += f" c/u — *{fmt_price(total_usd)} USD* total"
        if blue:
            price_line += f"\n   ≈ *${fmt_price(total_usd * blue)} ARS* (blue ${blue:,.0f})"

        lines.append(
            f"{stop_icon} {price_line}\n"
            f"✈️ {airline_str} — {duration} — {stops}\n"
            + "\n".join(f"   {s}" for s in segments) +
            f"\n[Reservar en Google Flights →]({link})"
        )

    ahorro_txt = ""
    if blue and cotiz.get("oficial"):
        usd_mas_barato = flights[0]["price"] * pasajeros
        ahorro = usd_mas_barato * (blue - cotiz["oficial"])
        ahorro_txt = f"\n💡 Pagando en USD ahorrás aprox. *${fmt_price(ahorro)} ARS* vs. pagar en pesos al tipo oficial."

    footer = f"{ahorro_txt}\n\n_Precios de Google Flights, pueden variar al momento de comprar._"
    return "\n\n".join(lines) + footer


# ── Motor de IA ───────────────────────────────────────────────────────────────

def run_tool(name: str, inputs: dict) -> str:
    if name == "buscar_fechas_baratas":
        return execute_buscar_fechas(
            inputs["origen"], inputs["destino"],
            inputs["fecha_desde"], inputs["fecha_hasta"],
            inputs.get("duracion_noches", 3),
            inputs.get("pasajeros", 1),
        )
    if name == "buscar_vuelos_fecha":
        return execute_buscar_vuelos(
            inputs["origen"], inputs["destino"],
            inputs["fecha_ida"], inputs.get("fecha_vuelta"),
            inputs.get("pasajeros", 1),
        )
    return "Herramienta desconocida."


def chat_with_ai(chat_id: int, user_text: str) -> str:
    """Send message to Claude, handle tool calls, return final text response."""
    if not ai:
        return None

    history = histories.setdefault(chat_id, [])
    history.append({"role": "user", "content": user_text})

    # Keep history bounded
    if len(history) > MAX_HISTORY:
        history[:] = history[-MAX_HISTORY:]

    messages = list(history)

    for _ in range(5):  # max tool call rounds
        response = ai.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages,
        )

        if response.stop_reason == "end_turn":
            # Final text response
            text = next((b.text for b in response.content if hasattr(b, "text")), "")
            history.append({"role": "assistant", "content": text})
            return text

        if response.stop_reason == "tool_use":
            # Execute each tool call
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    result = run_tool(block.name, block.input)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    })

            # Add assistant response and tool results to messages
            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": tool_results})
            continue

        break

    return "Algo salió mal 😕 Intentá de nuevo."


# ── Audio ─────────────────────────────────────────────────────────────────────

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


# ── Handlers ──────────────────────────────────────────────────────────────────

LOADING_MSGS = [
    "Un momento, estoy pensando... 🤔",
    "Consultando vuelos y más info... ✈️",
    "Dame un segundo... 🔍",
    "Revisando todo para vos... 🗓️",
]


def handle_message(chat_id, message_id, text):
    msg = bot.send_message(chat_id, random.choice(LOADING_MSGS),
                           reply_to_message_id=message_id)
    try:
        response = chat_with_ai(chat_id, text)
        if not response:
            response = "Lo siento, no pude procesar tu consulta. Intentá de nuevo 😕"

        bot.edit_message_text(
            response,
            chat_id=chat_id, message_id=msg.message_id,
            parse_mode="Markdown", disable_web_page_preview=True,
        )
    except Exception as e:
        bot.edit_message_text(
            "Ups, algo falló 😕 Intentá de nuevo en un momento.",
            chat_id=chat_id, message_id=msg.message_id,
        )


@bot.message_handler(commands=["start"])
def cmd_start(message):
    nombre = message.from_user.first_name or "viajero"
    histories.pop(message.chat.id, None)  # reset history on start
    bot.send_message(
        message.chat.id,
        f"¡Hola, {nombre}! 👋 Soy *Flynow*, tu asistente de viajes. ✈️\n\n"
        f"Puedo ayudarte con:\n"
        f"• 🔍 Buscar vuelos baratos\n"
        f"• 📅 Encontrar las fechas más económicas\n"
        f"• 🌦️ Info sobre clima en cada destino\n"
        f"• 🛂 Requisitos de visa para argentinos\n"
        f"• 🗺️ Consejos de viaje, zonas, presupuesto\n\n"
        f"Escribime o mandame un 🎙️ *audio* — hablame como si fuera un amigo.\n\n"
        f"¿A dónde soñás viajar? 🌍",
        parse_mode="Markdown",
    )


@bot.message_handler(commands=["reset", "nuevo"])
def cmd_reset(message):
    histories.pop(message.chat.id, None)
    bot.reply_to(message, "Listo, empezamos de cero 🔄 ¿A dónde querés ir?")


@bot.message_handler(commands=["help", "ayuda"])
def cmd_help(message):
    bot.send_message(
        message.chat.id,
        "✈️ *Flynow — Asistente de Viajes*\n\n"
        "Hablame como si le hablaras a un amigo, por ejemplo:\n\n"
        "• _\"quiero ir a Brasil 10 días en julio\"_\n"
        "• _\"fechas baratas de mendoza a miami\"_\n"
        "• _\"¿necesito visa para Europa?\"_\n"
        "• _\"¿cuándo es mejor ir a Bangkok?\"_\n"
        "• _\"vuelos mdz eze el 15 de abril\"_\n\n"
        "También podés mandarme un 🎙️ *audio* y te entiendo igual.\n\n"
        "Usá /reset para empezar una nueva conversación.",
        parse_mode="Markdown",
    )


@bot.message_handler(content_types=["voice"])
def handle_voice(message):
    if not GROQ_API_KEY:
        bot.reply_to(
            message,
            "Los audios todavía no están activados 🎙️\n"
            "Escribime lo mismo con texto y te ayudo igual 😊"
        )
        return

    msg = bot.reply_to(message, "🎙️ Escuchando tu audio...")
    path = download_voice(message.voice.file_id)

    if not path:
        bot.edit_message_text("No pude procesar el audio 😕 ¿Podés escribirme lo mismo?",
                              message.chat.id, msg.message_id)
        return

    text = transcribe_audio(path)
    try:
        os.remove(path)
    except Exception:
        pass

    if not text:
        bot.edit_message_text("No pude entender el audio 😕 ¿Podés escribirme lo mismo?",
                              message.chat.id, msg.message_id)
        return

    bot.edit_message_text(f"🎙️ _\"{text}\"_\n\n{random.choice(LOADING_MSGS)}",
                          message.chat.id, msg.message_id, parse_mode="Markdown")

    try:
        response = chat_with_ai(message.chat.id, text)
        if not response:
            response = "No pude procesar eso. Intentá de nuevo 😕"
        bot.edit_message_text(
            f"🎙️ _\"{text}\"_\n\n{response}",
            chat_id=message.chat.id, message_id=msg.message_id,
            parse_mode="Markdown", disable_web_page_preview=True,
        )
    except Exception:
        bot.edit_message_text("Ups, algo falló 😕 Intentá de nuevo.",
                              message.chat.id, msg.message_id)


@bot.message_handler(content_types=["text"])
def handle_text(message):
    handle_message(message.chat.id, message.message_id, message.text)


@bot.message_handler(content_types=["sticker", "photo", "video", "document", "location"])
def handle_other(message):
    bot.reply_to(
        message,
        "Solo entiendo texto y audios por ahora 😅\n"
        "¿A dónde querés volar? 🌍"
    )


if __name__ == "__main__":
    print("Bot iniciado con IA...")
    bot.infinity_polling()
