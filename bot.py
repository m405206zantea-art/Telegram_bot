bot.py
# bot.py (shorter, cleaned, admin-first-only, self-update)
import os, sys, json, random, time, re, traceback
from pathlib import Path
from datetime import datetime, timedelta
from telegram import (
    Update, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove,
    InlineKeyboardMarkup, InlineKeyboardButton
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes,
    filters, CallbackQueryHandler
)

# ---------------- CONFIG (put token here) ----------------
BOT_TOKEN = "8326540330:AAE6csPLQ0fKc-QVqa0DOGiC3gMlpW3JUxw"
DATA = Path("data"); DATA.mkdir(exist_ok=True)
POINTS_F = DATA / "points.json"
CFG_F = DATA / "config.json"
PENDING_F = DATA / "pending.json"
BUTTONS_F = DATA / "buttons.json"
STATE_F = DATA / "state.json"
BLOCK_F = DATA / "blocked.json"

DEFAULT_CFG = {
    "admin_id": None,               # will be set on first /start
    "lottery_points": 1000,
    "hint_cost": 30,
    "invite_reward": 50,
    "max_fake": 3,
    "purchase_plans": {"50":15000,"100":30000,"200":60000},
    "premium": {
        "p1": {"name":"پرمیوم 1 ماهه","price":90000,"points":500,"days":30},
        "p3": {"name":"پرمیوم 3 ماهه","price":250000,"points":1500,"days":90},
        "plife": {"name":"پرمیوم دائمی","price":500000,"points":0,"days":0}
    },
    "admin_card": "0000-0000-0000-0000",
    "win_points": 10,
    "loss_points": -5,
    "max_attempts": 10
}

# optional OCR
USE_OCR = False
try:
    from PIL import Image
    import pytesseract
    USE_OCR = True
except Exception:
    USE_OCR = False

# ---------------- storage helpers ----------------
def load(p, d): 
    try:
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
    except: pass
    return d

def save(p, d):
    p.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")

points = load(POINTS_F, {})
cfg = load(CFG_F, DEFAULT_CFG)
pending = load(PENDING_F, {})
buttons = load(BUTTONS_F, {})
state = load(STATE_F, {})    # game state {uid: {"num":int,"attempts":int}}
blocked = load(BLOCK_F, [])

# runtime only
fake_count = {}
forward_map = {}  # forwarded admin_msg_id -> original_user_id

# ---------------- utilities ----------------
def ensure_user(uid, uname):
    s = str(uid)
    if s not in points:
        points[s] = {"username": uname, "points": 0, "invited_by": None, "invites": [], "premium_until": None}
        save(POINTS_F, points)

def add_points(uid, uname, pts):
    ensure_user(uid, uname)
    points[str(uid)]["points"] = points[str(uid)].get("points",0) + int(pts)
    save(POINTS_F, points)

def set_admin_id(uid):
    if cfg.get("admin_id") is None:
        cfg["admin_id"] = int(uid); save(CFG_F, cfg); return True
    return False

def is_admin(uid): return cfg.get("admin_id") == int(uid)

def get_top(n=5):
    items = sorted(points.items(), key=lambda kv: kv[1].get("points",0), reverse=True)
    return items[:n]

def is_premium(uid):
    p = points.get(str(uid),{}).get("premium_until")
    if not p: return False
    if p == "perm": return True
    try: return datetime.utcnow() < datetime.fromisoformat(p)
    except: return False

def give_premium(uid, uname, key):
    plan = cfg.get("premium",{}).get(key)
    if not plan: return False
    ensure_user(uid, uname)
    pts = plan.get("points",0)
    if pts: add_points(uid, uname, pts)
    days = plan.get("days",0)
    if days==0: points[str(uid)]["premium_until"]="perm"
    else: points[str(uid)]["premium_until"]=(datetime.utcnow()+timedelta(days=int(days))).isoformat()
    save(POINTS_F, points); return True

# ---------------- keyboards ----------------
def main_kb():
    kb = [
        ["🎯 شروع بازی","💡 راهنما"],
        ["🏆 امتیاز من","🔝 ۵ نفر برتر"],
        ["💳 خرید امتیاز","💎 خرید پرمیوم"],
        ["📨 لینک دعوت من","📩 تماس با پشتیبانی"],
        ["🎲 بازی شانسی (به زودی...)","🤖 هوش مصنوعی (به زودی...)"]
    ]
    for b in buttons.keys():
        kb.append([b])
    return ReplyKeyboardMarkup(kb, resize_keyboard=True)

