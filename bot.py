import json
import os
import random
import re
import shutil
import subprocess
import sys
import urllib.parse
from datetime import datetime, timedelta
import telebot
import requests
import anthropic
from apscheduler.schedulers.background import BackgroundScheduler
from supabase import create_client

TOKEN = os.environ["BOT_TOKEN"]
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

bot = telebot.TeleBot(TOKEN)
ai = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY) if ANTHROPIC_API_KEY else None
db = create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_URL and SUPABASE_KEY else None

# Historial de conversación en memoria { chat_id: [{role, content}, ...] }
histories: dict = {}
MAX_HISTORY = 12

# Búsquedas pendientes de confirmación { chat_id: {tipo, params} }
pending_searches: dict = {}


# ── Prompt del sistema ────────────────────────────────────────────────────────

SYSTEM_PROMPT_BASE = """Sos Flynow, el mejor asistente de viajes del mundo. Hablás en español rioplatense (argentino): usás "vos", "te", "podés", "querés", etc. Sos cálido, entusiasta, conciso y muy útil.

Tu especialidad es encontrar vuelos baratos, pero también asesorás sobre:
- Clima y mejor época para visitar destinos
- Requisitos de visa para ciudadanos argentinos
- Consejos de viaje: presupuesto, hospedaje, zonas, seguridad
- Moneda, idioma, costumbres locales
- Atracciones, gastronomía, actividades

Cuando el usuario quiera buscar vuelos o fechas baratas, usás las herramientas disponibles.
Siempre convertís nombres de ciudades, regiones y países a códigos IATA correctos.
Si el usuario menciona una región o país (ej: "Brasil", "Europa"), elegís el aeropuerto principal más relevante.
Si el usuario menciona cantidad de personas (ej: "con 3 amigos", "somos 4"), multiplicás el precio total y lo aclarás.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FLUJO DE BÚSQUEDA — MUY IMPORTANTE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. Cuando te falte info (origen, mes, duración, personas), usá `preguntar_con_opciones` con botones — NUNCA hagas la pregunta en texto.
2. Cuando ya tenés TODOS los parámetros listos para buscar, usá `confirmar_busqueda` ANTES de buscar — esto muestra un resumen y pide OK al usuario.
3. Si el usuario dice "sí" o confirma, la búsqueda se ejecuta automáticamente — NO llamés vos mismo a buscar_fechas_baratas o buscar_vuelos_fecha después de confirmar_busqueda.
4. Si el usuario no sabe a dónde ir o dice "sorprendeme", "no sé", "a dónde puedo ir", usá `sorprender_destino`.
5. Cuando el usuario mencione su ciudad de origen por primera vez, guardala con `guardar_ciudad_origen`.

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
- Hoy es {fecha}
{contexto_usuario}"""


def get_system_prompt(chat_id: int) -> str:
    user = get_user(chat_id)
    contexto = ""
    if user and user.get("ciudad_origen"):
        origen = user["ciudad_origen"]
        nombre = user.get("nombre", "")
        contexto = f"\nEl usuario sale habitualmente desde: {origen}. Usalo como origen por defecto si no especifica otro."
        if nombre:
            contexto = f"\nEl usuario se llama {nombre}." + contexto
    return SYSTEM_PROMPT_BASE.format(
        fecha=datetime.today().strftime('%d/%m/%Y'),
        contexto_usuario=contexto,
    )


# ── Herramientas para Claude ──────────────────────────────────────────────────

