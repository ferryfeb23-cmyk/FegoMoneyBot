"""
FegoMoney Bot - Bot Keuangan Ferry Febrian
Telegram: @FegoMoney_bot
"""
import os, json, re, base64, logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)
import anthropic
import gspread
from google.oauth2.service_account import Credentials

logging.basicConfig(
    format='%(asctime)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ── CONFIG ─────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN    = os.environ['TELEGRAM_TOKEN']
ANTHROPIC_API_KEY = os.environ['ANTHROPIC_API_KEY']
GOOGLE_SHEET_ID   = os.environ['GOOGLE_SHEET_ID']
ALLOWED_USER_ID   = int(os.environ.get('ALLOWED_USER_ID', '0'))

# ── GOOGLE SHEETS ──────────────────────────────────────────────────────────
def get_sheet():
    creds_json = json.loads(os.environ['GOOGLE_CREDENTIALS'])
    creds = Credentials.from_service_account_info(
        creds_json,
        scopes=['https://www.googleapis.com/auth/spreadsheets']
    )
    gc = gspread.authorize(creds)
    return gc.open_by_key(GOOGLE_SHEET_ID)

def get_ws(sheet, name='Input Transaksi'):
    try:
        return sheet.worksheet(name)
    except:
        ws = sheet.add_worksheet(title=name, rows=500, cols=13)
        ws.append_row(['Tanggal','Hari','Waktu','Bulan','Jenis','Kategori',
                       'Sub-Kategori','Keterangan','Pihak','Jumlah',
                       'Saldo','Rekening','Catatan'])
        return ws

# ── ANTHROPIC ──────────────────────────────────────────────────────────────
claude = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

HARI_MAP = {0:'Senin',1:'Selasa',2:'Rabu',3:'Kamis',
            4:'Jumat',5:'Sabtu',6:'Minggu'}

PARSE_PROMPT = """Kamu adalah asisten keuangan Ferry Febrian di Manokwari, Papua Barat.

KONTEKS BISNIS FERRY:
- Bisnis Top Up Games: modal ke Naim Store/Takapedia → pemasukan dari Tauhid Riski/CIRCLEF
- Jualan Akun Game: modal ke supplier akun → pemasukan dari buyer (Nico Martan, Juan Lahinta, Kelvin, Didan, dll)
- Gaji Pos: pemasukan dari Kantor Pos tiap awal bulan
- Proyek Kasuari Positif: modal dari Trias Santosa, biaya ke Yudistira/Buzzerpanel/Josua/dll
- Keperluan Naomi: bayi (susu, popok, baju, mainan)
- Keperluan Kalila: anak kuliah (uang kuliah, transport, jajan)
- Piutang aktif: Erwin Rp 200rb (10 Jun), Nico sisa Rp 346rb (15 Jun), Kelvin sisa Rp 1.3jt (7 Jul)

ATURAN KATEGORISASI:
- "modal top up / modal usaha top up" → Pengeluaran, Bisnis / Usaha
- "terima top up / bayar top up / QRIS top up" → Pemasukan, Bisnis / Usaha  
- "modal akun / beli akun" → Pengeluaran, Bisnis / Usaha
- "jual akun / hasil akun / cicilan akun" → Pemasukan, Bisnis / Usaha
- "modal proyek / kasuari / buzzerpanel / buzzer" → Pengeluaran, Bisnis / Usaha
- "gaji / pengkreditan" → Pemasukan, Gaji / Tunjangan
- "token listrik / PLN" → Pengeluaran, Kebutuhan Sehari-hari
- "paket data / pulsa" → Pengeluaran, Pulsa / Internet / Digital
- "transfer ke rekening sendiri" → ABAIKAN, tidak perlu dicatat

Kembalikan HANYA JSON valid (tanpa teks lain):
{
  "transaksi": [
    {
      "tanggal": "DD/MM",
      "jenis": "Pengeluaran atau Pemasukan",
      "kategori": "kategori sesuai list",
      "sub_kategori": "sub kategori",
      "keterangan": "deskripsi singkat",
      "pihak": "nama toko atau orang",
      "jumlah": 150000,
      "rekening": "BCA 8315136187 atau GoPay atau DANA atau Mandiri atau Tunai",
      "catatan": "info tambahan"
    }
  ],
  "ringkasan": "ringkasan singkat"
}

Kategori Pengeluaran: Kebutuhan Sehari-hari, Keperluan Naomi, Keperluan Kalila, Uang Makan, Transportasi, Pulsa / Internet / Digital, Investasi / Tabungan, Transfer / Utang Dibayar, Kesehatan, Hiburan / Game, Biaya Bank / Admin, Belanja Online, Pendidikan, Bisnis / Usaha, Lain-lain Pengeluaran

Kategori Pemasukan: Gaji / Tunjangan, Bisnis / Usaha, Desain / Freelance, Transfer Masuk / Utang, Bonus / Cashback, Lain-lain Pemasukan"""


async def parse_text(text: str) -> dict:
    resp = claude.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1000,
        messages=[{"role":"user","content":f"{PARSE_PROMPT}\n\nInput: {text}"}]
    )
    raw = re.sub(r'```json|```','', resp.content[0].text).strip()
    return json.loads(raw)


