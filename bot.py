import os
import re
import subprocess
import sys
from datetime import datetime, timedelta
import telebot

TOKEN = os.environ["BOT_TOKEN"]
bot = telebot.TeleBot(TOKEN)

HELP_TEXT = """
✈️ *Buscador de Vuelos* — Comandos:

*/vuelos* `ORIGEN DESTINO FECHA [VUELTA]`
Vuelos en fecha específica.
Ej: `/vuelos MDZ EZE 2026-04-15`
Ej: `/vuelos MDZ EZE 2026-04-15 2026-04-20` _(ida y vuelta)_

*/fechas* `ORIGEN DESTINO [DIAS] [DURACION]`
Fechas más baratas en los próximos meses.
Ej: `/fechas MDZ EZE`
Ej: `/fechas MDZ BCN 90 7` _(rango 90 días, viaje 7 días)_

Códigos de aeropuertos comunes:
`EZE` Ezeiza · `AEP` Aeroparque · `MDZ` Mendoza
`BCN` Barcelona · `MAD` Madrid · `MIA` Miami · `JFK` New York
"""


def strip_ansi(text):
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    return ansi_escape.sub('', text)


def run_fli(args: list[str], timeout=60) -> str:
    try:
        result = subprocess.run(
            [sys.executable, "-m", "flights"] + args,
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
    """Keep only the table section, drop the ASCII chart."""
    lines = raw.splitlines()
    in_table = False
    table_lines = []
    for line in lines:
        if "Cheapest Dates" in line or "Flight Results" in line or ("│" in line and "─" not in line and line.count("│") >= 3):
            in_table = True
        if in_table:
            table_lines.append(line)
    return "\n".join(table_lines) if table_lines else raw


@bot.message_handler(commands=["start", "help", "ayuda"])
def cmd_help(message):
    bot.send_message(message.chat.id, HELP_TEXT, parse_mode="Markdown")


@bot.message_handler(commands=["vuelos"])
def cmd_vuelos(message):
    parts = message.text.split()[1:]  # drop /vuelos
    if len(parts) < 3:
        bot.reply_to(message, "Uso: `/vuelos ORIGEN DESTINO FECHA [VUELTA]`\nEj: `/vuelos MDZ EZE 2026-04-15`", parse_mode="Markdown")
        return

    origen, destino, fecha_ida = parts[0].upper(), parts[1].upper(), parts[2]
    cmd = ["flights", origen, destino, fecha_ida]

    if len(parts) >= 4:
        cmd += ["--return", parts[3]]

    cmd += ["--sort", "CHEAPEST"]

    msg = bot.reply_to(message, "🔍 Buscando vuelos...")
    result = run_fli(["flights", origen, destino, fecha_ida] + (["--return", parts[3]] if len(parts) >= 4 else []) + ["--sort", "CHEAPEST"])
    output = format_output(result)

    if not output:
        output = "No se encontraron vuelos para esa ruta y fecha."

    bot.edit_message_text(
        f"✈️ *{origen} → {destino}* — {fecha_ida}\n\n```\n{output[:3800]}\n```",
        chat_id=message.chat.id,
        message_id=msg.message_id,
        parse_mode="Markdown",
    )


@bot.message_handler(commands=["fechas"])
def cmd_fechas(message):
    parts = message.text.split()[1:]
    if len(parts) < 2:
        bot.reply_to(message, "Uso: `/fechas ORIGEN DESTINO [DIAS] [DURACION]`\nEj: `/fechas MDZ BCN 90 7`", parse_mode="Markdown")
        return

    origen, destino = parts[0].upper(), parts[1].upper()
    dias = int(parts[2]) if len(parts) >= 3 else 60
    duracion = int(parts[3]) if len(parts) >= 4 else 3

    desde = datetime.today().strftime("%Y-%m-%d")
    hasta = (datetime.today() + timedelta(days=dias)).strftime("%Y-%m-%d")

    msg = bot.reply_to(message, f"🔍 Buscando fechas baratas {origen} → {destino}...")
    result = run_fli(["dates", origen, destino, "--from", desde, "--to", hasta, "--duration", str(duracion), "--round", "--sort"])
    output = format_output(result)

    if not output:
        output = "No se encontraron resultados."

    bot.edit_message_text(
        f"📅 *{origen} → {destino}* — próximos {dias} días, {duracion} noches\n\n```\n{output[:3800]}\n```",
        chat_id=message.chat.id,
        message_id=msg.message_id,
        parse_mode="Markdown",
    )


@bot.message_handler(func=lambda m: True)
def fallback(message):
    bot.reply_to(message, "No entendí. Usá /help para ver los comandos disponibles.")


if __name__ == "__main__":
    print("Bot iniciado...")
    bot.infinity_polling()