TOOLS = [
    {
        "name": "buscar_fechas_baratas",
        "description": (
            "Busca las fechas más baratas para volar entre dos aeropuertos en un rango de fechas. "
            "IMPORTANTE: Solo llamar esto después de que el usuario haya confirmado la búsqueda via confirmar_busqueda."
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
            "Busca vuelos disponibles en una fecha específica entre dos aeropuertos. "
            "IMPORTANTE: Solo llamar esto después de que el usuario haya confirmado la búsqueda via confirmar_busqueda."
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
    {
        "name": "confirmar_busqueda",
        "description": (
            "Muestra un resumen de los parámetros de búsqueda y pide confirmación al usuario ANTES de ejecutar la búsqueda. "
            "Usar SIEMPRE que tengas todos los datos listos para buscar vuelos o fechas baratas. "
            "Después de llamar esto, NO llamés buscar_fechas_baratas ni buscar_vuelos_fecha — se ejecuta automáticamente si el usuario confirma."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "tipo": {"type": "string", "enum": ["fechas", "vuelos"], "description": "Tipo de búsqueda"},
                "origen": {"type": "string", "description": "Código IATA origen"},
                "destino": {"type": "string", "description": "Código IATA destino"},
                "fecha_desde": {"type": "string", "description": "Para tipo=fechas: YYYY-MM-DD"},
                "fecha_hasta": {"type": "string", "description": "Para tipo=fechas: YYYY-MM-DD"},
                "fecha_ida": {"type": "string", "description": "Para tipo=vuelos: YYYY-MM-DD"},
                "fecha_vuelta": {"type": "string", "description": "Para tipo=vuelos: YYYY-MM-DD (opcional)"},
                "duracion_noches": {"type": "integer", "description": "Duración del viaje en noches"},
                "pasajeros": {"type": "integer", "description": "Cantidad de pasajeros"},
            },
            "required": ["tipo", "origen", "destino"],
        },
    },
    {
        "name": "preguntar_con_opciones",
        "description": (
            "Hacer UNA pregunta al usuario mostrando botones de respuesta rápida. "
            "Usar SIEMPRE que necesites preguntarle al usuario sobre fechas, duración, cantidad de personas, o sí/no. "
            "NO hagas la pregunta en texto — usá esta herramienta para que aparezcan botones tapeables."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "pregunta": {"type": "string", "description": "La pregunta a mostrar al usuario"},
                "tipo": {
                    "type": "string",
                    "enum": ["meses", "duracion", "personas", "si_no", "custom"],
                    "description": (
                        "Tipo de opciones: "
                        "'meses' = botones con los meses del año, "
                        "'duracion' = finde/semana/10días/2semanas, "
                        "'personas' = 1/2/3/4 personas, "
                        "'si_no' = Sí/No, "
                        "'custom' = opciones personalizadas"
                    ),
                },
                "opciones_custom": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Solo si tipo=custom: lista de opciones a mostrar como botones (máx 6)",
                },
            },
            "required": ["pregunta", "tipo"],
        },
    },
    {
        "name": "sorprender_destino",
        "description": (
            "Sugiere 3 destinos al azar cuando el usuario no sabe a dónde quiere ir. "
            "Usar cuando el usuario dice 'sorprendeme', 'no sé a dónde ir', 'a dónde me recomendás', etc."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "origen": {"type": "string", "description": "Código IATA de la ciudad de origen del usuario"},
            },
            "required": ["origen"],
        },
    },
    {
        "name": "guardar_ciudad_origen",
        "description": (
            "Guarda la ciudad de origen habitual del usuario para no preguntársela cada vez. "
            "Llamar cuando el usuario mencione su ciudad de origen por primera vez."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "iata": {"type": "string", "description": "Código IATA de la ciudad (ej: MDZ)"},
                "nombre": {"type": "string", "description": "Nombre legible de la ciudad (ej: Mendoza)"},
            },
            "required": ["iata"],
        },
    },
    {
        "name": "crear_alerta_precio",
        "description": (
            "Crea una alerta para notificar al usuario cuando el precio de un vuelo baje de un umbral. "
            "Usar cuando el usuario diga 'avisame si baja de X', 'crear alerta', 'notificame cuando esté barato', etc."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "origen": {"type": "string", "description": "Código IATA origen"},
                "destino": {"type": "string", "description": "Código IATA destino"},
                "precio_max_usd": {"type": "number", "description": "Precio máximo en USD por persona"},
                "duracion_noches": {"type": "integer", "description": "Duración del viaje en noches (default 3)"},
                "mes_inicio": {"type": "integer", "description": "Mes inicio para buscar (1-12, opcional)"},
                "mes_fin": {"type": "integer", "description": "Mes fin para buscar (1-12, opcional)"},
            },
            "required": ["origen", "destino", "precio_max_usd"],
        },
    },
    {
        "name": "listar_alertas",
        "description": "Lista las alertas de precio activas del usuario.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "eliminar_alerta",
        "description": "Elimina/desactiva una alerta de precio por su ID.",
        "input_schema": {
            "type": "object",
            "properties": {
                "alerta_id": {"type": "integer", "description": "ID de la alerta a eliminar"},
            },
            "required": ["alerta_id"],
        },
    },
]


# ── Destinos sorpresa ──────────────────────────────────────────────────────────