async def parse_image(image_bytes: bytes) -> dict:
    b64 = base64.standard_b64encode(image_bytes).decode()
    resp = claude.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1500,
        messages=[{"role":"user","content":[
            {"type":"image","source":{"type":"base64","media_type":"image/jpeg","data":b64}},
            {"type":"text","text":PARSE_PROMPT}
        ]}]
    )
    raw = re.sub(r'```json|```','', resp.content[0].text).strip()
    return json.loads(raw)


def rp(n): return f"Rp {n:,}".replace(',','.')
def usd(n): return f"${n/18089.5:.2f}"


def save_transactions(tx_list: list) -> int:
    sheet = get_sheet()
    ws = get_ws(sheet)
    now = datetime.now()
    saved = 0

    for tx in tx_list:
        try:
            tgl = tx.get('tanggal', now.strftime('%d/%m'))
            try:
                d,m = tgl.split('/')
                dt = datetime(now.year, int(m), int(d))
                hari = HARI_MAP[dt.weekday()]
                bulan = dt.strftime('%B %Y').replace(
                    'January','Januari').replace('February','Februari'
                    ).replace('March','Maret').replace('May','Mei'
                    ).replace('June','Juni').replace('July','Juli'
                    ).replace('August','Agustus').replace('October','Oktober'
                    ).replace('November','November').replace('December','Desember')
            except:
                hari = HARI_MAP[now.weekday()]
                bulan = 'Juni 2026'
                tgl = now.strftime('%d/%m')

            ws.append_row([
                tgl, hari, now.strftime('%H:%M'), bulan,
                tx.get('jenis',''), tx.get('kategori',''),
                tx.get('sub_kategori',''), tx.get('keterangan',''),
                tx.get('pihak',''), tx.get('jumlah',0),
                '', tx.get('rekening','BCA 8315136187'),
                tx.get('catatan','')
            ])
            saved += 1
        except Exception as e:
            logger.error(f"Save error: {e}")
    return saved


def get_summary() -> str:
    try:
        sheet = get_sheet()
        ws = get_ws(sheet)
        records = ws.get_all_records()

        tot_pem = sum(r.get('Jumlah',0) for r in records if r.get('Jenis')=='Pemasukan')
        tot_pen = sum(r.get('Jumlah',0) for r in records if r.get('Jenis')=='Pengeluaran')
        net = tot_pem - tot_pen
        cnt = len(records)

        # Top up
        tu_pem = sum(r.get('Jumlah',0) for r in records
                     if r.get('Jenis')=='Pemasukan' and
                     any(k in str(r.get('Keterangan','')).lower()
                         for k in ['top up','circlef','tauhid']))
        tu_mod = sum(r.get('Jumlah',0) for r in records
                     if r.get('Jenis')=='Pengeluaran' and
                     any(k in str(r.get('Keterangan','')).lower()
                         for k in ['modal top up','modal usaha top']))

        # Jualan akun
        ak_pem = sum(r.get('Jumlah',0) for r in records
                     if r.get('Jenis')=='Pemasukan' and
                     any(k in str(r.get('Keterangan','')).lower()
                         for k in ['jual akun','akun sultan','akun ml','cicilan akun']))
        ak_mod = sum(r.get('Jumlah',0) for r in records
                     if r.get('Jenis')=='Pengeluaran' and
                     any(k in str(r.get('Keterangan','')).lower()
                         for k in ['modal akun','modal beli akun','beli akun']))

        return (
            f"📊 *RINGKASAN JUNI 2026*\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"✅ Pemasukan: *{rp(tot_pem)}*\n"
            f"   ≈ {usd(tot_pem)}\n"
            f"❌ Pengeluaran: *{rp(tot_pen)}*\n"
            f"   ≈ {usd(tot_pen)}\n"
            f"💰 Net Profit: *{rp(net)}*\n"
            f"   ≈ {usd(net)}\n"
            f"📝 Transaksi: *{cnt}*\n\n"
            f"🎮 *TOP UP GAMES*\n"
            f"   Masuk: {rp(tu_pem)}\n"
            f"   Modal: {rp(tu_mod)}\n"
            f"   Profit: *{rp(tu_pem-tu_mod)}*\n\n"
            f"🕹️ *JUALAN AKUN*\n"
            f"   Masuk: {rp(ak_pem)}\n"
            f"   Modal: {rp(ak_mod)}\n"
            f"   Profit: *{rp(ak_pem-ak_mod)}*\n\n"
            f"⚠️ *PIUTANG AKTIF*\n"
            f"   Erwin: {rp(200000)} → 10 Jun\n"
            f"   Nico: {rp(346000)} → 15 Jun\n"
            f"   Kelvin: {rp(1300000)} → 7 Jul\n"
            f"   Total: *{rp(1846000)}*"
        )
    except Exception as e:
        return f"❌ Error ambil data: {e}"