def admin_kb():
    kb = [
        ["📊 لیست کاربران","🧾 پرداخت‌های معلق"],
        ["💳 تغییر شماره کارت","⚙️ تنظیمات"],
        ["➕ اضافه دکمه","🏷️ دادن پرمیوم دستی"],
        ["🔄 آپدیت ربات (ارسال فایل)","❌ بلاک کاربر"],
        ["🏁 منوی اصلی"]
    ]
    return ReplyKeyboardMarkup(kb, resize_keyboard=True)

# ---------------- handlers ----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    uid = user.id
    uname = user.username or f"user{uid}"
    # referral: /start ref<id>
    ref = context.args[0] if context.args else None
    if ref and ref.startswith("ref"):
        inviter = ref[3:]
        if inviter in points and inviter != str(uid):
            if not points[str(uid)].get("invited_by"):
                points[str(uid)]["invited_by"]=inviter
                points[inviter].setdefault("invites",[]); points[inviter]["invites"].append(str(uid))
                save(POINTS_F, points)
                add_points(int(inviter), points[inviter]["username"], cfg.get("invite_reward",50))
    ensure_user(uid, uname)
    # set admin only if not set
    if cfg.get("admin_id") is None:
        cfg["admin_id"] = uid; save(CFG_F, cfg)
        await update.message.reply_text("📢 شما مدیر ربات شدید و اکنون می‌توانید تنظیمات را کنترل کنید.")
    await context.bot.send_message(chat_id=uid, text="منوی اصلی:", reply_markup=main_kb())

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user: return
    uid = user.id; sid = str(uid)
    if uid in blocked:
        await update.message.reply_text("⛔ حساب شما مسدود شده.")
        return
    txt = (update.message.text or "").strip()
    # admin menu open
    if txt == "/admin" and is_admin(uid):
        await context.bot.send_message(chat_id=uid, text="پنل مدیریت:", reply_markup=admin_kb()); return

    # admin-only workflows
    if is_admin(uid):
        ud = context.user_data
        if ud.get("expect_card"):
            cfg["admin_card"] = txt; save(CFG_F, cfg); ud["expect_card"]=False
            await update.message.reply_text(f"✅ شماره کارت بروز شد: {cfg['admin_card']}"); return
        if ud.get("adding_button"):
            name = txt; ud["adding_button"]=False; ud["adding_response"]=True; ud["new_button_name"]=name
            await update.message.reply_text("متن پاسخ برای دکمه را ارسال کنید:"); return
        if ud.get("adding_response"):
            resp = txt; name = ud.pop("new_button_name"); ud["adding_response"]=False
            buttons[name]=resp; save(BUTTONS_F, buttons); await update.message.reply_text(f"✅ دکمه '{name}' اضافه شد."); return
        if ud.get("expect_block"):
            ud["expect_block"]=False; target = txt.lstrip("@")
            found = None
            for k,v in points.items():
                if v.get("username")==target: found=int(k); break
            try:
                if found is None: found=int(target)
            except: found=None
            if found: block_user(found); await update.message.reply_text("✅ بلاک شد")
            else: await update.message.reply_text("کاربر یافت نشد")
            return
        # admin menu choices
        if txt == "📊 لیست کاربران":
            lines=[f"@{v.get('username')} ({k}) → {v.get('points',0)}" for k,v in points.items()]
            await update.message.reply_text("\n".join(lines) if lines else "هیچ کاربری ثبت نشده"); return
        if txt == "🧾 پرداخت‌های معلق":
            if not pending: await update.message.reply_text("پرداخت معلقی وجود ندارد"); return
            for pid,p in pending.items():
                cap=f"ID:{pid}\n@{p['username']} ({p['user_id']})\nPlan:{p.get('plan_name',p.get('plan_points'))} — {p['plan_price']:,} T\nStatus:{p['status']}"
                if p.get("photo") and Path(p["photo"]).exists():
                    await context.bot.send_photo(chat_id=uid, photo=open(p["photo"],"rb"), caption=cap,
                                                 reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅",callback_data=f"approve|{pid}"),InlineKeyboardButton("❌",callback_data=f"reject|{pid}")]]))
                else:
                    await update.message.reply_text(cap, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅",callback_data=f"approve|{pid}"),InlineKeyboardButton("❌",callback_data=f"reject|{pid}")]]))
            return
        if txt == "💳 تغییر شماره کارت":
            context.user_data["expect_card"]=True; await update.message.reply_text(f"شماره کارت فعلی: {cfg.get('admin_card')}\nلطفا شماره جدید را ارسال کنید:"); return
        if txt == "➕ اضافه دکمه":
            context.user_data["adding_button"]=True; await update.message.reply_text("نام دکمه را ارسال کنید:"); return
        if txt == "🏷️ دادن پرمیوم دستی":
            context.user_data["expect_premium_user"]=True; await update.message.reply_text("آیدی یا یوزرنیم را ارسال کنید:"); return
        if txt == "🔄 آپدیت ربات (ارسال فایل)":
            context.user_data["expect_update"]=True; await update.message.reply_text("فایل .py را ارسال کنید (document)."); return
        if txt == "❌ بلاک کاربر":
            context.user_data["expect_block"]=True; await update.message.reply_text("آیدی یا @username را وارد کنید:"); return
        if txt == "🏁 منوی اصلی":
            await context.bot.send_message(chat_id=uid, text="منوی اصلی مدیریت:", reply_markup=admin_kb()); return

    # user menu & actions
    if txt in buttons:
        await update.message.reply_text(buttons[txt]); return
    if txt == "🎯 شروع بازی":
        state[sid] = {"num": random.randint(1,100), "attempts":0}; save(STATE_F, state); await update.message.reply_text("بازی شروع شد! یک عدد بین 1 و 100 بفرست."); return
    if txt == "💡 راهنما":
        ensure_user(uid, user.username or f"user{uid}")
        if points.get(sid,{}).get("points",0) < cfg.get("hint_cost",30): await update.message.reply_text("امتیاز کافی نداری"); return
        points[sid]["points"] -= cfg.get("hint_cost",30); save(POINTS_F, points)
        if sid not in state: state[sid]={"num":random.randint(1,100),"attempts":0}
        n = state[sid]["num"]; low=max(1,n-10); high=min(100,n+10)
        await update.message.reply_text(f"💡 راهنما: بین {low} تا {high} (هزینه {cfg.get('hint_cost')} امتیاز)"); return
    if txt == "🏆 امتیاز من":
        ensure_user(uid, user.username or f"user{uid}"); p = points.get(sid,{}).get("points",0)
        await update.message.reply_text(f"امتیاز: {p}\nپرمیوم: {'فعال' if is_premium(uid) else 'غیرفعال'}"); return
    if txt == "🔝 ۵ نفر برتر":
        tops = get_top(5); lines=[f"{i+1}. @{v['username']} → {v.get('points',0)}" for i,(k,v) in enumerate(tops)]
        await update.message.reply_text("🔝 ۵ نفر برتر:\n" + ("\n".join(lines) if lines else "هیچکس")); return
    if txt == "📨 لینک دعوت من":
        code=f"ref{sid}"; me=await context.bot.get_me(); await update.message.reply_text(f"https://t.me/{me.username}?start={code}"); return
    if txt == "📩 تماس با پشتیبانی":
        await update.message.reply_text("پیام خود را ارسال کنید؛ به پشتیبانی فوروارد می‌شود."); return
    if txt == "💳 خرید امتیاز":
        kb=[] 
        for pts,pr in cfg.get("purchase_plans",{}).items(): kb.append([InlineKeyboardButton(f"{pts} pts — {pr:,} T", callback_data=f"buy|{pts}")])
        kb.append([InlineKeyboardButton("خرید پرمیوم", callback_data="buy_premium")])
        kb.append([InlineKeyboardButton("بازگشت", callback_data="menu|main")])
        await update.message.reply_text("پلن‌ها:", reply_markup=InlineKeyboardMarkup(kb)); return
    if txt == "💎 خرید پرمیوم":
        kb=[]
        for key,p in cfg.get("premium",{}).items(): kb.append([InlineKeyboardButton(f"{p['name']} — {p['price']:,} T", callback_data=f"prem|{key}")])
        kb.append([InlineKeyboardButton("بازگشت", callback_data="menu|main")])
        await update.message.reply_text("پرمیوم‌ها:", reply_markup=InlineKeyboardMarkup(kb)); return

    # "be soon" buttons
    if "به زودی" in txt or "به‌زودی" in txt:
        await update.message.reply_text("این قابلیت به زودی اضافه میشه 😏"); return

    # if numeric and have active game => guess
    if sid in state and txt.isdigit():
        await guess_handler(update, context); return

    # otherwise forward to admin as support
    if not is_admin(uid):
        try:
            fwd = await context.bot.forward_message(chat_id=cfg.get("admin_id"), from_chat_id=update.effective_chat.id, message_id=update.message.message_id)
            forward_map[fwd.message_id] = update.effective_user.id
            await update.message.reply_text("پیام به پشتیبانی ارسال شد؛ منتظر پاسخ باشید.")
        except:
            await update.message.reply_text("خطا در ارسال به پشتیبانی.")
    else:
        await update.message.reply_text("دستور نامعتبر یا وضعیت نامشخص. از منوی مدیریت استفاده کنید.")

# ---------------- guess processing ----------------
async def guess_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user = update.effective_user; uid=user.id; sid=str(uid)
        if sid not in state: state[sid]={"num":random.randint(1,100),"attempts":0}
        n = state[sid]["num"]; state[sid]["attempts"] += 1; save(STATE_F,state)
        g = int(update.message.text.strip())
        mult = 2 if is_premium(uid) else 1
        if g < n: await update.message.reply_text("⬆️ عدد بالاتر است!")
        elif g > n: await update.message.reply_text("⬇️ عدد پایین‌تر است!")
        else:
            pts = int(cfg.get("win_points",10))*mult; add_points(uid, user.username or f"user{uid}", pts)
            await update.message.reply_text(f"🎯 درست! +{pts} امتیاز")
            # notify admin if reached lottery threshold
            if points.get(str(uid),{}).get("points",0) >= cfg.get("lottery_points",1000):
                try: await context.bot.send_message(chat_id=cfg.get("admin_id"), text=f"📢 @{user.username} به قرعه‌کشی رسید!")
                except: pass
            state[sid]={"num":random.randint(1,100),"attempts":0}; save(STATE_F,state); return
        # attempts limit
        if state[sid]["attempts"] >= cfg.get("max_attempts",10):
            add_points(uid, user.username or f"user{uid}", cfg.get("loss_points",-5))
            await update.message.reply_text(f"❌ باختی! عدد {n} بود. {cfg.get('loss_points')} امتیاز کم شد.")
            state[sid]={"num":random.randint(1,100),"attempts":0}; save(STATE_F,state)
    except Exception as e:
        await update.message.reply_text("خطا در پردازش حدس."); print("guess err",e); traceback.print_exc()

# ---------------- callbacks inline ----------------
async def callback_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q=update.callback_query; await q.answer(); data=q.data or ""; user=q.from_user
    if data.startswith("buy|"):
        _,pts=data.split("|",1); price=cfg.get("purchase_plans",{}).get(pts)
        if not price: await q.edit_message_text("پلن نامعتبر"); return
        pid=str(int(time.time()*1000))
        pending[pid]={"user_id":user.id,"username":user.username or f"user{user.id}","plan_points":int(pts),"plan_price":int(price),"status":"waiting","time":datetime.utcnow().isoformat(),"photo":None}
        save(PENDING_F,pending)
        await q.message.reply_text(f"برای خرید {pts} امتیاز — مبلغ {price:,} تومان\nشماره کارت: {cfg.get('admin_card')}\nلطفا رسید (عکس) بفرستید و در کپشن مبلغ را وارد کنید.")
        return
    if data=="buy_premium":
        buttons=[]
        for k,p in cfg.get("premium",{}).items(): buttons.append([InlineKeyboardButton(f"{p['name']} — {p['price']:,} T", callback_data=f"prembuy|{k}")])
        buttons.append([InlineKeyboardButton("بازگشت", callback_data="menu|main")]); await q.edit_message_text("پرمیوم ها:", reply_markup=InlineKeyboardMarkup(buttons)); return
    if data.startswith("prem|") or data.startswith("prembuy|"):
        _,key=data.split("|",1); p=cfg.get("premium",{}).get(key)
        if not p: await q.edit_message_text("پلن نامعتبر"); return
        pid=str(int(time.time()*1000))
        pending[pid]={"user_id":user.id,"username":user.username or f"user{user.id}","plan_key":key,"plan_name":p['name'],"plan_price":int(p['price']),"plan_points":int(p.get('points',0)),"is_premium":True,"status":"waiting","time":datetime.utcnow().isoformat(),"photo":None}
        save(PENDING_F,pending)
        await q.message.reply_text(f"برای خرید {p['name']} — مبلغ {p['price']:,} تومان\nشماره کارت: {cfg.get('admin_card')}\nلطفا رسید (عکس) بفرستید.")
        return
    if data.startswith("approve|") or data.startswith("reject|"):
        cmd,pid=data.split("|",1); pay=pending.get(pid)
        if not pay: await q.edit_message_text("پرداخت یافت نشد"); return
        if not is_admin(q.from_user.id): await q.edit_message_text("شما ادمین نیستید"); return
        if cmd=="approve":
            if pay.get("is_premium"):
                give_premium(pay["user_id"], pay["username"], pay["plan_key"])
                pay["status"]="approved"; save(PENDING_F,pending); await q.edit_message_text("پرمیوم فعال شد"); 
                try: await context.bot.send_message(chat_id=pay["user_id"], text="🎉 خرید شما تایید و پرمیوم فعال شد.")
                except: pass
            else:
                add_points(pay["user_id"], pay["username"], pay["plan_points"]); pay["status"]="approved"; save(PENDING_F,pending)
                await q.edit_message_text(f"✅ پرداخت تایید و {pay['plan_points']} امتیاز اضافه شد.")
                try: await context.bot.send_message(chat_id=pay["user_id"], text=f"🎉 پرداخت تایید شد! +{pay['plan_points']} امتیاز")
                except: pass
        else:
            pay["status"]="rejected"; save(PENDING_F,pending); await q.edit_message_text("❌ رد شد"); 
            try: await context.bot.send_message(chat_id=pay["user_id"], text="⚠️ رسید شما تایید نشد.")
            except: pass
        return
    if data=="menu|main":
        await q.message.delete(); await context.bot.send_message(chat_id=q.from_user.id, text="منو:", reply_markup=main_kb()); return

# ---------------- photo (receipt) handler ----------------
async def photo_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user; uid=user.id; sid=str(uid)
    if uid in blocked: await update.message.reply_text("حساب مسدود"); return
    # find pending for user
    pid=None; pay=None
    for k,p in pending.items():
        if p.get("user_id")==uid and p.get("status")=="waiting": pid=k; pay=p; break
    if not pid: await update.message.reply_text("سفارش معتبر یافت نشد. ابتدا پلن را انتخاب کنید."); return
    # save photo
    file = await context.bot.get_file(update.message.photo[-1].file_id)
    ppath = DATA / f"receipt_{pid}.jpg"; await file.download_to_drive(str(ppath))
    pending[pid]["photo"]=str(ppath); save(PENDING_F,pending)
    caption = (update.message.caption or "").strip()
    detected_amount=None; detected_card=None
    # caption parse
    if caption:
        m=re.search(r"(\d{3,7})", caption.replace(",",""))
        if m: detected_amount=int(re.sub(r"[^\d]","",m.group(1)))
    ocr_amt=None; ocr_card=None
    if USE_OCR:
        try:
            from PIL import Image
            import pytesseract
            text=pytesseract.image_to_string(Image.open(str(ppath)))
            nums=re.findall(r"\d{3,7}", text.replace(",",""))
            if nums: ocr_amt=max(map(int,nums))
            cm=re.search(r"(\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4})", text)
            if cm: ocr_card=cm.group(1).replace(" ","").replace("-","")
        except Exception:
            ocr_amt=None; ocr_card=None
    expected=pay.get("plan_price")
    match_amt = (detected_amount==expected) or (ocr_amt==expected)
    admin_card = cfg.get("admin_card","").replace("-","").replace(" ","")
    match_card = False
    if ocr_card:
        if admin_card in ocr_card or ocr_card in admin_card: match_card=True
    # auto-approve if amount matches and card matches or card not found
    if match_amt and (match_card or not ocr_card):
        pay["status"]="approved"; save(PENDING_F,pending)
        if pay.get("is_premium"): give_premium(pay["user_id"], pay["username"], pay["plan_key"])
        else: add_points(pay["user_id"], pay["username"], pay["plan_points"])
        try: await context.bot.send_message(chat_id=pay["user_id"], text="🎉 پرداخت شما تایید و امتیاز اضافه شد.")
        except: pass
        try: await context.bot.send_message(chat_id=cfg.get("admin_id"), text=f"✅ پرداخت اتومات: PID {pid}")
        except: pass
        return
    # else manual review - increment fake counter
    fake_count[sid]=fake_count.get(sid,0)+1
    if fake_count[sid] >= cfg.get("max_fake",3):
        blocked.append(uid); save(BLOCK_F, blocked); await update.message.reply_text("⛔ چند رسید نامعتبر فرستادید — بلاک شدید."); return
    pay["status"]="pending_review"; save(PENDING_F,pending)
    caption_admin=f"پرداخت نیاز به بررسی: ID {pid}\nUser @{pay['username']}\nPlan {pay.get('plan_name',pay.get('plan_points'))} — {pay['plan_price']:,} T\nCAP: {caption}\nOCR_amt:{ocr_amt}\nOCR_card:{ocr_card}"
    try:
        await context.bot.send_photo(chat_id=cfg.get("admin_id"), photo=open(str(ppath),"rb"), caption=caption_admin, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅",callback_data=f"approve|{pid}"),InlineKeyboardButton("❌",callback_data=f"reject|{pid}")]]))
    except:
        await context.bot.send_message(chat_id=cfg.get("admin_id"), text=caption_admin, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅",callback_data=f"approve|{pid}"),InlineKeyboardButton("❌",callback_data=f"reject|{pid}")]]))
    await update.message.reply_text("رسید شما برای بررسی ارسال شد. نتیجه اطلاع داده می‌شود.")

# -------------- admin reply to forwarded ----------------
async def admin_reply_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # admin replies to a forwarded message -> send to original user
    user = update.effective_user
    if not is_admin(user.id): return
    if update.message.reply_to_message:
        mid = update.message.reply_to_message.message_id
        orig = forward_map.get(mid)
        if orig:
            txt = update.message.text or ""
            try:
                await context.bot.send_message(chat_id=orig, text=f"📩 پاسخ پشتیبانی:\n\n{txt}")
                await update.message.reply_text("پیام ارسال شد.")
            except:
                await update.message.reply_text("ارسال موفق نبود.")
        else:
            await update.message.reply_text("پیام مرجع قابل پیگیری نیست.")

# ---------------- file update handler (self-update) ----------------
async def doc_update_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_admin(user.id): await update.message.reply_text("فقط ادمین مجاز است."); return
    if not update.message.document: await update.message.reply_text("فایل .py ارسال کنید (document)."); return
    doc = update.message.document
    if not doc.file_name.endswith(".py"): await update.message.reply_text("فقط فایل .py پذیرفته می‌شود."); return
    f = await context.bot.get_file(doc.file_id)
    newpath = Path("update_new.py")
    await f.download_to_drive(str(newpath))
    await update.message.reply_text("فایل دریافت شد. جایگزینی و ری‌استارت در حال انجام است...")
    try:
        curr = Path(sys.argv[0])
        backup = curr.with_suffix(".backup.py")
        if curr.exists(): curr.replace(backup)
        newpath.replace(curr)
        python = sys.executable
        os.execv(python, [python] + sys.argv)
    except Exception as e:
        await update.message.reply_text(f"خطا در آپدیت: {e}")
        # try restore
        if backup.exists(): backup.replace(curr)

# ---------------- register & run ----------------
def build_app():
    return ApplicationBuilder().token(BOT_TOKEN).build()

def register(app):
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.PHOTO & ~filters.COMMAND, photo_handler))
    app.add_handler(CallbackQueryHandler(callback_cb))
    # file update - document (admin only checked inside)
    app.add_handler(MessageHandler(filters.Document.ALL & ~filters.COMMAND, doc_update_handler))
    # admin reply (replying to forwarded message)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, admin_reply_handler))
    # main text handler (last)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

def main():
    if BOT_TOKEN.startswith("PUT_YOUR"): print("Set BOT_TOKEN"); return
    app = build_app(); register(app)
    print("Bot started..."); app.run_polling()

if __name__ == "__main__":
    main()