DESTINOS_SORPRESA = [
    {"destino": "BRC", "nombre": "Bariloche",  "emoji": "🏔️", "desc": "Nieve, montañas y lagos increíbles"},
    {"destino": "IGR", "nombre": "Iguazú",     "emoji": "💧", "desc": "Las cataratas más espectaculares del mundo"},
    {"destino": "USH", "nombre": "Ushuaia",    "emoji": "🐧", "desc": "El fin del mundo y la Patagonia austral"},
    {"destino": "PMY", "nombre": "Puerto Madryn","emoji": "🐳","desc": "Ballenas, pingüinos y mar patagónico"},
    {"destino": "GRU", "nombre": "São Paulo",  "emoji": "🌆", "desc": "Gastronomía, cultura y vida nocturna"},
    {"destino": "GIG", "nombre": "Río de Janeiro","emoji":"🌴","desc": "Carnaval, playas y el Cristo Redentor"},
    {"destino": "SCL", "nombre": "Santiago",   "emoji": "🌋", "desc": "Ciudad vibrante con los Andes de fondo"},
    {"destino": "MIA", "nombre": "Miami",      "emoji": "🏖️", "desc": "Playa, shopping y el sol de Florida"},
    {"destino": "MAD", "nombre": "Madrid",     "emoji": "🇪🇸", "desc": "Europa desde Argentina, historia y tapas"},
    {"destino": "CUN", "nombre": "Cancún",     "emoji": "🌊", "desc": "Caribe mexicano, playas turquesa y ruinas mayas"},
    {"destino": "LIM", "nombre": "Lima",       "emoji": "🦙", "desc": "Machu Picchu y la mejor gastronomía de Sudamérica"},
    {"destino": "BOG", "nombre": "Bogotá",     "emoji": "🌺", "desc": "Cartagena de Indias y el café colombiano"},
    {"destino": "MVD", "nombre": "Montevideo", "emoji": "🏙️", "desc": "Ciudad tranquila, playas y buen asado uruguayo"},
    {"destino": "VVI", "nombre": "Santa Cruz", "emoji": "🦜", "desc": "Puerta de entrada a la Amazonia boliviana"},
]


# ── Cotización del dólar ──────────────────────────────────────────────────────

_dolar_cache: dict = {"ts": None, "blue": None, "oficial": None, "mep": None}


def get_dolar() -> dict:
    import time
    now = time.time()
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


# ── Supabase helpers ──────────────────────────────────────────────────────────

def get_user(chat_id: int) -> dict | None:
    if not db:
        return None
    try:
        res = db.table("usuarios").select("*").eq("chat_id", chat_id).execute()
        return res.data[0] if res.data else None
    except Exception:
        return None


def save_user(chat_id: int, **kwargs):
    if not db:
        return
    try:
        kwargs["actualizado_at"] = datetime.now().isoformat()
        existing = get_user(chat_id)
        if existing:
            db.table("usuarios").update(kwargs).eq("chat_id", chat_id).execute()
        else:
            db.table("usuarios").insert({"chat_id": chat_id, **kwargs}).execute()
    except Exception:
        pass


def load_history_from_db(chat_id: int):
    if not db or chat_id in histories:
        return
    try:
        res = db.table("conversaciones").select("history").eq("chat_id", chat_id).execute()
        if res.data and res.data[0].get("history"):
            histories[chat_id] = res.data[0]["history"][-MAX_HISTORY:]
    except Exception:
        pass