def get_today() -> str:
    try:
        sheet = get_sheet()
        ws = get_ws(sheet)
        records = ws.get_all_records()
        today = datetime.now().strftime('%d/%m')
        today_tx = [r for r in records if r.get('Tanggal')==today]

        if not today_tx:
            return f"📅 Belum ada transaksi hari ini ({today})."

        text = f"📅 *Transaksi {today}:*\n\n"
        pem = pen = 0
        for r in today_tx:
            e = "🟢" if r.get('Jenis')=='Pemasukan' else "🔴"
            text += f"{e} {rp(r.get('Jumlah',0))} — {str(r.get('Keterangan',''))[:25]}\n"
            if r.get('Jenis')=='Pemasukan': pem += r.get('Jumlah',0)
            else: pen += r.get('Jumlah',0)

        text += f"\n✅ Masuk: *{rp(pem)}*\n❌ Keluar: *{rp(pen)}*"
        return text
    except Exception as e:
        return f"❌ Error: {e}"


def fmt_tx(tx: dict) -> str:
    e = "🟢" if tx.get('jenis')=='Pemasukan' else "🔴"
    return (
        f"{e} *{tx.get('jenis','-')}*\n"
        f"📅 {tx.get('tanggal','-')}\n"
        f"💰 {rp(tx.get('jumlah',0))} ≈ {usd(tx.get('jumlah',0))}\n"
        f"🏷 {tx.get('kategori','-')}\n"
        f"📝 {tx.get('keterangan','-')}\n"
        f"👤 {tx.get('pihak','-')}\n"
        f"🏦 {tx.get('rekening','-')}"
    )


def is_auth(update: Update) -> bool:
    if ALLOWED_USER_ID == 0: return True
    return update.effective_user.id == ALLOWED_USER_ID


# ── HANDLERS ───────────────────────────────────────────────────────────────

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_auth(update): return
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Ringkasan",callback_data="summary"),
         InlineKeyboardButton("📅 Hari Ini",callback_data="today")],
        [InlineKeyboardButton("⚠️ Piutang",callback_data="piutang"),
         InlineKeyboardButton("❓ Cara Pakai",callback_data="help")],
    ])
    await update.message.reply_text(
        "💰 *FEGO MONEY BOT*\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "Halo Ferry! Bot siap mencatat keuangan.\n\n"
        "*Cara input:*\n"
        "📸 Foto nota → otomatis terbaca\n"
        "✍️ Ketik transaksi → langsung diproses\n\n"
        "*Contoh ketik:*\n"
        "`beli makan 35rb BCA`\n"
        "`modal top up naim store 170rb`\n"
        "`terima bayar akun sultan nico 5.154jt`\n"
        "`token listrik 200rb`",
        parse_mode='Markdown', reply_markup=kb
    )


async def handle_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_auth(update): return
    msg = await update.message.reply_text("📸 Membaca nota...")
    try:
        photo = update.message.photo[-1]
        f = await photo.get_file()
        img = await f.download_as_bytearray()
        result = await parse_image(bytes(img))
        txs = result.get('transaksi', [])
        if not txs:
            await msg.edit_text("❌ Tidak bisa baca nota. Coba foto lebih jelas atau ketik manual.")
            return
        ctx.user_data['pending'] = txs
        preview = f"📋 *{len(txs)} transaksi ditemukan:*\n\n"
        for i,tx in enumerate(txs):
            preview += f"*{i+1}.* {fmt_tx(tx)}\n\n"
        if result.get('ringkasan'):
            preview += f"_{result['ringkasan']}_\n\n"
        preview += "Simpan semua?"
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Simpan",callback_data="save_all"),
            InlineKeyboardButton("❌ Batal",callback_data="cancel"),
        ]])
        await msg.edit_text(preview, parse_mode='Markdown', reply_markup=kb)
    except Exception as e:
        logger.error(f"Photo error: {e}")
        await msg.edit_text(f"❌ Error: {str(e)[:100]}")