def save_history_to_db(chat_id: int):
    if not db:
        return
    history = histories.get(chat_id, [])
    try:
        existing = db.table("conversaciones").select("chat_id").eq("chat_id", chat_id).execute()
        payload = {"history": history[-MAX_HISTORY:], "updated_at": datetime.now().isoformat()}
        if existing.data:
            db.table("conversaciones").update(payload).eq("chat_id", chat_id).execute()
        else:
            db.table("conversaciones").insert({"chat_id": chat_id, **payload}).execute()
    except Exception:
        pass


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
NOMBRES_MESES = [
    "", "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]


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
    if return_date:
        q = f"Flights+from+{origin}+to+{dest}+on+{date}+return+{return_date}"
    else:
        q = f"Flights+from+{origin}+to+{dest}+on+{date}"
    return f"https://www.google.com/travel/flights?q={q}&hl=es"


def share_button_markup(url: str, text: str = "Mirá estos vuelos que encontré con Flynow ✈️") -> telebot.types.InlineKeyboardMarkup:
    share_url = f"https://t.me/share/url?url={urllib.parse.quote(url, safe='')}&text={urllib.parse.quote(text, safe='')}"
    markup = telebot.types.InlineKeyboardMarkup()
    markup.row(telebot.types.InlineKeyboardButton("📤 Compartir", url=share_url))
    return markup


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


# ── Botones rápidos ───────────────────────────────────────────────────────────

OPCIONES_MESES = [
    ["Enero", "Febrero", "Marzo"],
    ["Abril", "Mayo", "Junio"],
    ["Julio", "Agosto", "Septiembre"],
    ["Octubre", "Noviembre", "Diciembre"],
]
OPCIONES_DURACION = [["Finde (2 días)", "1 semana", "10 días", "2 semanas"]]
OPCIONES_PERSONAS = [["Solo yo", "2 personas", "3 personas", "4 o más"]]
OPCIONES_SI_NO = [["Sí ✅", "No ❌"]]


def build_keyboard(tipo: str, opciones_custom: list = None) -> telebot.types.InlineKeyboardMarkup:
    markup = telebot.types.InlineKeyboardMarkup()
    if tipo == "meses":
        for fila in OPCIONES_MESES:
            markup.row(*[telebot.types.InlineKeyboardButton(m, callback_data=f"resp:{m}") for m in fila])
    elif tipo == "duracion":
        for fila in OPCIONES_DURACION:
            markup.row(*[telebot.types.InlineKeyboardButton(o, callback_data=f"resp:{o}") for o in fila])
    elif tipo == "personas":
        for fila in OPCIONES_PERSONAS:
            markup.row(*[telebot.types.InlineKeyboardButton(o, callback_data=f"resp:{o}") for o in fila])
    elif tipo == "si_no":
        for fila in OPCIONES_SI_NO:
            markup.row(*[telebot.types.InlineKeyboardButton(o, callback_data=f"resp:{o}") for o in fila])
    elif tipo == "custom" and opciones_custom:
        row = []
        for i, op in enumerate(opciones_custom[:6]):
            row.append(telebot.types.InlineKeyboardButton(op, callback_data=f"resp:{op}"))
            if len(row) == 2 or i == len(opciones_custom) - 1:
                markup.row(*row)
                row = []
    return markup


def execute_preguntar(chat_id: int, message_id: int, pregunta: str, tipo: str, opciones_custom: list = None) -> str:
    markup = build_keyboard(tipo, opciones_custom)
    audio_hint = "\n\n_También podés responder por 🎙️ audio_"
    bot.send_message(
        chat_id, pregunta + audio_hint,
        reply_to_message_id=message_id,
        reply_markup=markup,
        parse_mode="Markdown",
    )
    return "__pregunta_enviada__"


def execute_confirmar_busqueda(chat_id: int, tipo: str, origen: str, destino: str,
                                fecha_desde=None, fecha_hasta=None,
                                fecha_ida=None, fecha_vuelta=None,
                                duracion_noches=3, pasajeros=1) -> str:
    origen_u = origen.upper()
    destino_u = destino.upper()
    pas_txt = f"{pasajeros} pasajero{'s' if pasajeros > 1 else ''}"

    if tipo == "fechas":
        mes_ini = fmt_date(fecha_desde) if fecha_desde else "—"
        mes_fin = fmt_date(fecha_hasta) if fecha_hasta else "—"
        dur_txt = f"{duracion_noches} noche{'s' if duracion_noches != 1 else ''}"
        card = (
            f"🔍 *¿Arrancamos con esta búsqueda?*\n\n"
            f"✈️  {origen_u} → {destino_u}\n"
            f"📅  {mes_ini} – {mes_fin}\n"
            f"🌙  Estadía: {dur_txt}\n"
            f"👥  {pas_txt}"
        )
        pending_searches[chat_id] = {
            "tipo": "fechas",
            "params": {
                "origen": origen_u, "destino": destino_u,
                "fecha_desde": fecha_desde, "fecha_hasta": fecha_hasta,
                "duracion_noches": duracion_noches, "pasajeros": pasajeros,
            },
        }
    else:
        ida_txt = fmt_date(fecha_ida) if fecha_ida else "—"
        vuelta_txt = f"\n🔙  Vuelta: {fmt_date(fecha_vuelta)}" if fecha_vuelta else ""
        card = (
            f"🔍 *¿Arrancamos con esta búsqueda?*\n\n"
            f"✈️  {origen_u} → {destino_u}\n"
            f"📅  Ida: {ida_txt}{vuelta_txt}\n"
            f"👥  {pas_txt}"
        )
        pending_searches[chat_id] = {
            "tipo": "vuelos",
            "params": {
                "origen": origen_u, "destino": destino_u,
                "fecha_ida": fecha_ida, "fecha_vuelta": fecha_vuelta,
                "pasajeros": pasajeros,
            },
        }

    markup = telebot.types.InlineKeyboardMarkup()
    markup.row(
        telebot.types.InlineKeyboardButton("✅ Sí, buscar", callback_data="confirm:si"),
        telebot.types.InlineKeyboardButton("✏️ Modificar", callback_data="confirm:no"),
    )
    bot.send_message(chat_id, card, reply_markup=markup, parse_mode="Markdown")
    return "__pregunta_enviada__"


def execute_sorprender(chat_id: int, origen: str) -> str:
    origen_u = origen.upper()
    opciones = [d for d in DESTINOS_SORPRESA if d["destino"] != origen_u]
    seleccion = random.sample(opciones, min(3, len(opciones)))

    lines = ["🎲 *¡Te propongo estos destinos!* Tocá uno para buscar vuelos:\n"]
    markup = telebot.types.InlineKeyboardMarkup()

    for d in seleccion:
        lines.append(f"{d['emoji']} *{d['nombre']}* — _{d['desc']}_")
        markup.row(telebot.types.InlineKeyboardButton(
            f"{d['emoji']} Buscar a {d['nombre']}",
            callback_data=f"sorpresa:{origen_u}-{d['destino']}",
        ))

    bot.send_message(chat_id, "\n\n".join(lines), reply_markup=markup, parse_mode="Markdown")
    return "__pregunta_enviada__"


# ── Alertas ───────────────────────────────────────────────────────────────────

def execute_crear_alerta(chat_id, origen, destino, precio_max_usd, duracion_noches=3, mes_inicio=None, mes_fin=None) -> str:
    if not db:
        return "Base de datos no configurada. Contactá al administrador."
    try:
        db.table("alertas").insert({
            "chat_id": chat_id,
            "origen": origen.upper(),
            "destino": destino.upper(),
            "precio_max_usd": precio_max_usd,
            "duracion_noches": duracion_noches,
            "mes_inicio": mes_inicio,
            "mes_fin": mes_fin,
            "activa": True,
        }).execute()

        # Armar tarjeta de resumen
        dur_txt = f"{duracion_noches} noche{'s' if duracion_noches != 1 else ''}"
        meses_txt = "Todo el año"
        if mes_inicio:
            meses_txt = NOMBRES_MESES[mes_inicio].capitalize()
            if mes_fin and mes_fin != mes_inicio:
                meses_txt += f" – {NOMBRES_MESES[mes_fin].capitalize()}"

        cotiz = get_dolar()
        ars_txt = ""
        if cotiz.get("blue"):
            ars_equiv = precio_max_usd * cotiz["blue"]
            ars_txt = f"\n💱  ≈ *${fmt_price(ars_equiv)} ARS* (blue actual)"

        return (
            f"🔔 *¡Alerta creada!*\n\n"
            f"┌─────────────────────────\n"
            f"│ ✈️  *{origen.upper()} → {destino.upper()}*\n"
            f"│ 💰  Umbral: *{fmt_price(precio_max_usd)} USD* por persona{ars_txt}\n"
            f"│ 🌙  Estadía: {dur_txt}\n"
            f"│ 📅  Período: {meses_txt}\n"
            f"│ 🔄  Revisión cada 2 horas\n"
            f"└─────────────────────────\n\n"
            f"Te aviso apenas baje de ese precio 🚀\n"
            f"_Usá /alertas para ver o eliminar tus alertas activas._"
        )
    except Exception as e:
        return f"No pude crear la alerta: {e}"


def execute_listar_alertas(chat_id) -> str:
    if not db:
        return "Base de datos no configurada."
    try:
        res = db.table("alertas").select("*").eq("chat_id", chat_id).eq("activa", True).execute()
        rows = res.data
        if not rows:
            return "No tenés alertas activas. Podés crear una diciéndome: _\"avisame cuando MDZ-EZE baje de 50 USD\"_"
        lines = ["🔔 *Tus alertas activas:*\n"]
        for r in rows:
            mes_txt = ""
            if r.get("mes_inicio"):
                mes_txt = f" — {NOMBRES_MESES[r['mes_inicio']].capitalize()}"
                if r.get("mes_fin") and r["mes_fin"] != r["mes_inicio"]:
                    mes_txt += f"/{NOMBRES_MESES[r['mes_fin']].capitalize()}"
            lines.append(
                f"*#{r['id']}* {r['origen']} → {r['destino']}{mes_txt}\n"
                f"   Precio umbral: *{fmt_price(r['precio_max_usd'])} USD*\n"
                f"   Duración: {r['duracion_noches']} noches"
            )
        lines.append("\nPara eliminar una: _\"eliminar alerta #ID\"_")
        return "\n\n".join(lines)
    except Exception as e:
        return f"No pude obtener las alertas: {e}"


def execute_eliminar_alerta(chat_id, alerta_id) -> str:
    if not db:
        return "Base de datos no configurada."
    try:
        res = db.table("alertas").update({"activa": False}).eq("id", alerta_id).eq("chat_id", chat_id).execute()
        if res.data:
            return f"✅ Alerta #{alerta_id} eliminada."
        return f"No encontré la alerta #{alerta_id} entre tus alertas activas."
    except Exception as e:
        return f"No pude eliminar la alerta: {e}"


def check_alertas():
    if not db:
        return
    try:
        res = db.table("alertas").select("*").eq("activa", True).execute()
        alertas = res.data
        if not alertas:
            return

        now = datetime.now()
        for alerta in alertas:
            try:
                origen = alerta["origen"]
                destino = alerta["destino"]
                precio_max = float(alerta["precio_max_usd"])
                duracion = alerta.get("duracion_noches", 3)
                mes_ini = alerta.get("mes_inicio")

                if mes_ini:
                    year = now.year
                    if mes_ini < now.month:
                        year += 1
                    desde = datetime(year, mes_ini, 1).strftime("%Y-%m-%d")
                    mes_end = alerta.get("mes_fin") or mes_ini
                    hasta_dt = datetime(year + 1, 1, 1) - timedelta(days=1) if mes_end == 12 \
                        else datetime(year, mes_end + 1, 1) - timedelta(days=1)
                    hasta = hasta_dt.strftime("%Y-%m-%d")
                else:
                    desde = now.strftime("%Y-%m-%d")
                    hasta = (now + timedelta(days=60)).strftime("%Y-%m-%d")

                raw = run_fli_text([
                    "dates", origen, destino,
                    "--from", desde, "--to", hasta,
                    "--duration", str(duracion),
                    "--round", "--sort",
                ])

                precio_min = None
                fecha_min = None
                for line in raw.splitlines():
                    m = re.match(
                        r'\s*[│|╭╰├]\s*(\d{4}-\d{2}-\d{2})\s*[│|]\s*\w+\s*[│|]\s*(\d{4}-\d{2}-\d{2})\s*[│|]\s*\w+\s*[│|]\s*\$?([\d,\.]+)',
                        line
                    )
                    if m:
                        dep, ret, price_raw = m.group(1), m.group(2), m.group(3)
                        price = float(price_raw.replace(",", ""))
                        if precio_min is None or price < precio_min:
                            precio_min = price
                            fecha_min = (dep, ret)

                if precio_min and precio_min <= precio_max and fecha_min:
                    link = google_flights_url(origen, destino, fecha_min[0], fecha_min[1])
                    cotiz = get_dolar()
                    blue = cotiz.get("blue")
                    ars_txt = f" ≈ *${fmt_price(precio_min * blue)} ARS*" if blue else ""

                    msg = (
                        f"🚨 *¡Alerta de precio!* 🚨\n\n"
                        f"✈️ *{origen} → {destino}*\n"
                        f"💰 *{fmt_price(precio_min)} USD*{ars_txt} — por debajo de tu umbral de {fmt_price(precio_max)} USD\n"
                        f"📅 {fmt_date(fecha_min[0])} → {fmt_date(fecha_min[1])} ({duracion} noches)\n\n"
                        f"[Reservar ahora →]({link})\n\n"
                        f"_¡Los precios cambian rápido, no lo dejes para después!_ ⏰"
                    )
                    bot.send_message(alerta["chat_id"], msg,
                                     parse_mode="Markdown", disable_web_page_preview=True)

                db.table("alertas").update({"ultima_check": now.isoformat()}).eq("id", alerta["id"]).execute()
            except Exception:
                continue
    except Exception:
        pass


# ── Motor de IA ───────────────────────────────────────────────────────────────

def run_tool(name: str, inputs: dict, chat_id: int = 0, message_id: int = 0) -> str:
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
    if name == "confirmar_busqueda":
        return execute_confirmar_busqueda(
            chat_id,
            inputs["tipo"], inputs["origen"], inputs["destino"],
            fecha_desde=inputs.get("fecha_desde"),
            fecha_hasta=inputs.get("fecha_hasta"),
            fecha_ida=inputs.get("fecha_ida"),
            fecha_vuelta=inputs.get("fecha_vuelta"),
            duracion_noches=inputs.get("duracion_noches", 3),
            pasajeros=inputs.get("pasajeros", 1),
        )
    if name == "preguntar_con_opciones":
        return execute_preguntar(
            chat_id, message_id,
            inputs["pregunta"], inputs["tipo"],
            inputs.get("opciones_custom"),
        )
    if name == "sorprender_destino":
        return execute_sorprender(chat_id, inputs["origen"])
    if name == "guardar_ciudad_origen":
        save_user(chat_id, ciudad_origen=inputs["iata"].upper())
        nombre = inputs.get("nombre", inputs["iata"])
        return f"✅ Guardé que salís desde {nombre} ({inputs['iata'].upper()}). De ahora en más lo uso como origen por defecto 🏠"
    if name == "crear_alerta_precio":
        return execute_crear_alerta(
            chat_id,
            inputs["origen"], inputs["destino"],
            inputs["precio_max_usd"],
            inputs.get("duracion_noches", 3),
            inputs.get("mes_inicio"), inputs.get("mes_fin"),
        )
    if name == "listar_alertas":
        return execute_listar_alertas(chat_id)
    if name == "eliminar_alerta":
        return execute_eliminar_alerta(chat_id, inputs["alerta_id"])
    return "Herramienta desconocida."


def chat_with_ai(chat_id: int, user_text: str, message_id: int = 0) -> str:
    if not ai:
        return None

    # Cargar historial persistente (solo la primera vez en esta sesión)
    load_history_from_db(chat_id)

    history = histories.setdefault(chat_id, [])
    history.append({"role": "user", "content": user_text})

    if len(history) > MAX_HISTORY:
        history[:] = history[-MAX_HISTORY:]

    messages = list(history)
    system = get_system_prompt(chat_id)

    for _ in range(5):
        response = ai.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            system=system,
            tools=TOOLS,
            messages=messages,
        )

        if response.stop_reason == "end_turn":
            text = next((b.text for b in response.content if hasattr(b, "text")), "")
            history.append({"role": "assistant", "content": text})
            save_history_to_db(chat_id)
            return text

        if response.stop_reason == "tool_use":
            tool_results = []
            pregunta_enviada = False
            for block in response.content:
                if block.type == "tool_use":
                    result = run_tool(block.name, block.input, chat_id=chat_id, message_id=message_id)
                    if result == "__pregunta_enviada__":
                        pregunta_enviada = True
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    })

            if pregunta_enviada:
                save_history_to_db(chat_id)
                return "__pregunta_enviada__"

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


def send_result(chat_id: int, message_id: int, text: str):
    """Envía o edita un mensaje de resultado, agregando botón compartir si hay link de vuelos."""
    gf_match = re.search(r'(https://www\.google\.com/travel/flights[^\s\)]+)', text)
    markup = share_button_markup(gf_match.group(1)) if gf_match else None
    bot.send_message(
        chat_id, text,
        parse_mode="Markdown", disable_web_page_preview=True,
        reply_markup=markup,
    )


def handle_message(chat_id, message_id, text):
    msg = bot.send_message(chat_id, random.choice(LOADING_MSGS),
                           reply_to_message_id=message_id)
    try:
        response = chat_with_ai(chat_id, text, message_id=message_id)
        if not response or response == "__pregunta_enviada__":
            try:
                bot.delete_message(chat_id, msg.message_id)
            except Exception:
                pass
            return

        # Agregar botón "Compartir" si la respuesta tiene un link de Google Flights
        gf_match = re.search(r'(https://www\.google\.com/travel/flights[^\s\)]+)', response)
        markup = share_button_markup(gf_match.group(1)) if gf_match else None

        bot.edit_message_text(
            response,
            chat_id=chat_id, message_id=msg.message_id,
            parse_mode="Markdown", disable_web_page_preview=True,
            reply_markup=markup,
        )
    except Exception:
        bot.edit_message_text(
            "Ups, algo falló 😕 Intentá de nuevo en un momento.",
            chat_id=chat_id, message_id=msg.message_id,
        )