async def handle_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_auth(update): return
    text = update.message.text
    if text.startswith('/') or len(text) < 4: return
    msg = await update.message.reply_text("⏳ Memproses...")
    try:
        result = await parse_text(text)
        txs = result.get('transaksi', [])
        if not txs:
            await msg.edit_text(
                "❌ Tidak bisa parse.\n\nContoh:\n"
                "`beli makan 35rb BCA`\n`modal top up 150rb`",
                parse_mode='Markdown'
            )
            return
        ctx.user_data['pending'] = txs
        if len(txs) == 1:
            preview = f"*Transaksi:*\n\n{fmt_tx(txs[0])}"
        else:
            preview = f"*{len(txs)} transaksi:*\n\n"
            for i,tx in enumerate(txs):
                preview += f"*{i+1}.* {fmt_tx(tx)}\n\n"
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Simpan",callback_data="save_all"),
            InlineKeyboardButton("❌ Batal",callback_data="cancel"),
        ]])
        await msg.edit_text(preview, parse_mode='Markdown', reply_markup=kb)
    except Exception as e:
        logger.error(f"Text error: {e}")
        await msg.edit_text(f"❌ Error: {str(e)[:100]}")


async def handle_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    d = q.data

    if d == "summary":
        await q.edit_message_text(get_summary(), parse_mode='Markdown')

    elif d == "today":
        await q.edit_message_text(get_today(), parse_mode='Markdown')

    elif d == "piutang":
        text = (
            "⚠️ *PIUTANG AKTIF*\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "🔴 *Erwin* — Rp 200.000\n"
            "   Jatuh tempo: *10 Juni 2026*\n\n"
            "🟡 *Nico Martan* — Rp 346.000\n"
            "   Sisa dari deal Rp 5.500.000\n"
            "   Jatuh tempo: *15 Juni 2026*\n\n"
            "🟢 *Kelvin (Akun Apip)* — Rp 1.300.000\n"
            "   DP Rp 1.100.000 sudah masuk\n"
            "   Jatuh tempo: *07 Juli 2026*\n\n"
            "💰 *Total outstanding: Rp 1.846.000*"
        )
        await q.edit_message_text(text, parse_mode='Markdown')

    elif d == "help":
        await q.edit_message_text(
            "❓ *CARA PAKAI*\n\n"
            "*Foto Nota:*\n"
            "Langsung foto & kirim → bot baca otomatis\n\n"
            "*Ketik Transaksi:*\n"
            "`beli makan siang 45rb BCA`\n"
            "`modal top up naim store 170rb`\n"
            "`terima bayar top up tauhid 409900`\n"
            "`modal akun sultan gopay 4jt`\n"
            "`jual akun nico 5.154jt masuk`\n"
            "`token listrik 200rb BCA`\n"
            "`paket data telkomsel 150rb gopay`\n\n"
            "*Perintah:*\n"
            "/start - Menu utama\n"
            "/ringkasan - Ringkasan bulan ini\n"
            "/hari\\_ini - Transaksi hari ini\n"
            "/piutang - Daftar piutang",
            parse_mode='Markdown'
        )

    elif d == "save_all":
        pending = ctx.user_data.get('pending', [])
        if not pending:
            await q.edit_message_text("❌ Tidak ada transaksi pending.")
            return
        await q.edit_message_text("💾 Menyimpan ke Google Sheets...")
        saved = save_transactions(pending)
        ctx.user_data['pending'] = []
        total = sum(tx.get('jumlah',0) for tx in pending)
        e = "🟢" if pending[0].get('jenis')=='Pemasukan' else "🔴"
        await q.edit_message_text(
            f"✅ *{saved} transaksi tersimpan!*\n\n"
            f"{e} Total: *{rp(total)}* ≈ {usd(total)}\n\n"
            f"Ketik /ringkasan untuk lihat semua.",
            parse_mode='Markdown'
        )

    elif d == "cancel":
        ctx.user_data['pending'] = []
        await q.edit_message_text("❌ Dibatalkan.")


async def cmd_ringkasan(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_auth(update): return
    msg = await update.message.reply_text("⏳ Mengambil data...")
    await msg.edit_text(get_summary(), parse_mode='Markdown')


async def cmd_today(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_auth(update): return
    await update.message.reply_text(get_today(), parse_mode='Markdown')


async def cmd_piutang(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_auth(update): return
    text = (
        "⚠️ *PIUTANG AKTIF*\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "🔴 *Erwin* — Rp 200.000 → 10 Jun\n"
        "🟡 *Nico Martan* — Rp 346.000 → 15 Jun\n"
        "🟢 *Kelvin* — Rp 1.300.000 → 07 Jul\n\n"
        "💰 *Total: Rp 1.846.000*"
    )
    await update.message.reply_text(text, parse_mode='Markdown')


def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ringkasan", cmd_ringkasan))
    app.add_handler(CommandHandler("hari_ini", cmd_today))
    app.add_handler(CommandHandler("piutang", cmd_piutang))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(CallbackQueryHandler(handle_callback))
    logger.info("FegoMoney Bot started!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()