@bot.callback_query_handler(func=lambda call: call.data.startswith("confirm:"))
def handle_confirm(call):
    action = call.data.split(":", 1)[1]
    try:
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
    except Exception:
        pass

    chat_id = call.message.chat.id

    if action == "si":
        pending = pending_searches.pop(chat_id, None)
        if not pending:
            bot.send_message(chat_id, "La búsqueda expiró 😅 Volvé a pedirla.")
            bot.answer_callback_query(call.id)
            return

        bot.send_message(chat_id, random.choice(LOADING_MSGS))
        if pending["tipo"] == "fechas":
            result = execute_buscar_fechas(**pending["params"])
        else:
            result = execute_buscar_vuelos(**pending["params"])

        send_result(chat_id, call.message.message_id, result)
    else:
        pending_searches.pop(chat_id, None)
        bot.send_message(chat_id, "Ok, ¿qué cambiamos? 🔄 Decime qué querés ajustar.",
                         parse_mode="Markdown")

    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("sorpresa:"))
def handle_sorpresa(call):
    try:
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
    except Exception:
        pass

    parts = call.data.replace("sorpresa:", "").split("-")
    if len(parts) < 2:
        bot.answer_callback_query(call.id)
        return

    origen, destino = parts[0], parts[1]
    bot.send_message(call.message.chat.id, f"👉 _Buscar vuelos a {destino}_", parse_mode="Markdown")
    handle_message(
        call.message.chat.id,
        call.message.message_id,
        f"quiero ver fechas baratas de {origen} a {destino} para los próximos 3 meses",
    )
    bot.answer_callback_query(call.id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("resp:"))
def handle_button(call):
    respuesta = call.data.replace("resp:", "")
    try:
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
    except Exception:
        pass
    bot.send_message(call.message.chat.id, f"👉 _{respuesta}_", parse_mode="Markdown")
    handle_message(call.message.chat.id, call.message.message_id, respuesta)
    bot.answer_callback_query(call.id)


@bot.message_handler(commands=["start"])
def cmd_start(message):
    chat_id = message.chat.id
    nombre = message.from_user.first_name or "viajero"
    histories.pop(chat_id, None)  # reset in-memory history

    # Guardar nombre del usuario
    save_user(chat_id, nombre=nombre)

    # Verificar si ya tiene ciudad de origen guardada
    user = get_user(chat_id)
    tiene_origen = user and user.get("ciudad_origen")

    saludo = (
        f"¡Hola, {nombre}! 👋 Soy *Flynow*, tu asistente de viajes. ✈️\n\n"
        f"Puedo ayudarte con:\n"
        f"• 🔍 Buscar vuelos baratos\n"
        f"• 📅 Encontrar las fechas más económicas\n"
        f"• 🌦️ Info sobre clima y destinos\n"
        f"• 🛂 Requisitos de visa para argentinos\n"
        f"• 🔔 Alertas cuando bajen los precios\n\n"
        f"Escribime o mandame un 🎙️ *audio* — hablame como si fuera un amigo.\n\n"
        f"¿A dónde soñás viajar? 🌍"
    )
    bot.send_message(chat_id, saludo, parse_mode="Markdown")

    # Onboarding: si es la primera vez, preguntar ciudad de origen
    if not tiene_origen:
        markup = telebot.types.InlineKeyboardMarkup()
        markup.row(
            telebot.types.InlineKeyboardButton("🏙️ Buenos Aires", callback_data="origen:EZE"),
            telebot.types.InlineKeyboardButton("🍷 Mendoza", callback_data="origen:MDZ"),
        )
        markup.row(
            telebot.types.InlineKeyboardButton("🌿 Córdoba", callback_data="origen:COR"),
            telebot.types.InlineKeyboardButton("🌊 Rosario", callback_data="origen:ROS"),
        )
        markup.row(
            telebot.types.InlineKeyboardButton("✈️ Otra ciudad", callback_data="origen:otra"),
        )
        bot.send_message(
            chat_id,
            "Antes de empezar: ¿desde qué ciudad solés volar? Así no te lo pregunto cada vez 😊",
            reply_markup=markup,
            parse_mode="Markdown",
        )


@bot.callback_query_handler(func=lambda call: call.data.startswith("origen:"))
def handle_origen(call):
    iata = call.data.replace("origen:", "")
    chat_id = call.message.chat.id
    try:
        bot.edit_message_reply_markup(chat_id, call.message.message_id, reply_markup=None)
    except Exception:
        pass

    nombres = {"EZE": "Buenos Aires", "MDZ": "Mendoza", "COR": "Córdoba", "ROS": "Rosario"}

    if iata == "otra":
        bot.send_message(chat_id, "¿Desde qué ciudad volás habitualmente? Escribime el nombre 🏙️")
    else:
        save_user(chat_id, ciudad_origen=iata)
        nombre_ciudad = nombres.get(iata, iata)
        bot.send_message(
            chat_id,
            f"¡Perfecto! Guardé *{nombre_ciudad}* como tu ciudad de origen 🏠\n"
            f"La próxima vez que busques vuelos, la uso automáticamente. ¡Ahora sí, contame a dónde querés ir! ✈️",
            parse_mode="Markdown",
        )

    bot.answer_callback_query(call.id)


@bot.message_handler(commands=["reset", "nuevo"])
def cmd_reset(message):
    histories.pop(message.chat.id, None)
    pending_searches.pop(message.chat.id, None)
    bot.reply_to(message, "Listo, empezamos de cero 🔄 ¿A dónde querés ir?")


@bot.message_handler(commands=["alertas"])
def cmd_alertas(message):
    result = execute_listar_alertas(message.chat.id)
    bot.send_message(message.chat.id, result, parse_mode="Markdown")


@bot.message_handler(commands=["help", "ayuda"])
def cmd_help(message):
    bot.send_message(
        message.chat.id,
        "✈️ *Flynow — Asistente de Viajes*\n\n"
        "Hablame como si le hablaras a un amigo, por ejemplo:\n\n"
        "• _\"quiero ir a Brasil 10 días en julio\"_\n"
        "• _\"fechas baratas de mendoza a miami\"_\n"
        "• _\"sorprendeme, no sé a dónde ir\"_\n"
        "• _\"¿necesito visa para Europa?\"_\n"
        "• _\"avisame cuando EZE-MIA baje de 400 USD\"_\n\n"
        "También podés mandarme un 🎙️ *audio* y te entiendo igual.\n\n"
        "Comandos:\n"
        "/reset — nueva conversación\n"
        "/alertas — ver alertas activas\n"
        "/ayuda — este mensaje",
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
        response = chat_with_ai(message.chat.id, text, message_id=message.message_id)
        if not response or response == "__pregunta_enviada__":
            try:
                bot.delete_message(message.chat.id, msg.message_id)
            except Exception:
                pass
            return

        gf_match = re.search(r'(https://www\.google\.com/travel/flights[^\s\)]+)', response)
        markup = share_button_markup(gf_match.group(1)) if gf_match else None

        bot.edit_message_text(
            f"🎙️ _\"{text}\"_\n\n{response}",
            chat_id=message.chat.id, message_id=msg.message_id,
            parse_mode="Markdown", disable_web_page_preview=True,
            reply_markup=markup,
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
    scheduler = BackgroundScheduler(timezone="America/Argentina/Buenos_Aires")
    scheduler.add_job(check_alertas, "interval", hours=2, id="check_alertas")
    scheduler.start()
    print("Bot iniciado con IA, alertas de precio y memoria persistente 🔔")
    bot.infinity_polling()
