# -*- coding: utf-8 -*-
import telebot
import subprocess
import os
import zipfile
import tempfile
import shutil
from telebot import types
import time
from datetime import datetime, timedelta
import psutil
import sqlite3
import json
import logging
import signal
import threading
import re
import sys
import atexit
import requests
from flask import Flask
from threading import Thread

# ============================================================
# CONFIG
# ============================================================
TOKEN = '8962084623:AAH7XTgIN8DNQOr9iVBIethf7W8GnhzlDg0'
OWNER_ID = 6994439211
ADMIN_ID = 6994439211
YOUR_USERNAME = '@MOHASINgaming'
UPDATE_CHANNEL = 'https://t.me/+2K1BCPtLFuIzMmQ1'

# Firebase REST API
FIREBASE_URL = "https://garena-es-13d62-default-rtdb.asia-southeast1.firebasedatabase.app"

# File limits
FREE_USER_LIMIT = 10
SUBSCRIBED_USER_LIMIT = 15
ADMIN_LIMIT = 999
OWNER_LIMIT = float('inf')

# Paths
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
UPLOAD_BOTS_DIR = os.path.join(BASE_DIR, 'upload_bots')
IROTECH_DIR = os.path.join(BASE_DIR, 'inf')
DATABASE_PATH = os.path.join(IROTECH_DIR, 'bot_data.db')

os.makedirs(UPLOAD_BOTS_DIR, exist_ok=True)
os.makedirs(IROTECH_DIR, exist_ok=True)

bot = telebot.TeleBot(TOKEN)

# ============================================================
# FLASK KEEP ALIVE
# ============================================================
app = Flask('')

@app.route('/')
def home():
    return "I'am Marco File Host"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run_flask)
    t.daemon = True
    t.start()
    print("Flask Keep-Alive started.")

# ============================================================
# FIREBASE REST CLASS
# ============================================================
class FirebaseDB:
    def __init__(self, url):
        self.url = url.rstrip('/')

    def get(self, path):
        try:
            r = requests.get(f"{self.url}/{path}.json", timeout=15)
            return r.json() if r.status_code == 200 else None
        except Exception as e:
            logger.error(f"FB GET [{path}]: {e}")
            return None

    def put(self, path, data):
        try:
            r = requests.put(f"{self.url}/{path}.json", json=data, timeout=15)
            return r.status_code == 200
        except:
            return False

    def patch(self, path, data):
        try:
            r = requests.patch(f"{self.url}/{path}.json", json=data, timeout=15)
            return r.status_code == 200
        except:
            return False

    def push(self, path, data):
        try:
            r = requests.post(f"{self.url}/{path}.json", json=data, timeout=15)
            return r.json().get("name") if r.status_code == 200 else None
        except:
            return None

    def delete(self, path):
        try:
            r = requests.delete(f"{self.url}/{path}.json", timeout=15)
            return r.status_code == 200
        except:
            return False


# ============================================================
# LOGGING
# ============================================================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

firebase = FirebaseDB(FIREBASE_URL)


# ============================================================
# FIREBASE HELPERS
# ============================================================
def fb_get_user_balance(user_id):
    uid = str(user_id)
    data = firebase.get(f"users/{uid}")
    if data:
        dep = float(data.get("deposit", 0))
        win = float(data.get("winning", 0))
        return {"deposit": dep, "winning": win, "total": dep + win}
    return {"deposit": 0, "winning": 0, "total": 0}


def fb_add_balance(user_id, amount, wallet="deposit"):
    uid = str(user_id)
    cur = firebase.get(f"users/{uid}") or {}
    new_val = float(cur.get(wallet, 0)) + float(amount)
    firebase.patch(f"users/{uid}", {wallet: new_val})
    return fb_get_user_balance(user_id)


def fb_log_transaction(user_id, tx_type, amount, method, status="Success", extra=None):
    uid = str(user_id)
    data = {
        "type": tx_type,
        "amount": float(amount),
        "method": method,
        "status": status,
        "date": datetime.now().strftime("%d-%m-%Y %I:%M %p"),
        "time": int(time.time())
    }
    if extra:
        data.update(extra)
    return firebase.push(f"transactions/{uid}", data)


def fb_verify_and_add_money(user_id, trx_id, method="bkash"):
    """Firebase SMS থেকে TRX ভেরিফাই করে ব্যালেন্স যোগ"""
    uid = str(user_id)
    trx_id = trx_id.strip()

    # Duplicate check
    used = firebase.get(f"Auto Pay/{trx_id}")
    if used:
        return {"success": False, "error": "❌ এই TRX আগে ব্যবহার হয়েছে!"}

    # XNXANIKPAY তে চেক
    all_payments = firebase.get("XNXANIKPAY")
    if not all_payments:
        return {"success": False, "error": "❌ সিস্টেমে SMS ডাটা নেই!"}

    found = None
    for key, payment in all_payments.items():
        if str(payment.get("txid", "")).strip().lower() == trx_id.lower():
            found = payment
            break

    if not found:
        return {"success": False, "error": "❌ TRX পাওয়া যায়নি!\n⏳ ১-২ মিনিট অপেক্ষা করুন"}

    try:
        amount = float(found.get("amount", 0))
    except:
        return {"success": False, "error": "❌ ভুল amount!"}

    if amount < 10:
        return {"success": False, "error": "❌ মিনিমাম ৳10!"}

    cur = firebase.get(f"users/{uid}") or {}
    new_dep = float(cur.get("deposit", 0)) + amount
    if not firebase.patch(f"users/{uid}", {"deposit": new_dep}):
        return {"success": False, "error": "❌ Firebase সমস্যা!"}

    firebase.put(f"Auto Pay/{trx_id}", {
        "amount": amount,
        "usedBy": uid,
        "method": method.lower(),
        "time": int(time.time()),
        "date": datetime.now().strftime("%d-%m-%Y %I:%M %p")
    })

    fb_log_transaction(uid, "Deposit (Auto)", amount, method, "Success",
                       {"txid": trx_id, "auto": True})

    logger.info(f"[AUTO] {uid}: +৳{amount} TRX:{trx_id}")
    return {"success": True, "amount": amount, "new_deposit": new_dep}


# ============================================================
# DATA STRUCTURES
# ============================================================
bot_scripts = {}
user_subscriptions = {}
user_files = {}
active_users = set()
admin_ids = {ADMIN_ID, OWNER_ID}
bot_locked = False

# ============================================================
# MENUS (ReplyKeyboard)
# ============================================================
COMMAND_BUTTONS_LAYOUT_USER = [
    ["📢 Updates Channel"],
    ["📤 Upload File", "📂 Check Files"],
    ["⚡ Bot Speed", "📊 Statistics"],
    ["💰 Add Balance", "👤 My Profile"],
    ["📞 Contact Owner"]
]

ADMIN_COMMAND_BUTTONS_LAYOUT = [
    ["📢 Updates Channel"],
    ["📤 Upload File", "📂 Check Files"],
    ["⚡ Bot Speed", "📊 Statistics"],
    ["💰 Add Balance", "👤 My Profile"],
    ["💳 Subscriptions", "📢 Broadcast"],
    ["🔒 Lock Bot", "🟢 Running All Code"],
    ["👑 Admin Panel", "📞 Contact Owner"]
]

# ============================================================
# DATABASE
# ============================================================
def init_db():
    logger.info(f"Init DB: {DATABASE_PATH}")
    try:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS subscriptions
                     (user_id INTEGER PRIMARY KEY, expiry TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS user_files
                     (user_id INTEGER, file_name TEXT, file_type TEXT,
                      PRIMARY KEY (user_id, file_name))''')
        c.execute('''CREATE TABLE IF NOT EXISTS active_users
                     (user_id INTEGER PRIMARY KEY)''')
        c.execute('''CREATE TABLE IF NOT EXISTS admins
                     (user_id INTEGER PRIMARY KEY)''')
        c.execute('INSERT OR IGNORE INTO admins (user_id) VALUES (?)', (OWNER_ID,))
        if ADMIN_ID != OWNER_ID:
            c.execute('INSERT OR IGNORE INTO admins (user_id) VALUES (?)', (ADMIN_ID,))
        conn.commit()
        conn.close()
        logger.info("DB OK")
    except Exception as e:
        logger.error(f"DB error: {e}", exc_info=True)


def load_data():
    logger.info("Loading data...")
    try:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()

        c.execute('SELECT user_id, expiry FROM subscriptions')
        for user_id, expiry in c.fetchall():
            try:
                user_subscriptions[user_id] = {'expiry': datetime.fromisoformat(expiry)}
            except:
                pass

        c.execute('SELECT user_id, file_name, file_type FROM user_files')
        for user_id, file_name, file_type in c.fetchall():
            if user_id not in user_files:
                user_files[user_id] = []
            user_files[user_id].append((file_name, file_type))

        c.execute('SELECT user_id FROM active_users')
        active_users.update(user_id for (user_id,) in c.fetchall())

        c.execute('SELECT user_id FROM admins')
        admin_ids.update(user_id for (user_id,) in c.fetchall())

        conn.close()
        logger.info(f"Loaded: {len(active_users)} users, {len(user_subscriptions)} subs")
    except Exception as e:
        logger.error(f"Load error: {e}", exc_info=True)


init_db()
load_data()

# ============================================================
# HELPERS
# ============================================================
def get_user_folder(user_id):
    folder = os.path.join(UPLOAD_BOTS_DIR, str(user_id))
    os.makedirs(folder, exist_ok=True)
    return folder


def get_user_file_limit(user_id):
    if user_id == OWNER_ID:
        return OWNER_LIMIT
    if user_id in admin_ids:
        return ADMIN_LIMIT
    if user_id in user_subscriptions and user_subscriptions[user_id]['expiry'] > datetime.now():
        return SUBSCRIBED_USER_LIMIT
    return FREE_USER_LIMIT


def get_user_file_count(user_id):
    return len(user_files.get(user_id, []))


def is_bot_running(script_owner_id, file_name):
    script_key = f"{script_owner_id}_{file_name}"
    script_info = bot_scripts.get(script_key)
    if script_info and script_info.get('process'):
        try:
            proc = psutil.Process(script_info['process'].pid)
            is_running = proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE
            if not is_running:
                if 'log_file' in script_info and hasattr(script_info['log_file'], 'close') and not script_info['log_file'].closed:
                    try:
                        script_info['log_file'].close()
                    except:
                        pass
                if script_key in bot_scripts:
                    del bot_scripts[script_key]
            return is_running
        except psutil.NoSuchProcess:
            if 'log_file' in script_info and hasattr(script_info['log_file'], 'close') and not script_info['log_file'].closed:
                try:
                    script_info['log_file'].close()
                except:
                    pass
            if script_key in bot_scripts:
                del bot_scripts[script_key]
            return False
        except Exception as e:
            logger.error(f"Check error {script_key}: {e}")
            return False
    return False


def kill_process_tree(process_info):
    pid = None
    log_file_closed = False
    script_key = process_info.get('script_key', 'N/A')

    try:
        if 'log_file' in process_info and hasattr(process_info['log_file'], 'close') and not process_info['log_file'].closed:
            try:
                process_info['log_file'].close()
                log_file_closed = True
            except Exception as log_e:
                logger.error(f"Log close err: {log_e}")

        process = process_info.get('process')
        if process and hasattr(process, 'pid'):
            pid = process.pid
            if pid:
                try:
                    parent = psutil.Process(pid)
                    children = parent.children(recursive=True)
                    for child in children:
                        try:
                            child.terminate()
                        except:
                            try:
                                child.kill()
                            except:
                                pass

                    gone, alive = psutil.wait_procs(children, timeout=1)
                    for p in alive:
                        try:
                            p.kill()
                        except:
                            pass

                    try:
                        parent.terminate()
                        try:
                            parent.wait(timeout=1)
                        except psutil.TimeoutExpired:
                            parent.kill()
                    except:
                        try:
                            parent.kill()
                        except:
                            pass
                except psutil.NoSuchProcess:
                    pass
    except Exception as e:
        logger.error(f"Kill error: {e}")


# ============================================================
# PACKAGE INSTALLER
# ============================================================
TELEGRAM_MODULES = {
    'telebot': 'pyTelegramBotAPI',
    'telegram': 'python-telegram-bot',
    'python_telegram_bot': 'python-telegram-bot',
    'aiogram': 'aiogram',
    'pyrogram': 'pyrogram',
    'telethon': 'telethon',
    'bs4': 'beautifulsoup4',
    'requests': 'requests',
    'pillow': 'Pillow',
    'cv2': 'opencv-python',
    'yaml': 'PyYAML',
    'dotenv': 'python-dotenv',
    'dateutil': 'python-dateutil',
    'psutil': 'psutil',
    'asyncio': None,
    'json': None,
    'datetime': None,
    'os': None,
    'sys': None,
    're': None,
    'time': None,
    'math': None,
    'random': None,
    'logging': None,
    'threading': None,
    'subprocess': None,
    'zipfile': None,
    'tempfile': None,
    'shutil': None,
    'sqlite3': None,
    'atexit': None,
}


def attempt_install_pip(module_name, message):
    package_name = TELEGRAM_MODULES.get(module_name.lower(), module_name)
    if package_name is None:
        return False
    try:
        bot.reply_to(message, f"🐍 Installing `{package_name}`...", parse_mode='Markdown')
        command = [sys.executable, '-m', 'pip', 'install', package_name]
        result = subprocess.run(command, capture_output=True, text=True, check=False,
                                encoding='utf-8', errors='ignore')
        if result.returncode == 0:
            bot.reply_to(message, f"✅ `{package_name}` installed.", parse_mode='Markdown')
            return True
        else:
            error_msg = f"❌ Failed `{package_name}`.\n```\n{result.stderr or result.stdout}\n```"
            if len(error_msg) > 4000:
                error_msg = error_msg[:4000] + "..."
            bot.reply_to(message, error_msg, parse_mode='Markdown')
            return False
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {e}")
        return False


def attempt_install_npm(module_name, user_folder, message):
    try:
        bot.reply_to(message, f"🟠 Installing node `{module_name}`...", parse_mode='Markdown')
        command = ['npm', 'install', module_name]
        result = subprocess.run(command, capture_output=True, text=True, check=False,
                                cwd=user_folder, encoding='utf-8', errors='ignore')
        if result.returncode == 0:
            bot.reply_to(message, f"✅ Node `{module_name}` installed.", parse_mode='Markdown')
            return True
        else:
            error_msg = f"❌ Failed `{module_name}`.\n```\n{result.stderr or result.stdout}\n```"
            if len(error_msg) > 4000:
                error_msg = error_msg[:4000] + "..."
            bot.reply_to(message, error_msg, parse_mode='Markdown')
            return False
    except FileNotFoundError:
        bot.reply_to(message, "❌ npm not found.")
        return False
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {e}")
        return False


# ============================================================
# SCRIPT RUNNER
# ============================================================
def run_script(script_path, script_owner_id, user_folder, file_name, message_obj_for_reply, attempt=1):
    max_attempts = 2
    if attempt > max_attempts:
        bot.reply_to(message_obj_for_reply, f"❌ Failed after {max_attempts} attempts.")
        return

    script_key = f"{script_owner_id}_{file_name}"
    logger.info(f"Run Py attempt {attempt}: {script_path}")

    try:
        if not os.path.exists(script_path):
            bot.reply_to(message_obj_for_reply, f"❌ Script not found!")
            remove_user_file_db(script_owner_id, file_name)
            return

        if attempt == 1:
            check_command = [sys.executable, script_path]
            check_proc = None
            try:
                check_proc = subprocess.Popen(check_command, cwd=user_folder,
                                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                              text=True, encoding='utf-8', errors='ignore')
                stdout, stderr = check_proc.communicate(timeout=5)
                return_code = check_proc.returncode
                if return_code != 0 and stderr:
                    match_py = re.search(r"ModuleNotFoundError: No module named '(.+?)'", stderr)
                    if match_py:
                        module_name = match_py.group(1).strip().strip("'\"")
                        if attempt_install_pip(module_name, message_obj_for_reply):
                            time.sleep(2)
                            threading.Thread(target=run_script, args=(script_path, script_owner_id,
                                                                      user_folder, file_name,
                                                                      message_obj_for_reply, attempt + 1)).start()
                            return
                        else:
                            bot.reply_to(message_obj_for_reply, f"❌ Install failed.")
                            return
                    else:
                        error_summary = stderr[:500]
                        bot.reply_to(message_obj_for_reply, f"❌ Pre-check:\n```\n{error_summary}\n```",
                                     parse_mode='Markdown')
                        return
            except subprocess.TimeoutExpired:
                if check_proc and check_proc.poll() is None:
                    check_proc.kill()
                    check_proc.communicate()
            except FileNotFoundError:
                bot.reply_to(message_obj_for_reply, f"❌ Python not found.")
                return
            except Exception as e:
                bot.reply_to(message_obj_for_reply, f"❌ Error: {e}")
                return
            finally:
                if check_proc and check_proc.poll() is None:
                    check_proc.kill()
                    check_proc.communicate()

        log_file_path = os.path.join(user_folder, f"{os.path.splitext(file_name)[0]}.log")
        log_file = None
        process = None
        try:
            log_file = open(log_file_path, 'w', encoding='utf-8', errors='ignore')
        except Exception as e:
            bot.reply_to(message_obj_for_reply, f"❌ Log open error: {e}")
            return

        try:
            startupinfo = None
            creationflags = 0
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = subprocess.SW_HIDE
            process = subprocess.Popen(
                [sys.executable, script_path], cwd=user_folder, stdout=log_file, stderr=log_file,
                stdin=subprocess.PIPE, startupinfo=startupinfo, creationflags=creationflags,
                encoding='utf-8', errors='ignore'
            )
            bot_scripts[script_key] = {
                'process': process, 'log_file': log_file, 'file_name': file_name,
                'chat_id': message_obj_for_reply.chat.id,
                'script_owner_id': script_owner_id,
                'start_time': datetime.now(), 'user_folder': user_folder,
                'type': 'py', 'script_key': script_key
            }
            bot.reply_to(message_obj_for_reply, f"✅ Py script '{file_name}' started! (PID: {process.pid})")
        except FileNotFoundError:
            bot.reply_to(message_obj_for_reply, f"❌ Python not found.")
            if log_file and not log_file.closed:
                log_file.close()
            if script_key in bot_scripts:
                del bot_scripts[script_key]
        except Exception as e:
            if log_file and not log_file.closed:
                log_file.close()
            bot.reply_to(message_obj_for_reply, f"❌ Error: {e}")
            if process and process.poll() is None:
                kill_process_tree({'process': process, 'log_file': log_file, 'script_key': script_key})
            if script_key in bot_scripts:
                del bot_scripts[script_key]
    except Exception as e:
        bot.reply_to(message_obj_for_reply, f"❌ Unexpected: {e}")
        if script_key in bot_scripts:
            kill_process_tree(bot_scripts[script_key])
            del bot_scripts[script_key]


def run_js_script(script_path, script_owner_id, user_folder, file_name, message_obj_for_reply, attempt=1):
    max_attempts = 2
    if attempt > max_attempts:
        bot.reply_to(message_obj_for_reply, f"❌ Failed after {max_attempts} attempts.")
        return

    script_key = f"{script_owner_id}_{file_name}"
    logger.info(f"Run JS attempt {attempt}: {script_path}")

    try:
        if not os.path.exists(script_path):
            bot.reply_to(message_obj_for_reply, f"❌ Script not found!")
            remove_user_file_db(script_owner_id, file_name)
            return

        if attempt == 1:
            check_command = ['node', script_path]
            check_proc = None
            try:
                check_proc = subprocess.Popen(check_command, cwd=user_folder,
                                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                              text=True, encoding='utf-8', errors='ignore')
                stdout, stderr = check_proc.communicate(timeout=5)
                return_code = check_proc.returncode
                if return_code != 0 and stderr:
                    match_js = re.search(r"Cannot find module '(.+?)'", stderr)
                    if match_js:
                        module_name = match_js.group(1).strip().strip("'\"")
                        if not module_name.startswith('.') and not module_name.startswith('/'):
                            if attempt_install_npm(module_name, user_folder, message_obj_for_reply):
                                time.sleep(2)
                                threading.Thread(target=run_js_script, args=(script_path, script_owner_id,
                                                                          user_folder, file_name,
                                                                          message_obj_for_reply, attempt + 1)).start()
                                return
                            else:
                                bot.reply_to(message_obj_for_reply, f"❌ Install failed.")
                                return
                    error_summary = stderr[:500]
                    bot.reply_to(message_obj_for_reply, f"❌ Pre-check:\n```\n{error_summary}\n```",
                                 parse_mode='Markdown')
                    return
            except subprocess.TimeoutExpired:
                if check_proc and check_proc.poll() is None:
                    check_proc.kill()
                    check_proc.communicate()
            except FileNotFoundError:
                bot.reply_to(message_obj_for_reply, f"❌ Node not found.")
                return
            except Exception as e:
                bot.reply_to(message_obj_for_reply, f"❌ Error: {e}")
                return
            finally:
                if check_proc and check_proc.poll() is None:
                    check_proc.kill()
                    check_proc.communicate()

        log_file_path = os.path.join(user_folder, f"{os.path.splitext(file_name)[0]}.log")
        log_file = None
        process = None
        try:
            log_file = open(log_file_path, 'w', encoding='utf-8', errors='ignore')
        except Exception as e:
            bot.reply_to(message_obj_for_reply, f"❌ Log error: {e}")
            return

        try:
            startupinfo = None
            creationflags = 0
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = subprocess.SW_HIDE
            process = subprocess.Popen(
                ['node', script_path], cwd=user_folder, stdout=log_file, stderr=log_file,
                stdin=subprocess.PIPE, startupinfo=startupinfo, creationflags=creationflags,
                encoding='utf-8', errors='ignore'
            )
            bot_scripts[script_key] = {
                'process': process, 'log_file': log_file, 'file_name': file_name,
                'chat_id': message_obj_for_reply.chat.id,
                'script_owner_id': script_owner_id,
                'start_time': datetime.now(), 'user_folder': user_folder,
                'type': 'js', 'script_key': script_key
            }
            bot.reply_to(message_obj_for_reply, f"✅ JS script '{file_name}' started! (PID: {process.pid})")
        except FileNotFoundError:
            bot.reply_to(message_obj_for_reply, f"❌ Node not found.")
            if log_file and not log_file.closed:
                log_file.close()
            if script_key in bot_scripts:
                del bot_scripts[script_key]
        except Exception as e:
            if log_file and not log_file.closed:
                log_file.close()
            bot.reply_to(message_obj_for_reply, f"❌ Error: {e}")
            if process and process.poll() is None:
                kill_process_tree({'process': process, 'log_file': log_file, 'script_key': script_key})
            if script_key in bot_scripts:
                del bot_scripts[script_key]
    except Exception as e:
        bot.reply_to(message_obj_for_reply, f"❌ Unexpected: {e}")
        if script_key in bot_scripts:
            kill_process_tree(bot_scripts[script_key])
            del bot_scripts[script_key]


# ============================================================
# DB OPS
# ============================================================
DB_LOCK = threading.Lock()


def save_user_file(user_id, file_name, file_type='py'):
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        try:
            c.execute('INSERT OR REPLACE INTO user_files (user_id, file_name, file_type) VALUES (?, ?, ?)',
                      (user_id, file_name, file_type))
            conn.commit()
            if user_id not in user_files:
                user_files[user_id] = []
            user_files[user_id] = [(fn, ft) for fn, ft in user_files[user_id] if fn != file_name]
            user_files[user_id].append((file_name, file_type))
        except Exception as e:
            logger.error(f"Save file err: {e}")
        finally:
            conn.close()


def remove_user_file_db(user_id, file_name):
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        try:
            c.execute('DELETE FROM user_files WHERE user_id = ? AND file_name = ?', (user_id, file_name))
            conn.commit()
            if user_id in user_files:
                user_files[user_id] = [f for f in user_files[user_id] if f[0] != file_name]
                if not user_files[user_id]:
                    del user_files[user_id]
        except Exception as e:
            logger.error(f"Remove file err: {e}")
        finally:
            conn.close()


def add_active_user(user_id):
    active_users.add(user_id)
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        try:
            c.execute('INSERT OR IGNORE INTO active_users (user_id) VALUES (?)', (user_id,))
            conn.commit()
        except Exception as e:
            logger.error(f"Add user err: {e}")
        finally:
            conn.close()


def save_subscription(user_id, expiry):
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        try:
            expiry_str = expiry.isoformat()
            c.execute('INSERT OR REPLACE INTO subscriptions (user_id, expiry) VALUES (?, ?)',
                      (user_id, expiry_str))
            conn.commit()
            user_subscriptions[user_id] = {'expiry': expiry}
        except Exception as e:
            logger.error(f"Save sub err: {e}")
        finally:
            conn.close()


def remove_subscription_db(user_id):
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        try:
            c.execute('DELETE FROM subscriptions WHERE user_id = ?', (user_id,))
            conn.commit()
            if user_id in user_subscriptions:
                del user_subscriptions[user_id]
        except Exception as e:
            logger.error(f"Remove sub err: {e}")
        finally:
            conn.close()


def add_admin_db(admin_id):
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        try:
            c.execute('INSERT OR IGNORE INTO admins (user_id) VALUES (?)', (admin_id,))
            conn.commit()
            admin_ids.add(admin_id)
        except Exception as e:
            logger.error(f"Add admin err: {e}")
        finally:
            conn.close()


def remove_admin_db(admin_id):
    if admin_id == OWNER_ID:
        return False
    with DB_LOCK:
        conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
        c = conn.cursor()
        removed = False
        try:
            c.execute('SELECT 1 FROM admins WHERE user_id = ?', (admin_id,))
            if c.fetchone():
                c.execute('DELETE FROM admins WHERE user_id = ?', (admin_id,))
                conn.commit()
                removed = c.rowcount > 0
                if removed:
                    admin_ids.discard(admin_id)
            return removed
        except Exception as e:
            logger.error(f"Remove admin err: {e}")
            return False
        finally:
            conn.close()


# ============================================================
# MENUS
# ============================================================
def create_main_menu_inline(user_id):
    markup = types.InlineKeyboardMarkup(row_width=2)
    buttons = [
        types.InlineKeyboardButton('📢 Updates Channel', url=UPDATE_CHANNEL),
        types.InlineKeyboardButton('📤 Upload File', callback_data='upload'),
        types.InlineKeyboardButton('📂 Check Files', callback_data='check_files'),
        types.InlineKeyboardButton('⚡ Bot Speed', callback_data='speed'),
        types.InlineKeyboardButton('💰 Add Balance', callback_data='add_balance_main'),
        types.InlineKeyboardButton('👤 Profile', callback_data='view_profile'),
        types.InlineKeyboardButton('📞 Contact Owner', url=f'https://t.me/{YOUR_USERNAME.replace("@", "")}')
    ]

    if user_id in admin_ids:
        admin_buttons = [
            types.InlineKeyboardButton('💳 Subscriptions', callback_data='subscription'),
            types.InlineKeyboardButton('📊 Statistics', callback_data='stats'),
            types.InlineKeyboardButton('🔒 Lock Bot' if not bot_locked else '🔓 Unlock Bot',
                                     callback_data='lock_bot' if not bot_locked else 'unlock_bot'),
            types.InlineKeyboardButton('📢 Broadcast', callback_data='broadcast'),
            types.InlineKeyboardButton('👑 Admin Panel', callback_data='admin_panel'),
            types.InlineKeyboardButton('🟢 Run All Scripts', callback_data='run_all_scripts')
        ]
        markup.add(buttons[0])
        markup.add(buttons[1], buttons[2])
        markup.add(buttons[3], admin_buttons[0])
        markup.add(admin_buttons[1], admin_buttons[3])
        markup.add(admin_buttons[2], admin_buttons[5])
        markup.add(admin_buttons[4])
        markup.add(buttons[4], buttons[5])
        markup.add(buttons[6])
    else:
        markup.add(buttons[0])
        markup.add(buttons[1], buttons[2])
        markup.add(buttons[3])
        markup.add(types.InlineKeyboardButton('📊 Statistics', callback_data='stats'))
        markup.add(buttons[4], buttons[5])
        markup.add(buttons[6])
    return markup


def create_reply_keyboard_main_menu(user_id):
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    layout = ADMIN_COMMAND_BUTTONS_LAYOUT if user_id in admin_ids else COMMAND_BUTTONS_LAYOUT_USER
    for row in layout:
        markup.add(*[types.KeyboardButton(text) for text in row])
    return markup


def create_control_buttons(script_owner_id, file_name, is_running=True):
    markup = types.InlineKeyboardMarkup(row_width=2)
    if is_running:
        markup.row(
            types.InlineKeyboardButton("🔴 Stop", callback_data=f'stop_{script_owner_id}_{file_name}'),
            types.InlineKeyboardButton("🔄 Restart", callback_data=f'restart_{script_owner_id}_{file_name}')
        )
        markup.row(
            types.InlineKeyboardButton("🗑️ Delete", callback_data=f'delete_{script_owner_id}_{file_name}'),
            types.InlineKeyboardButton("📜 Logs", callback_data=f'logs_{script_owner_id}_{file_name}')
        )
    else:
        markup.row(
            types.InlineKeyboardButton("🟢 Start", callback_data=f'start_{script_owner_id}_{file_name}'),
            types.InlineKeyboardButton("🗑️ Delete", callback_data=f'delete_{script_owner_id}_{file_name}')
        )
        markup.row(
            types.InlineKeyboardButton("📜 View Logs", callback_data=f'logs_{script_owner_id}_{file_name}')
        )
    markup.add(types.InlineKeyboardButton("🔙 Back to Files", callback_data='check_files'))
    return markup


def create_admin_panel():
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.row(
        types.InlineKeyboardButton('➕ Add Admin', callback_data='add_admin'),
        types.InlineKeyboardButton('➖ Remove Admin', callback_data='remove_admin')
    )
    markup.row(types.InlineKeyboardButton('📋 List Admins', callback_data='list_admins'))
    markup.row(types.InlineKeyboardButton('🔙 Back to Main', callback_data='back_to_main'))
    return markup


def create_subscription_menu():
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.row(
        types.InlineKeyboardButton('➕ Add Subscription', callback_data='add_subscription'),
        types.InlineKeyboardButton('➖ Remove Subscription', callback_data='remove_subscription')
    )
    markup.row(types.InlineKeyboardButton('🔍 Check Subscription', callback_data='check_subscription'))
    markup.row(types.InlineKeyboardButton('🔙 Back to Main', callback_data='back_to_main'))
    return markup


def create_add_balance_menu():
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton('💗 bKash', callback_data='pay_bkash'),
        types.InlineKeyboardButton('🚀 Rocket', callback_data='pay_rocket'),
        types.InlineKeyboardButton('🟠 Nagad', callback_data='pay_nagad'),
        types.InlineKeyboardButton('🔙 Back to Main', callback_data='back_to_main')
    )
    return markup


def create_payment_method_menu(method):
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton('📋 Copy Number', callback_data=f'copy_number_{method}'),
        types.InlineKeyboardButton('✅ Enter TRX ID', callback_data=f'enter_trx_{method}'),
        types.InlineKeyboardButton('🔙 Back', callback_data='add_balance_main')
    )
    return markup


# ============================================================
# FILE HANDLING
# ============================================================
def handle_zip_file(downloaded_file_content, file_name_zip, message):
    user_id = message.from_user.id
    user_folder = get_user_folder(user_id)
    temp_dir = None
    try:
        temp_dir = tempfile.mkdtemp(prefix=f"user_{user_id}_zip_")
        zip_path = os.path.join(temp_dir, file_name_zip)
        with open(zip_path, 'wb') as new_file:
            new_file.write(downloaded_file_content)
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            for member in zip_ref.infolist():
                member_path = os.path.abspath(os.path.join(temp_dir, member.filename))
                if not member_path.startswith(os.path.abspath(temp_dir)):
                    raise zipfile.BadZipFile(f"Unsafe path: {member.filename}")
            zip_ref.extractall(temp_dir)

        extracted_items = os.listdir(temp_dir)
        py_files = [f for f in extracted_items if f.endswith('.py')]
        js_files = [f for f in extracted_items if f.endswith('.js')]
        req_file = 'requirements.txt' if 'requirements.txt' in extracted_items else None
        pkg_json = 'package.json' if 'package.json' in extracted_items else None

        if req_file:
            req_path = os.path.join(temp_dir, req_file)
            bot.reply_to(message, f"🔄 Installing deps from `{req_file}`...")
            try:
                command = [sys.executable, '-m', 'pip', 'install', '-r', req_path]
                result = subprocess.run(command, capture_output=True, text=True, check=True,
                                        encoding='utf-8', errors='ignore')
                bot.reply_to(message, f"✅ Python deps installed.")
            except subprocess.CalledProcessError as e:
                error_msg = f"❌ Failed.\n```\n{e.stderr or e.stdout}\n```"
                if len(error_msg) > 4000:
                    error_msg = error_msg[:4000] + "..."
                bot.reply_to(message, error_msg, parse_mode='Markdown')
                return

        if pkg_json:
            bot.reply_to(message, f"🔄 Installing node deps...")
            try:
                command = ['npm', 'install']
                result = subprocess.run(command, capture_output=True, text=True, check=True,
                                        cwd=temp_dir, encoding='utf-8', errors='ignore')
                bot.reply_to(message, f"✅ Node deps installed.")
            except FileNotFoundError:
                bot.reply_to(message, "❌ npm not found.")
                return
            except subprocess.CalledProcessError as e:
                error_msg = f"❌ Failed.\n```\n{e.stderr or e.stdout}\n```"
                if len(error_msg) > 4000:
                    error_msg = error_msg[:4000] + "..."
                bot.reply_to(message, error_msg, parse_mode='Markdown')
                return

        main_script_name = None
        file_type = None
        preferred_py = ['main.py', 'bot.py', 'app.py']
        preferred_js = ['index.js', 'main.js', 'bot.js', 'app.js']
        for p in preferred_py:
            if p in py_files:
                main_script_name = p
                file_type = 'py'
                break
        if not main_script_name:
            for p in preferred_js:
                if p in js_files:
                    main_script_name = p
                    file_type = 'js'
                    break
        if not main_script_name:
            if py_files:
                main_script_name = py_files[0]
                file_type = 'py'
            elif js_files:
                main_script_name = js_files[0]
                file_type = 'js'
        if not main_script_name:
            bot.reply_to(message, "❌ No .py or .js found!")
            return

        for item_name in os.listdir(temp_dir):
            src_path = os.path.join(temp_dir, item_name)
            dest_path = os.path.join(user_folder, item_name)
            if os.path.isdir(dest_path):
                shutil.rmtree(dest_path)
            elif os.path.exists(dest_path):
                os.remove(dest_path)
            shutil.move(src_path, dest_path)

        save_user_file(user_id, main_script_name, file_type)
        main_script_path = os.path.join(user_folder, main_script_name)
        bot.reply_to(message, f"✅ Files extracted. Starting `{main_script_name}`...",
                     parse_mode='Markdown')

        if file_type == 'py':
            threading.Thread(target=run_script, args=(main_script_path, user_id, user_folder,
                                                       main_script_name, message)).start()
        elif file_type == 'js':
            threading.Thread(target=run_js_script, args=(main_script_path, user_id, user_folder,
                                                         main_script_name, message)).start()

    except zipfile.BadZipFile as e:
        bot.reply_to(message, f"❌ Bad ZIP: {e}")
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {e}")
    finally:
        if temp_dir and os.path.exists(temp_dir):
            try:
                shutil.rmtree(temp_dir)
            except:
                pass


def handle_js_file(file_path, script_owner_id, user_folder, file_name, message):
    try:
        save_user_file(script_owner_id, file_name, 'js')
        threading.Thread(target=run_js_script, args=(file_path, script_owner_id, user_folder,
                                                      file_name, message)).start()
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {e}")


def handle_py_file(file_path, script_owner_id, user_folder, file_name, message):
    try:
        save_user_file(script_owner_id, file_name, 'py')
        threading.Thread(target=run_script, args=(file_path, script_owner_id, user_folder,
                                                   file_name, message)).start()
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {e}")


# ============================================================
# LOGIC FUNCTIONS
# ============================================================
def _logic_send_welcome(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    user_name = message.from_user.first_name
    user_username = message.from_user.username

    if bot_locked and user_id not in admin_ids:
        bot.send_message(chat_id, "⚠️ Bot locked by admin.")
        return

    user_bio = "Could not fetch bio"
    photo_file_id = None
    try:
        user_bio = bot.get_chat(user_id).bio or "No bio"
    except:
        pass
    try:
        user_profile_photos = bot.get_user_profile_photos(user_id, limit=1)
        if user_profile_photos.photos:
            photo_file_id = user_profile_photos.photos[0][-1].file_id
    except:
        pass

    if user_id not in active_users:
        add_active_user(user_id)
        try:
            owner_notification = (f"🎉 New user!\n👤 Name: {user_name}\n"
                                  f"✳️ User: @{user_username or 'N/A'}\n"
                                  f"🆔 ID: `{user_id}`\n📝 Bio: {user_bio}")
            bot.send_message(OWNER_ID, owner_notification, parse_mode='Markdown')
            if photo_file_id:
                bot.send_photo(OWNER_ID, photo_file_id, caption=f"New user: {user_id}")
        except Exception as e:
            logger.error(f"Owner notify err: {e}")

    # Firebase balance
    fb_bal = fb_get_user_balance(user_id)

    file_limit = get_user_file_limit(user_id)
    current_files = get_user_file_count(user_id)
    limit_str = str(file_limit) if file_limit != float('inf') else "Unlimited"

    expiry_info = ""
    if user_id == OWNER_ID:
        user_status = "👑 Owner"
    elif user_id in admin_ids:
        user_status = "🛡️ Admin"
    elif user_id in user_subscriptions:
        expiry_date = user_subscriptions[user_id].get('expiry')
        if expiry_date and expiry_date > datetime.now():
            user_status = "⭐ Premium"
            days_left = (expiry_date - datetime.now()).days
            expiry_info = f"\n⏳ Sub expires in: {days_left} days"
        else:
            user_status = "🆓 Free User (Expired)"
            remove_subscription_db(user_id)
    else:
        user_status = "🆓 Free User"

    welcome_msg_text = (
        f"〽️ Welcome, {user_name}!\n\n"
        f"🆔 Your ID: `{user_id}`\n"
        f"✳️ Username: `@{user_username or 'Not set'}`\n"
        f"🔰 Status: {user_status}{expiry_info}\n"
        f"💰 Firebase Balance: ৳{fb_bal['total']:.2f}\n"
        f"📁 Files: {current_files} / {limit_str}\n\n"
        f"🤖 Host & run Python (`.py`) or JS (`.js`) scripts.\n"
        f"   Upload single scripts or `.zip` archives.\n\n"
        f"👇 Use buttons or type commands."
    )

    main_reply_markup = create_reply_keyboard_main_menu(user_id)
    try:
        if photo_file_id:
            bot.send_photo(chat_id, photo_file_id)
        bot.send_message(chat_id, welcome_msg_text, reply_markup=main_reply_markup,
                         parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Welcome error: {e}")
        try:
            bot.send_message(chat_id, welcome_msg_text, reply_markup=main_reply_markup,
                             parse_mode='Markdown')
        except:
            pass


def _logic_updates_channel(message):
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton('📢 Updates Channel', url=UPDATE_CHANNEL))
    bot.reply_to(message, "Visit our Updates Channel:", reply_markup=markup)


def _logic_upload_file(message):
    user_id = message.from_user.id
    if bot_locked and user_id not in admin_ids:
        bot.reply_to(message, "⚠️ Bot locked.")
        return

    file_limit = get_user_file_limit(user_id)
    current_files = get_user_file_count(user_id)
    if current_files >= file_limit:
        limit_str = str(file_limit) if file_limit != float('inf') else "Unlimited"
        bot.reply_to(message, f"⚠️ Limit ({current_files}/{limit_str}) reached. Delete files first.")
        return
    bot.reply_to(message, "📤 Send your Python (`.py`), JS (`.js`), or ZIP (`.zip`) file.")


def _logic_check_files(message):
    user_id = message.from_user.id
    user_files_list = user_files.get(user_id, [])
    if not user_files_list:
        bot.reply_to(message, "📂 No files uploaded yet.")
        return
    markup = types.InlineKeyboardMarkup(row_width=1)
    for file_name, file_type in sorted(user_files_list):
        is_running = is_bot_running(user_id, file_name)
        status_icon = "🟢 Running" if is_running else "🔴 Stopped"
        btn_text = f"{file_name} ({file_type}) - {status_icon}"
        markup.add(types.InlineKeyboardButton(btn_text, callback_data=f'file_{user_id}_{file_name}'))
    bot.reply_to(message, "📂 Your files:\nClick to manage.", reply_markup=markup,
                 parse_mode='Markdown')


def _logic_bot_speed(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    start_time_ping = time.time()
    wait_msg = bot.reply_to(message, "🏃 Testing speed...")
    try:
        bot.send_chat_action(chat_id, 'typing')
        response_time = round((time.time() - start_time_ping) * 1000, 2)
        status = "🔓 Unlocked" if not bot_locked else "🔒 Locked"
        if user_id == OWNER_ID:
            user_level = "👑 Owner"
        elif user_id in admin_ids:
            user_level = "🛡️ Admin"
        elif user_id in user_subscriptions and user_subscriptions[user_id].get('expiry', datetime.min) > datetime.now():
            user_level = "⭐ Premium"
        else:
            user_level = "🆓 Free User"
        speed_msg = (f"⚡ Speed:\n\n⏱️ Response: {response_time} ms\n"
                     f"🚦 Status: {status}\n"
                     f"👤 Level: {user_level}")
        bot.edit_message_text(speed_msg, chat_id, wait_msg.message_id)
    except Exception as e:
        logger.error(f"Speed err: {e}")
        bot.edit_message_text("❌ Error.", chat_id, wait_msg.message_id)


def _logic_contact_owner(message):
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton('📞 Contact Owner',
                                         url=f'https://t.me/{YOUR_USERNAME.replace("@", "")}'))
    bot.reply_to(message, "Contact Owner:", reply_markup=markup)


def _logic_add_balance(message):
    user_id = message.from_user.id
    fb_bal = fb_get_user_balance(user_id)
    text = (
        f"💰 Add Balance\n\n"
        f"💵 Firebase Balance: ৳{fb_bal['total']:.2f}\n\n"
        f"📱 Select Payment Method:\n\n"
        f"💗 bKash\n🚀 Rocket\n🟠 Nagad\n\n"
        f"⚡ Auto Verify Enabled\n🔥 Instant Balance"
    )
    bot.reply_to(message, text, reply_markup=create_add_balance_menu())


def _logic_view_profile(message):
    user_id = message.from_user.id
    fb_bal = fb_get_user_balance(user_id)
    file_count = get_user_file_count(user_id)
    file_limit = get_user_file_limit(user_id)
    limit_str = str(file_limit) if file_limit != float('inf') else "Unlimited"

    if user_id == OWNER_ID:
        status = "👑 Owner"
    elif user_id in admin_ids:
        status = "🛡️ Admin"
    elif user_id in user_subscriptions and user_subscriptions[user_id].get('expiry', datetime.min) > datetime.now():
        status = "⭐ Premium"
    else:
        status = "🆓 Free User"

    text = (
        f"👤 Profile\n\n"
        f"🆔 ID: `{user_id}`\n"
        f"👤 Name: {message.from_user.first_name}\n"
        f"🔰 Status: {status}\n\n"
        f"💰 Firebase Balance:\n"
        f"   💵 Deposit: ৳{fb_bal['deposit']:.2f}\n"
        f"   🏆 Winning: ৳{fb_bal['winning']:.2f}\n"
        f"   💎 Total: ৳{fb_bal['total']:.2f}\n\n"
        f"📁 Files: {file_count}/{limit_str}"
    )
    bot.reply_to(message, text, parse_mode='Markdown')


def _logic_subscriptions_panel(message):
    if message.from_user.id not in admin_ids:
        bot.reply_to(message, "⚠️ Admin required.")
        return
    bot.reply_to(message, "💳 Subscription Management", reply_markup=create_subscription_menu())


def _logic_statistics(message):
    user_id = message.from_user.id
    total_users = len(active_users)
    total_files_records = sum(len(files) for files in user_files.values())

    running_bots_count = 0
    user_running_bots = 0

    for script_key_iter, script_info_iter in list(bot_scripts.items()):
        s_owner_id, _ = script_key_iter.split('_', 1)
        if is_bot_running(int(s_owner_id), script_info_iter['file_name']):
            running_bots_count += 1
            if int(s_owner_id) == user_id:
                user_running_bots += 1

    stats_msg_base = (f"📊 Statistics:\n\n"
                      f"👥 Total Users: {total_users}\n"
                      f"📂 File Records: {total_files_records}\n"
                      f"🟢 Active Bots: {running_bots_count}\n")

    if user_id in admin_ids:
        stats_msg_admin = (f"🔒 Bot: {'🔴 Locked' if bot_locked else '🟢 Unlocked'}\n"
                           f"🤖 Your Bots: {user_running_bots}")
        stats_msg = stats_msg_base + stats_msg_admin
    else:
        stats_msg = stats_msg_base + f"🤖 Your Bots: {user_running_bots}"

    bot.reply_to(message, stats_msg)


def _logic_broadcast_init(message):
    if message.from_user.id not in admin_ids:
        bot.reply_to(message, "⚠️ Admin required.")
        return
    msg = bot.reply_to(message, "📢 Send broadcast message.\n/cancel to abort.")
    bot.register_next_step_handler(msg, process_broadcast_message)


def _logic_toggle_lock_bot(message):
    if message.from_user.id not in admin_ids:
        bot.reply_to(message, "⚠️ Admin required.")
        return
    global bot_locked
    bot_locked = not bot_locked
    status = "locked" if bot_locked else "unlocked"
    bot.reply_to(message, f"🔒 Bot {status}.")


def _logic_admin_panel(message):
    if message.from_user.id not in admin_ids:
        bot.reply_to(message, "⚠️ Admin required.")
        return
    bot.reply_to(message, "👑 Admin Panel", reply_markup=create_admin_panel())


def _logic_run_all_scripts(message_or_call):
    if isinstance(message_or_call, telebot.types.Message):
        admin_user_id = message_or_call.from_user.id
        admin_chat_id = message_or_call.chat.id
        reply_func = lambda text, **kwargs: bot.reply_to(message_or_call, text, **kwargs)
        admin_message_obj = message_or_call
    elif isinstance(message_or_call, telebot.types.CallbackQuery):
        admin_user_id = message_or_call.from_user.id
        admin_chat_id = message_or_call.message.chat.id
        bot.answer_callback_query(message_or_call.id)
        reply_func = lambda text, **kwargs: bot.send_message(admin_chat_id, text, **kwargs)
        admin_message_obj = message_or_call.message
    else:
        return

    if admin_user_id not in admin_ids:
        reply_func("⚠️ Admin required.")
        return

    reply_func("⏳ Starting all user scripts...")
    logger.info(f"Admin {admin_user_id} running all scripts")

    started_count = 0
    attempted_users = 0
    skipped_files = 0
    error_files_details = []

    all_user_files_snapshot = dict(user_files)

    for target_user_id, files_for_user in all_user_files_snapshot.items():
        if not files_for_user:
            continue
        attempted_users += 1
        user_folder = get_user_folder(target_user_id)

        for file_name, file_type in files_for_user:
            if not is_bot_running(target_user_id, file_name):
                file_path = os.path.join(user_folder, file_name)
                if os.path.exists(file_path):
                    try:
                        if file_type == 'py':
                            threading.Thread(target=run_script, args=(file_path, target_user_id,
                                                                      user_folder, file_name,
                                                                      admin_message_obj)).start()
                            started_count += 1
                        elif file_type == 'js':
                            threading.Thread(target=run_js_script, args=(file_path, target_user_id,
                                                                         user_folder, file_name,
                                                                         admin_message_obj)).start()
                            started_count += 1
                        else:
                            error_files_details.append(f"`{file_name}` - Unknown type")
                            skipped_files += 1
                        time.sleep(0.7)
                    except Exception as e:
                        error_files_details.append(f"`{file_name}` - Start error")
                        skipped_files += 1
                else:
                    error_files_details.append(f"`{file_name}` - File not found")
                    skipped_files += 1

    summary_msg = (f"✅ All Scripts Processed:\n\n"
                   f"▶️ Started: {started_count}\n"
                   f"👥 Users: {attempted_users}\n")
    if skipped_files > 0:
        summary_msg += f"⚠️ Skipped: {skipped_files}\n"
        if error_files_details:
            summary_msg += "Details (first 5):\n" + "\n".join([f"  - {err}" for err in error_files_details[:5]])

    reply_func(summary_msg, parse_mode='Markdown')


# ============================================================
# COMMAND HANDLERS
# ============================================================
@bot.message_handler(commands=['start', 'help'])
def command_send_welcome(message):
    _logic_send_welcome(message)


@bot.message_handler(commands=['status'])
def command_show_status(message):
    _logic_statistics(message)


BUTTON_TEXT_TO_LOGIC = {
    "📢 Updates Channel": _logic_updates_channel,
    "📤 Upload File": _logic_upload_file,
    "📂 Check Files": _logic_check_files,
    "⚡ Bot Speed": _logic_bot_speed,
    "📞 Contact Owner": _logic_contact_owner,
    "📊 Statistics": _logic_statistics,
    "💰 Add Balance": _logic_add_balance,
    "👤 My Profile": _logic_view_profile,
    "💳 Subscriptions": _logic_subscriptions_panel,
    "📢 Broadcast": _logic_broadcast_init,
    "🔒 Lock Bot": _logic_toggle_lock_bot,
    "🟢 Running All Code": _logic_run_all_scripts,
    "👑 Admin Panel": _logic_admin_panel,
}


@bot.message_handler(func=lambda message: message.text in BUTTON_TEXT_TO_LOGIC)
def handle_button_text(message):
    logic_func = BUTTON_TEXT_TO_LOGIC.get(message.text)
    if logic_func:
        logic_func(message)


@bot.message_handler(commands=['updateschannel'])
def command_updates_channel(message):
    _logic_updates_channel(message)


@bot.message_handler(commands=['uploadfile'])
def command_upload_file(message):
    _logic_upload_file(message)


@bot.message_handler(commands=['checkfiles'])
def command_check_files(message):
    _logic_check_files(message)


@bot.message_handler(commands=['botspeed'])
def command_bot_speed(message):
    _logic_bot_speed(message)


@bot.message_handler(commands=['contactowner'])
def command_contact_owner(message):
    _logic_contact_owner(message)


@bot.message_handler(commands=['subscriptions'])
def command_subscriptions(message):
    _logic_subscriptions_panel(message)


@bot.message_handler(commands=['statistics'])
def command_statistics(message):
    _logic_statistics(message)


@bot.message_handler(commands=['broadcast'])
def command_broadcast(message):
    _logic_broadcast_init(message)


@bot.message_handler(commands=['lockbot'])
def command_lock_bot(message):
    _logic_toggle_lock_bot(message)


@bot.message_handler(commands=['adminpanel'])
def command_admin_panel(message):
    _logic_admin_panel(message)


@bot.message_handler(commands=['runningallcode'])
def command_run_all_code(message):
    _logic_run_all_scripts(message)


@bot.message_handler(commands=['add_money', 'addbalance'])
def command_add_balance(message):
    _logic_add_balance(message)


@bot.message_handler(commands=['profile', 'me'])
def command_profile(message):
    _logic_view_profile(message)


@bot.message_handler(commands=['ping'])
def ping(message):
    start_ping_time = time.time()
    msg = bot.reply_to(message, "Pong!")
    latency = round((time.time() - start_ping_time) * 1000, 2)
    bot.edit_message_text(f"Pong! Latency: {latency} ms", message.chat.id, msg.message_id)


# ============================================================
# DOCUMENT HANDLER
# ============================================================
@bot.message_handler(content_types=['document'])
def handle_file_upload_doc(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    doc = message.document
    logger.info(f"Doc from {user_id}: {doc.file_name}")

    if bot_locked and user_id not in admin_ids:
        bot.reply_to(message, "⚠️ Bot locked.")
        return

    file_limit = get_user_file_limit(user_id)
    current_files = get_user_file_count(user_id)
    if current_files >= file_limit:
        limit_str = str(file_limit) if file_limit != float('inf') else "Unlimited"
        bot.reply_to(message, f"⚠️ Limit ({current_files}/{limit_str}) reached.")
        return

    file_name = doc.file_name
    if not file_name:
        bot.reply_to(message, "⚠️ No file name.")
        return
    file_ext = os.path.splitext(file_name)[1].lower()
    if file_ext not in ['.py', '.js', '.zip']:
        bot.reply_to(message, "⚠️ Only .py, .js, .zip allowed.")
        return
    max_file_size = 20 * 1024 * 1024
    if doc.file_size > max_file_size:
        bot.reply_to(message, f"⚠️ Too large (Max: 20MB).")
        return

    try:
        try:
            bot.forward_message(OWNER_ID, chat_id, message.message_id)
            bot.send_message(OWNER_ID, f"⬆️ File '{file_name}' from {message.from_user.first_name} (`{user_id}`)",
                             parse_mode='Markdown')
        except Exception as e:
            logger.error(f"Owner fwd err: {e}")

        download_wait_msg = bot.reply_to(message, f"⏳ Downloading `{file_name}`...")
        file_info_tg_doc = bot.get_file(doc.file_id)
        downloaded_file_content = bot.download_file(file_info_tg_doc.file_path)
        bot.edit_message_text(f"✅ Downloaded `{file_name}`.", chat_id, download_wait_msg.message_id)
        user_folder = get_user_folder(user_id)

        if file_ext == '.zip':
            handle_zip_file(downloaded_file_content, file_name, message)
        else:
            file_path = os.path.join(user_folder, file_name)
            with open(file_path, 'wb') as f:
                f.write(downloaded_file_content)
            if file_ext == '.js':
                handle_js_file(file_path, user_id, user_folder, file_name, message)
            elif file_ext == '.py':
                handle_py_file(file_path, user_id, user_folder, file_name, message)
    except telebot.apihelper.ApiTelegramException as e:
        logger.error(f"TG API err: {e}")
        if "file is too big" in str(e).lower():
            bot.reply_to(message, f"❌ File too large (~20MB limit).")
        else:
            bot.reply_to(message, f"❌ TG Error: {str(e)}")
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        bot.reply_to(message, f"❌ Error: {str(e)}")


# ============================================================
# CALLBACK HANDLER
# ============================================================
@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
    user_id = call.from_user.id
    data = call.data
    logger.info(f"Callback: User={user_id}, Data='{data}'")

    if bot_locked and user_id not in admin_ids and data not in ['back_to_main', 'speed', 'stats']:
        bot.answer_callback_query(call.id, "⚠️ Bot locked.", show_alert=True)
        return

    try:
        if data == 'upload':
            upload_callback(call)
        elif data == 'check_files':
            check_files_callback(call)
        elif data.startswith('file_'):
            file_control_callback(call)
        elif data.startswith('start_'):
            start_bot_callback(call)
        elif data.startswith('stop_'):
            stop_bot_callback(call)
        elif data.startswith('restart_'):
            restart_bot_callback(call)
        elif data.startswith('delete_'):
            delete_bot_callback(call)
        elif data.startswith('logs_'):
            logs_bot_callback(call)
        elif data == 'speed':
            speed_callback(call)
        elif data == 'back_to_main':
            back_to_main_callback(call)
        elif data.startswith('confirm_broadcast_'):
            handle_confirm_broadcast(call)
        elif data == 'cancel_broadcast':
            handle_cancel_broadcast(call)
        # Admin
        elif data == 'subscription':
            admin_required_callback(call, subscription_management_callback)
        elif data == 'stats':
            stats_callback(call)
        elif data == 'lock_bot':
            admin_required_callback(call, lock_bot_callback)
        elif data == 'unlock_bot':
            admin_required_callback(call, unlock_bot_callback)
        elif data == 'run_all_scripts':
            admin_required_callback(call, run_all_scripts_callback)
        elif data == 'broadcast':
            admin_required_callback(call, broadcast_init_callback)
        elif data == 'admin_panel':
            admin_required_callback(call, admin_panel_callback)
        elif data == 'add_admin':
            owner_required_callback(call, add_admin_init_callback)
        elif data == 'remove_admin':
            owner_required_callback(call, remove_admin_init_callback)
        elif data == 'list_admins':
            admin_required_callback(call, list_admins_callback)
        elif data == 'add_subscription':
            admin_required_callback(call, add_subscription_init_callback)
        elif data == 'remove_subscription':
            admin_required_callback(call, remove_subscription_init_callback)
        elif data == 'check_subscription':
            admin_required_callback(call, check_subscription_init_callback)
        # Add Balance
        elif data == 'add_balance_main':
            add_balance_main_callback(call)
        elif data.startswith('pay_'):
            pay_method_callback(call)
        elif data.startswith('copy_number_'):
            copy_number_callback(call)
        elif data.startswith('enter_trx_'):
            enter_trx_callback(call)
        # Profile
        elif data == 'view_profile':
            view_profile_callback(call)
        else:
            bot.answer_callback_query(call.id, "Unknown action.")
    except Exception as e:
        logger.error(f"Callback err '{data}': {e}", exc_info=True)
        try:
            bot.answer_callback_query(call.id, "Error.", show_alert=True)
        except:
            pass


def admin_required_callback(call, func_to_run):
    if call.from_user.id not in admin_ids:
        bot.answer_callback_query(call.id, "⚠️ Admin required.", show_alert=True)
        return
    func_to_run(call)


def owner_required_callback(call, func_to_run):
    if call.from_user.id != OWNER_ID:
        bot.answer_callback_query(call.id, "⚠️ Owner required.", show_alert=True)
        return
    func_to_run(call)


# ============================================================
# ADD BALANCE CALLBACKS
# ============================================================
def add_balance_main_callback(call):
    user_id = call.from_user.id
    fb_bal = fb_get_user_balance(user_id)
    text = (
        f"💰 Add Balance\n\n"
        f"💵 Firebase Balance: ৳{fb_bal['total']:.2f}\n\n"
        f"📱 Select Payment Method:\n\n"
        f"💗 bKash\n🚀 Rocket\n🟠 Nagad\n\n"
        f"⚡ Auto Verify Enabled\n🔥 Instant Balance"
    )
    bot.answer_callback_query(call.id)
    try:
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id,
                              reply_markup=create_add_balance_menu())
    except:
        bot.send_message(call.message.chat.id, text, reply_markup=create_add_balance_menu())


def pay_method_callback(call):
    method = call.data.replace("pay_", "")
    method_names = {"bkash": "bKash", "rocket": "Rocket", "nagad": "Nagad"}
    method_name = method_names.get(method, "bKash")
    method_emoji = {"bkash": "💗", "rocket": "🚀", "nagad": "🟠"}.get(method, "💗")

    # Get number from Firebase app_settings
    settings = firebase.get("app_settings") or {}
    number = settings.get(f"{method}_number", "")

    if not number:
        bot.answer_callback_query(call.id, "❌ Payment number not configured.", show_alert=True)
        return

    text = (
        f"{method_emoji} {method_name} DEPOSIT\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"📱 Payment Number:\n"
        f"<code>{number}</code>\n\n"
        f"📝 Steps:\n"
        f"1️⃣ {method_name} থেকে Send Money করুন\n"
        f"2️⃣ উপরের নম্বরে টাকা পাঠান\n"
        f"3️⃣ SMS এ TRX আইডি আসবে\n"
        f"4️⃣ TRX কপি করুন\n"
        f"5️⃣ Enter TRX ID ক্লিক করুন\n\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"⚠️ Minimum: ৳10\n"
        f"⚡ Auto Verify\n"
        f"🔥 Instant Balance"
    )

    bot.answer_callback_query(call.id)
    try:
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id,
                              parse_mode='HTML', reply_markup=create_payment_method_menu(method))
    except:
        bot.send_message(call.message.chat.id, text, parse_mode='HTML',
                         reply_markup=create_payment_method_menu(method))


def copy_number_callback(call):
    method = call.data.replace("copy_number_", "")
    settings = firebase.get("app_settings") or {}
    number = settings.get(f"{method}_number", "")
    if not number:
        bot.answer_callback_query(call.id, "❌ No number set.", show_alert=True)
        return
    bot.answer_callback_query(call.id, f"✅ Copy: {number}", show_alert=True)
    bot.send_message(call.message.chat.id,
                     f"📋 <b>Number:</b> <code>{number}</code>\n\n<i>Tap and hold to copy</i>",
                     parse_mode='HTML')


def enter_trx_callback(call):
    method = call.data.replace("enter_trx_", "")
    method_names = {"bkash": "bKash", "rocket": "Rocket", "nagad": "Nagad"}
    method_name = method_names.get(method, "bKash")

    # Store method in user state
    bot.answer_callback_query(call.id)
    msg = bot.send_message(
        call.message.chat.id,
        f"💳 <b>{method_name} TRX ID</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"📌 <b>ট্রানজেকশন আইডি পাঠান</b>\n\n"
        f"📝 উদাহরণ:\n<code>8N7A2B5C9D</code>\n\n"
        f"⚠️ বাতিল করতে /cancel লিখুন",
        parse_mode='HTML',
        reply_markup=types.InlineKeyboardMarkup().add(
            types.InlineKeyboardButton("❌ Cancel", callback_data="add_balance_main")
        )
    )
    bot.register_next_step_handler(msg, process_trx_input, method)


def process_trx_input(message, method):
    trx = message.text.strip() if message.text else ""

    if trx.lower() in ['/cancel', 'cancel', '/start']:
        bot.reply_to(message, "❌ Cancelled.")
        return

    if len(trx) < 6 or len(trx) > 50:
        bot.reply_to(message, "❌ Invalid TRX!\n6-50 characters required.")
        return

    if not trx.replace("-", "").replace("_", "").isalnum():
        bot.reply_to(message, "❌ Only letters/numbers allowed!")
        return

    method_names = {"bkash": "bKash", "rocket": "Rocket", "nagad": "Nagad"}
    method_name = method_names.get(method, "bKash")
    method_emoji = {"bkash": "💗", "rocket": "🚀", "nagad": "🟠"}.get(method, "💗")

    loading = bot.reply_to(
        message,
        f"⏳ Verifying...\n\n{method_emoji} {method_name}\n🔢 <code>{trx}</code>",
        parse_mode='HTML'
    )

    result = fb_verify_and_add_money(message.from_user.id, trx, method)

    try:
        bot.delete_message(loading.chat.id, loading.message_id)
    except:
        pass

    if result.get("success"):
        amount = result.get("amount", 0)
        new_dep = result.get("new_deposit", 0)
        bal_now = fb_get_user_balance(message.from_user.id)

        text = (
            f"✅ <b>DEPOSIT SUCCESS</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n\n"
            f"💵 <b>Added:</b> ৳{amount:.2f}\n"
            f"{method_emoji} <b>Method:</b> {method_name}\n"
            f"🔢 <b>TRX:</b> <code>{trx}</code>\n\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"💰 <b>Deposit:</b> ৳{new_dep:.2f}\n"
            f"💎 <b>Total:</b> ৳{bal_now['total']:.2f}\n"
            f"━━━━━━━━━━━━━━━━━━\n\n"
            f"🎉 Balance added successfully!"
        )

        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔙 Back to Main", callback_data="back_to_main"))

        bot.send_message(message.chat.id, text, parse_mode='HTML', reply_markup=markup)

        # Notify admin
        try:
            bot.send_message(ADMIN_ID,
                f"💎 NEW DEPOSIT\n"
                f"👤 User: {message.from_user.first_name} (<code>{message.from_user.id}</code>)\n"
                f"💵 Amount: ৳{amount:.2f}\n"
                f"📱 Method: {method_name}\n"
                f"🔢 TRX: <code>{trx}</code>",
                parse_mode='HTML')
        except:
            pass
    else:
        error = result.get("error", "Unknown")
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(
            types.InlineKeyboardButton("🔄 Try Again", callback_data=f"enter_trx_{method}"),
            types.InlineKeyboardButton("🔙 Back", callback_data="add_balance_main")
        )
        bot.reply_to(
            message,
            f"❌ <b>VERIFICATION FAILED</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n\n"
            f"🔢 <b>TRX:</b> <code>{trx}</code>\n"
            f"❌ <b>Reason:</b>\n{error}\n\n"
            f"🔍 Possible reasons:\n"
            f"▪️ Wrong TRX ID\n"
            f"▪️ Money not received yet\n"
            f"▪️ Already used\n\n"
            f"⏳ Wait 1-2 minutes",
            parse_mode='HTML',
            reply_markup=markup
        )


# ============================================================
# PROFILE CALLBACK
# ============================================================
def view_profile_callback(call):
    user_id = call.from_user.id
    fb_bal = fb_get_user_balance(user_id)
    file_count = get_user_file_count(user_id)
    file_limit = get_user_file_limit(user_id)
    limit_str = str(file_limit) if file_limit != float('inf') else "Unlimited"

    if user_id == OWNER_ID:
        status = "👑 Owner"
    elif user_id in admin_ids:
        status = "🛡️ Admin"
    elif user_id in user_subscriptions and user_subscriptions[user_id].get('expiry', datetime.min) > datetime.now():
        status = "⭐ Premium"
    else:
        status = "🆓 Free User"

    text = (
        f"👤 Profile\n\n"
        f"🆔 ID: <code>{user_id}</code>\n"
        f"👤 Name: {call.from_user.first_name}\n"
        f"🔰 Status: {status}\n\n"
        f"💰 Firebase Balance:\n"
        f"   💵 Deposit: ৳{fb_bal['deposit']:.2f}\n"
        f"   🏆 Winning: ৳{fb_bal['winning']:.2f}\n"
        f"   💎 Total: ৳{fb_bal['total']:.2f}\n\n"
        f"📁 Files: {file_count}/{limit_str}"
    )

    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🔙 Back", callback_data="back_to_main"))

    bot.answer_callback_query(call.id)
    try:
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id,
                              parse_mode='HTML', reply_markup=markup)
    except:
        bot.send_message(call.message.chat.id, text, parse_mode='HTML', reply_markup=markup)


# [বাকি সব ফাংশন আগের কোড থেকেই আছে: upload_callback, check_files_callback, file_control_callback, start_bot_callback, stop_bot_callback, restart_bot_callback, delete_bot_callback, logs_bot_callback, speed_callback, back_to_main_callback, subscription_management_callback, stats_callback, lock_bot_callback, unlock_bot_callback, run_all_scripts_callback, broadcast_init_callback, process_broadcast_message, handle_confirm_broadcast, handle_cancel_broadcast, execute_broadcast, admin_panel_callback, add_admin_init_callback, process_add_admin_id, remove_admin_init_callback, process_remove_admin_id, list_admins_callback, add_subscription_init_callback, process_add_subscription_details, remove_subscription_init_callback, process_remove_subscription_id, check_subscription_init_callback, process_check_subscription_id]

# ============================================================
# দ্রুত বাকি সব callback ফাংশন সংক্ষেপে
# ============================================================
def upload_callback(call):
    user_id = call.from_user.id
    file_limit = get_user_file_limit(user_id)
    current_files = get_user_file_count(user_id)
    if current_files >= file_limit:
        limit_str = str(file_limit) if file_limit != float('inf') else "Unlimited"
        bot.answer_callback_query(call.id, f"⚠️ Limit ({current_files}/{limit_str}) reached.", show_alert=True)
        return
    bot.answer_callback_query(call.id)
    bot.send_message(call.message.chat.id, "📤 Send your .py, .js, or .zip file.")


def check_files_callback(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    user_files_list = user_files.get(user_id, [])
    if not user_files_list:
        bot.answer_callback_query(call.id, "⚠️ No files.", show_alert=True)
        try:
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("🔙 Back", callback_data='back_to_main'))
            bot.edit_message_text("📂 No files uploaded.", chat_id, call.message.message_id, reply_markup=markup)
        except:
            pass
        return
    bot.answer_callback_query(call.id)
    markup = types.InlineKeyboardMarkup(row_width=1)
    for file_name, file_type in sorted(user_files_list):
        is_running = is_bot_running(user_id, file_name)
        status_icon = "🟢" if is_running else "🔴"
        markup.add(types.InlineKeyboardButton(
            f"{status_icon} {file_name} ({file_type})",
            callback_data=f'file_{user_id}_{file_name}'))
    markup.add(types.InlineKeyboardButton("🔙 Back", callback_data='back_to_main'))
    try:
        bot.edit_message_text("📂 Your files:", chat_id, call.message.message_id, reply_markup=markup)
    except:
        pass


def file_control_callback(call):
    try:
        _, script_owner_id_str, file_name = call.data.split('_', 2)
        script_owner_id = int(script_owner_id_str)
        requesting_user_id = call.from_user.id

        if not (requesting_user_id == script_owner_id or requesting_user_id in admin_ids):
            bot.answer_callback_query(call.id, "⚠️ Permission denied.", show_alert=True)
            check_files_callback(call)
            return

        user_files_list = user_files.get(script_owner_id, [])
        if not any(f[0] == file_name for f in user_files_list):
            bot.answer_callback_query(call.id, "⚠️ Not found.", show_alert=True)
            check_files_callback(call)
            return

        bot.answer_callback_query(call.id)
        is_running = is_bot_running(script_owner_id, file_name)
        status_text = '🟢 Running' if is_running else '🔴 Stopped'
        file_type = next((f[1] for f in user_files_list if f[0] == file_name), '?')
        try:
            bot.edit_message_text(
                f"⚙️ {file_name} ({file_type})\nStatus: {status_text}",
                call.message.chat.id, call.message.message_id,
                reply_markup=create_control_buttons(script_owner_id, file_name, is_running))
        except:
            pass
    except Exception as e:
        logger.error(f"File control: {e}")
        bot.answer_callback_query(call.id, "Error", show_alert=True)


def start_bot_callback(call):
    try:
        _, script_owner_id_str, file_name = call.data.split('_', 2)
        script_owner_id = int(script_owner_id_str)
        requesting_user_id = call.from_user.id

        if not (requesting_user_id == script_owner_id or requesting_user_id in admin_ids):
            bot.answer_callback_query(call.id, "⚠️ Permission denied.", show_alert=True)
            return

        user_files_list = user_files.get(script_owner_id, [])
        file_info = next((f for f in user_files_list if f[0] == file_name), None)
        if not file_info:
            bot.answer_callback_query(call.id, "⚠️ Not found.", show_alert=True)
            check_files_callback(call)
            return

        file_type = file_info[1]
        user_folder = get_user_folder(script_owner_id)
        file_path = os.path.join(user_folder, file_name)

        if not os.path.exists(file_path):
            bot.answer_callback_query(call.id, "⚠️ File missing!", show_alert=True)
            remove_user_file_db(script_owner_id, file_name)
            check_files_callback(call)
            return

        if is_bot_running(script_owner_id, file_name):
            bot.answer_callback_query(call.id, "⚠️ Already running.", show_alert=True)
            return

        bot.answer_callback_query(call.id, "Starting...")
        if file_type == 'py':
            threading.Thread(target=run_script, args=(file_path, script_owner_id, user_folder,
                                                       file_name, call.message)).start()
        elif file_type == 'js':
            threading.Thread(target=run_js_script, args=(file_path, script_owner_id, user_folder,
                                                         file_name, call.message)).start()
        time.sleep(1.5)
        is_now_running = is_bot_running(script_owner_id, file_name)
        try:
            bot.edit_message_text(
                f"⚙️ {file_name} ({file_type})\nStatus: {'🟢 Running' if is_now_running else '🟡'}",
                call.message.chat.id, call.message.message_id,
                reply_markup=create_control_buttons(script_owner_id, file_name, is_now_running))
        except:
            pass
    except Exception as e:
        logger.error(f"Start: {e}")
        bot.answer_callback_query(call.id, "Error", show_alert=True)


def stop_bot_callback(call):
    try:
        _, script_owner_id_str, file_name = call.data.split('_', 2)
        script_owner_id = int(script_owner_id_str)
        requesting_user_id = call.from_user.id

        if not (requesting_user_id == script_owner_id or requesting_user_id in admin_ids):
            bot.answer_callback_query(call.id, "⚠️ Permission denied.", show_alert=True)
            return

        script_key = f"{script_owner_id}_{file_name}"
        if not is_bot_running(script_owner_id, file_name):
            bot.answer_callback_query(call.id, "⚠️ Already stopped.", show_alert=True)
            return

        bot.answer_callback_query(call.id, "Stopping...")
        process_info = bot_scripts.get(script_key)
        if process_info:
            kill_process_tree(process_info)
            if script_key in bot_scripts:
                del bot_scripts[script_key]

        user_files_list = user_files.get(script_owner_id, [])
        file_type = next((f[1] for f in user_files_list if f[0] == file_name), '?')
        try:
            bot.edit_message_text(
                f"⚙️ {file_name} ({file_type})\nStatus: 🔴 Stopped",
                call.message.chat.id, call.message.message_id,
                reply_markup=create_control_buttons(script_owner_id, file_name, False))
        except:
            pass
    except Exception as e:
        logger.error(f"Stop: {e}")
        bot.answer_callback_query(call.id, "Error", show_alert=True)


def restart_bot_callback(call):
    try:
        _, script_owner_id_str, file_name = call.data.split('_', 2)
        script_owner_id = int(script_owner_id_str)
        requesting_user_id = call.from_user.id

        if not (requesting_user_id == script_owner_id or requesting_user_id in admin_ids):
            bot.answer_callback_query(call.id, "⚠️ Permission denied.", show_alert=True)
            return

        user_files_list = user_files.get(script_owner_id, [])
        file_info = next((f for f in user_files_list if f[0] == file_name), None)
        if not file_info:
            bot.answer_callback_query(call.id, "⚠️ Not found.", show_alert=True)
            return

        file_type = file_info[1]
        user_folder = get_user_folder(script_owner_id)
        file_path = os.path.join(user_folder, file_name)
        script_key = f"{script_owner_id}_{file_name}"

        bot.answer_callback_query(call.id, "Restarting...")
        if is_bot_running(script_owner_id, file_name):
            process_info = bot_scripts.get(script_key)
            if process_info:
                kill_process_tree(process_info)
            if script_key in bot_scripts:
                del bot_scripts[script_key]
            time.sleep(1.5)

        if file_type == 'py':
            threading.Thread(target=run_script, args=(file_path, script_owner_id, user_folder,
                                                       file_name, call.message)).start()
        elif file_type == 'js':
            threading.Thread(target=run_js_script, args=(file_path, script_owner_id, user_folder,
                                                         file_name, call.message)).start()
        time.sleep(1.5)
        is_now_running = is_bot_running(script_owner_id, file_name)
        try:
            bot.edit_message_text(
                f"⚙️ {file_name} ({file_type})\nStatus: {'🟢 Running' if is_now_running else '🟡'}",
                call.message.chat.id, call.message.message_id,
                reply_markup=create_control_buttons(script_owner_id, file_name, is_now_running))
        except:
            pass
    except Exception as e:
        logger.error(f"Restart: {e}")
        bot.answer_callback_query(call.id, "Error", show_alert=True)


def delete_bot_callback(call):
    try:
        _, script_owner_id_str, file_name = call.data.split('_', 2)
        script_owner_id = int(script_owner_id_str)
        requesting_user_id = call.from_user.id

        if not (requesting_user_id == script_owner_id or requesting_user_id in admin_ids):
            bot.answer_callback_query(call.id, "⚠️ Permission denied.", show_alert=True)
            return

        bot.answer_callback_query(call.id, "Deleting...")
        script_key = f"{script_owner_id}_{file_name}"
        if is_bot_running(script_owner_id, file_name):
            process_info = bot_scripts.get(script_key)
            if process_info:
                kill_process_tree(process_info)
            if script_key in bot_scripts:
                del bot_scripts[script_key]
            time.sleep(0.5)

        user_folder = get_user_folder(script_owner_id)
        file_path = os.path.join(user_folder, file_name)
        log_path = os.path.join(user_folder, f"{os.path.splitext(file_name)[0]}.log")

        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except:
                pass
        if os.path.exists(log_path):
            try:
                os.remove(log_path)
            except:
                pass

        remove_user_file_db(script_owner_id, file_name)
        try:
            bot.edit_message_text(
                f"🗑️ {file_name} deleted!",
                call.message.chat.id, call.message.message_id, reply_markup=None)
        except:
            pass
    except Exception as e:
        logger.error(f"Delete: {e}")
        bot.answer_callback_query(call.id, "Error", show_alert=True)


def logs_bot_callback(call):
    try:
        _, script_owner_id_str, file_name = call.data.split('_', 2)
        script_owner_id = int(script_owner_id_str)
        requesting_user_id = call.from_user.id

        if not (requesting_user_id == script_owner_id or requesting_user_id in admin_ids):
            bot.answer_callback_query(call.id, "⚠️ Permission denied.", show_alert=True)
            return

        user_folder = get_user_folder(script_owner_id)
        log_path = os.path.join(user_folder, f"{os.path.splitext(file_name)[0]}.log")

        if not os.path.exists(log_path):
            bot.answer_callback_query(call.id, "⚠️ No logs.", show_alert=True)
            return

        bot.answer_callback_query(call.id)
        try:
            log_content = ""
            file_size = os.path.getsize(log_path)
            max_log_kb = 100
            max_tg_msg = 4096

            if file_size == 0:
                log_content = "(Empty)"
            elif file_size > max_log_kb * 1024:
                with open(log_path, 'rb') as f:
                    f.seek(-max_log_kb * 1024, os.SEEK_END)
                    log_bytes = f.read()
                log_content = log_bytes.decode('utf-8', errors='ignore')
                log_content = f"(Last {max_log_kb} KB)\n...\n" + log_content
            else:
                with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
                    log_content = f.read()

            if len(log_content) > max_tg_msg:
                log_content = log_content[-max_tg_msg:]
                first_nl = log_content.find('\n')
                if first_nl != -1:
                    log_content = "...\n" + log_content[first_nl + 1:]

            if not log_content.strip():
                log_content = "(No content)"

            bot.send_message(
                call.message.chat.id,
                f"📜 Logs for `{file_name}`:\n```\n{log_content}\n```",
                parse_mode='Markdown')
        except Exception as e:
            logger.error(f"Log read: {e}")
            bot.send_message(call.message.chat.id, f"❌ Error reading log.")
    except Exception as e:
        logger.error(f"Logs: {e}")
        bot.answer_callback_query(call.id, "Error", show_alert=True)


def speed_callback(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    start_cb_ping_time = time.time()
    try:
        bot.edit_message_text("🏃 Testing...", chat_id, call.message.message_id)
        bot.send_chat_action(chat_id, 'typing')
        response_time = round((time.time() - start_cb_ping_time) * 1000, 2)
        status = "🔓 Unlocked" if not bot_locked else "🔒 Locked"

        if user_id == OWNER_ID:
            user_level = "👑 Owner"
        elif user_id in admin_ids:
            user_level = "🛡️ Admin"
        elif user_id in user_subscriptions and user_subscriptions[user_id].get('expiry', datetime.min) > datetime.now():
            user_level = "⭐ Premium"
        else:
            user_level = "🆓 Free User"

        speed_msg = (f"⚡ Speed:\n\n⏱️ Response: {response_time} ms\n"
                     f"🚦 Status: {status}\n"
                     f"👤 Level: {user_level}")
        bot.answer_callback_query(call.id)
        bot.edit_message_text(speed_msg, chat_id, call.message.message_id,
                              reply_markup=create_main_menu_inline(user_id))
    except Exception as e:
        logger.error(f"Speed: {e}")
        try:
            bot.answer_callback_query(call.id, "Error", show_alert=True)
        except:
            pass


def back_to_main_callback(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id

    fb_bal = fb_get_user_balance(user_id)
    file_limit = get_user_file_limit(user_id)
    current_files = get_user_file_count(user_id)
    limit_str = str(file_limit) if file_limit != float('inf') else "Unlimited"

    if user_id == OWNER_ID:
        user_status = "👑 Owner"
    elif user_id in admin_ids:
        user_status = "🛡️ Admin"
    elif user_id in user_subscriptions and user_subscriptions[user_id].get('expiry', datetime.min) > datetime.now():
        user_status = "⭐ Premium"
    else:
        user_status = "🆓 Free User"

    main_menu_text = (
        f"〽️ Welcome back, {call.from_user.first_name}!\n\n"
        f"🆔 ID: `{user_id}`\n"
        f"🔰 Status: {user_status}\n"
        f"💰 Balance: ৳{fb_bal['total']:.2f}\n"
        f"📁 Files: {current_files} / {limit_str}\n\n"
        f"👇 Use buttons or type commands."
    )
    try:
        bot.answer_callback_query(call.id)
        bot.edit_message_text(main_menu_text, chat_id, call.message.message_id,
                              reply_markup=create_main_menu_inline(user_id), parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Back main: {e}")


def subscription_management_callback(call):
    bot.answer_callback_query(call.id)
    try:
        bot.edit_message_text("💳 Subscription Management",
                              call.message.chat.id, call.message.message_id,
                              reply_markup=create_subscription_menu())
    except:
        pass


def stats_callback(call):
    bot.answer_callback_query(call.id)
    _logic_statistics(call.message)
    try:
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id,
                                       reply_markup=create_main_menu_inline(call.from_user.id))
    except:
        pass


def lock_bot_callback(call):
    global bot_locked
    bot_locked = True
    bot.answer_callback_query(call.id, "🔒 Locked.")
    try:
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id,
                                       reply_markup=create_main_menu_inline(call.from_user.id))
    except:
        pass


def unlock_bot_callback(call):
    global bot_locked
    bot_locked = False
    bot.answer_callback_query(call.id, "🔓 Unlocked.")
    try:
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id,
                                       reply_markup=create_main_menu_inline(call.from_user.id))
    except:
        pass


def run_all_scripts_callback(call):
    _logic_run_all_scripts(call)


def broadcast_init_callback(call):
    bot.answer_callback_query(call.id)
    msg = bot.send_message(call.message.chat.id, "📢 Send message.\n/cancel to abort.")
    bot.register_next_step_handler(msg, process_broadcast_message)


def process_broadcast_message(message):
    user_id = message.from_user.id
    if user_id not in admin_ids:
        bot.reply_to(message, "⚠️ Not authorized.")
        return
    if message.text and message.text.lower() == '/cancel':
        bot.reply_to(message, "Cancelled.")
        return

    broadcast_content = message.text
    if not broadcast_content and not (message.photo or message.video or message.document or message.sticker):
        bot.reply_to(message, "⚠️ Cannot broadcast empty.")
        msg = bot.send_message(message.chat.id, "📢 Send broadcast or /cancel.")
        bot.register_next_step_handler(msg, process_broadcast_message)
        return

    target_count = len(active_users)
    markup = types.InlineKeyboardMarkup()
    markup.row(
        types.InlineKeyboardButton("✅ Confirm", callback_data=f"confirm_broadcast_{message.message_id}"),
        types.InlineKeyboardButton("❌ Cancel", callback_data="cancel_broadcast")
    )

    preview_text = broadcast_content[:1000].strip() if broadcast_content else "(Media)"
    bot.reply_to(message,
                 f"⚠️ Confirm Broadcast:\n\n```\n{preview_text}\n```\nTo {target_count} users. Sure?",
                 reply_markup=markup, parse_mode='Markdown')


def handle_confirm_broadcast(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    if user_id not in admin_ids:
        bot.answer_callback_query(call.id, "⚠️ Admin only.", show_alert=True)
        return
    try:
        original_message = call.message.reply_to_message
        if not original_message:
            raise ValueError("No original message")

        broadcast_text = None
        broadcast_photo_id = None
        broadcast_video_id = None

        if original_message.text:
            broadcast_text = original_message.text
        elif original_message.photo:
            broadcast_photo_id = original_message.photo[-1].file_id
        elif original_message.video:
            broadcast_video_id = original_message.video.file_id
        else:
            raise ValueError("No supported media")

        bot.answer_callback_query(call.id, "Starting...")
        bot.edit_message_text(f"📢 Broadcasting to {len(active_users)} users...",
                              chat_id, call.message.message_id, reply_markup=None)
        thread = threading.Thread(target=execute_broadcast, args=(
            broadcast_text, broadcast_photo_id, broadcast_video_id,
            original_message.caption if (broadcast_photo_id or broadcast_video_id) else None,
            chat_id))
        thread.start()
    except Exception as e:
        logger.error(f"Confirm bcast: {e}")
        bot.edit_message_text(f"❌ Error: {e}", chat_id, call.message.message_id, reply_markup=None)


def handle_cancel_broadcast(call):
    bot.answer_callback_query(call.id, "Cancelled.")
    bot.delete_message(call.message.chat.id, call.message.message_id)
    if call.message.reply_to_message:
        try:
            bot.delete_message(call.message.chat.id, call.message.reply_to_message.message_id)
        except:
            pass


def execute_broadcast(broadcast_text, photo_id, video_id, caption, admin_chat_id):
    sent_count = 0
    failed_count = 0
    blocked_count = 0
    start_exec_time = time.time()
    users_to_broadcast = list(active_users)
    total_users = len(users_to_broadcast)
    batch_size = 25
    delay_batches = 1.5

    for i, user_id_bc in enumerate(users_to_broadcast):
        try:
            if broadcast_text:
                bot.send_message(user_id_bc, broadcast_text, parse_mode='Markdown')
            elif photo_id:
                bot.send_photo(user_id_bc, photo_id, caption=caption,
                               parse_mode='Markdown' if caption else None)
            elif video_id:
                bot.send_video(user_id_bc, video_id, caption=caption,
                               parse_mode='Markdown' if caption else None)
            sent_count += 1
        except telebot.apihelper.ApiTelegramException as e:
            err_desc = str(e).lower()
            if any(s in err_desc for s in ["blocked", "deactivated", "chat not found", "kicked"]):
                blocked_count += 1
            elif "flood control" in err_desc or "too many requests" in err_desc:
                retry_after = 5
                match = re.search(r"retry after (\d+)", err_desc)
                if match:
                    retry_after = int(match.group(1)) + 1
                time.sleep(retry_after)
                try:
                    if broadcast_text:
                        bot.send_message(user_id_bc, broadcast_text, parse_mode='Markdown')
                    elif photo_id:
                        bot.send_photo(user_id_bc, photo_id, caption=caption,
                                       parse_mode='Markdown' if caption else None)
                    elif video_id:
                        bot.send_video(user_id_bc, video_id, caption=caption,
                                       parse_mode='Markdown' if caption else None)
                    sent_count += 1
                except:
                    failed_count += 1
            else:
                failed_count += 1
        except:
            failed_count += 1

        if (i + 1) % batch_size == 0 and i < total_users - 1:
            time.sleep(delay_batches)
        elif i % 5 == 0:
            time.sleep(0.2)

    duration = round(time.time() - start_exec_time, 2)
    result_msg = (f"📢 Broadcast Done!\n\n"
                  f"✅ Sent: {sent_count}\n"
                  f"❌ Failed: {failed_count}\n"
                  f"🚫 Blocked: {blocked_count}\n"
                  f"👥 Targets: {total_users}\n"
                  f"⏱️ Duration: {duration}s")
    logger.info(result_msg)
    try:
        bot.send_message(admin_chat_id, result_msg)
    except:
        pass


def admin_panel_callback(call):
    bot.answer_callback_query(call.id)
    try:
        bot.edit_message_text("👑 Admin Panel", call.message.chat.id, call.message.message_id,
                              reply_markup=create_admin_panel())
    except:
        pass


def add_admin_init_callback(call):
    bot.answer_callback_query(call.id)
    msg = bot.send_message(call.message.chat.id, "👑 Enter User ID to promote.\n/cancel to abort.")
    bot.register_next_step_handler(msg, process_add_admin_id)


def process_add_admin_id(message):
    if message.from_user.id != OWNER_ID:
        bot.reply_to(message, "⚠️ Owner only.")
        return
    if message.text.lower() == '/cancel':
        bot.reply_to(message, "Cancelled.")
        return
    try:
        new_admin_id = int(message.text.strip())
        if new_admin_id <= 0:
            raise ValueError
        if new_admin_id == OWNER_ID:
            bot.reply_to(message, "⚠️ Owner is already Owner.")
            return
        if new_admin_id in admin_ids:
            bot.reply_to(message, f"⚠️ Already admin.")
            return
        add_admin_db(new_admin_id)
        bot.reply_to(message, f"✅ `{new_admin_id}` promoted.")
        try:
            bot.send_message(new_admin_id, "🎉 You are now Admin!")
        except:
            pass
    except ValueError:
        bot.reply_to(message, "⚠️ Invalid ID.")
        msg = bot.send_message(message.chat.id, "👑 Enter ID or /cancel.")
        bot.register_next_step_handler(msg, process_add_admin_id)


def remove_admin_init_callback(call):
    bot.answer_callback_query(call.id)
    msg = bot.send_message(call.message.chat.id, "👑 Enter Admin ID to remove.\n/cancel to abort.")
    bot.register_next_step_handler(msg, process_remove_admin_id)


def process_remove_admin_id(message):
    if message.from_user.id != OWNER_ID:
        bot.reply_to(message, "⚠️ Owner only.")
        return
    if message.text.lower() == '/cancel':
        bot.reply_to(message, "Cancelled.")
        return
    try:
        admin_id_remove = int(message.text.strip())
        if admin_id_remove <= 0:
            raise ValueError
        if admin_id_remove == OWNER_ID:
            bot.reply_to(message, "⚠️ Cannot remove Owner.")
            return
        if admin_id_remove not in admin_ids:
            bot.reply_to(message, f"⚠️ Not admin.")
            return
        if remove_admin_db(admin_id_remove):
            bot.reply_to(message, f"✅ Removed.")
            try:
                bot.send_message(admin_id_remove, "ℹ️ Removed from admins.")
            except:
                pass
        else:
            bot.reply_to(message, f"❌ Failed.")
    except ValueError:
        bot.reply_to(message, "⚠️ Invalid ID.")
        msg = bot.send_message(message.chat.id, "👑 Enter ID or /cancel.")
        bot.register_next_step_handler(msg, process_remove_admin_id)


def list_admins_callback(call):
    bot.answer_callback_query(call.id)
    try:
        admin_list_str = "\n".join(
            f"- `{aid}` {'(Owner)' if aid == OWNER_ID else ''}"
            for aid in sorted(list(admin_ids))
        )
        if not admin_list_str:
            admin_list_str = "(None)"
        bot.edit_message_text(f"👑 Admins:\n\n{admin_list_str}",
                              call.message.chat.id, call.message.message_id,
                              reply_markup=create_admin_panel(), parse_mode='Markdown')
    except:
        pass


def add_subscription_init_callback(call):
    bot.answer_callback_query(call.id)
    msg = bot.send_message(call.message.chat.id, "💳 Enter User ID & days (e.g., `12345 30`).\n/cancel to abort.")
    bot.register_next_step_handler(msg, process_add_subscription_details)


def process_add_subscription_details(message):
    if message.from_user.id not in admin_ids:
        bot.reply_to(message, "⚠️ Not authorized.")
        return
    if message.text.lower() == '/cancel':
        bot.reply_to(message, "Cancelled.")
        return
    try:
        parts = message.text.split()
        if len(parts) != 2:
            raise ValueError("Need 2 values")
        sub_user_id = int(parts[0].strip())
        days = int(parts[1].strip())
        if sub_user_id <= 0 or days <= 0:
            raise ValueError("Positive values only")

        current_expiry = user_subscriptions.get(sub_user_id, {}).get('expiry')
        start_date_new_sub = datetime.now()
        if current_expiry and current_expiry > start_date_new_sub:
            start_date_new_sub = current_expiry
        new_expiry = start_date_new_sub + timedelta(days=days)
        save_subscription(sub_user_id, new_expiry)

        bot.reply_to(message, f"✅ Sub for `{sub_user_id}` by {days} days.\nExpiry: {new_expiry:%Y-%m-%d}")
        try:
            bot.send_message(sub_user_id,
                f"🎉 Sub activated by {days} days! Expires: {new_expiry:%Y-%m-%d}.")
        except:
            pass
    except ValueError as e:
        bot.reply_to(message, f"⚠️ Invalid: {e}")
        msg = bot.send_message(message.chat.id, "💳 Enter ID & days, or /cancel.")
        bot.register_next_step_handler(msg, process_add_subscription_details)


def remove_subscription_init_callback(call):
    bot.answer_callback_query(call.id)
    msg = bot.send_message(call.message.chat.id, "💳 Enter User ID to remove.\n/cancel to abort.")
    bot.register_next_step_handler(msg, process_remove_subscription_id)


def process_remove_subscription_id(message):
    if message.from_user.id not in admin_ids:
        bot.reply_to(message, "⚠️ Not authorized.")
        return
    if message.text.lower() == '/cancel':
        bot.reply_to(message, "Cancelled.")
        return
    try:
        sub_user_id_remove = int(message.text.strip())
        if sub_user_id_remove <= 0:
            raise ValueError
        if sub_user_id_remove not in user_subscriptions:
            bot.reply_to(message, f"⚠️ No active sub.")
            return
        remove_subscription_db(sub_user_id_remove)
        bot.reply_to(message, f"✅ Removed.")
        try:
            bot.send_message(sub_user_id_remove, "ℹ️ Sub removed.")
        except:
            pass
    except ValueError:
        bot.reply_to(message, "⚠️ Invalid ID.")
        msg = bot.send_message(message.chat.id, "💳 Enter ID or /cancel.")
        bot.register_next_step_handler(msg, process_remove_subscription_id)


def check_subscription_init_callback(call):
    bot.answer_callback_query(call.id)
    msg = bot.send_message(call.message.chat.id, "💳 Enter User ID to check.\n/cancel to abort.")
    bot.register_next_step_handler(msg, process_check_subscription_id)


def process_check_subscription_id(message):
    if message.from_user.id not in admin_ids:
        bot.reply_to(message, "⚠️ Not authorized.")
        return
    if message.text.lower() == '/cancel':
        bot.reply_to(message, "Cancelled.")
        return
    try:
        sub_user_id_check = int(message.text.strip())
        if sub_user_id_check <= 0:
            raise ValueError
        if sub_user_id_check in user_subscriptions:
            expiry_dt = user_subscriptions[sub_user_id_check].get('expiry')
            if expiry_dt:
                if expiry_dt > datetime.now():
                    days_left = (expiry_dt - datetime.now()).days
                    bot.reply_to(message,
                        f"✅ Active sub.\nExpires: {expiry_dt:%Y-%m-%d %H:%M:%S} ({days_left} days)")
                else:
                    bot.reply_to(message,
                        f"⚠️ Expired sub ({expiry_dt:%Y-%m-%d}).")
                    remove_subscription_db(sub_user_id_check)
            else:
                bot.reply_to(message, f"⚠️ No expiry set.")
        else:
            bot.reply_to(message, f"ℹ️ No sub record.")
    except ValueError:
        bot.reply_to(message, "⚠️ Invalid ID.")
        msg = bot.send_message(message.chat.id, "💳 Enter ID or /cancel.")
        bot.register_next_step_handler(msg, process_check_subscription_id)


# ============================================================
# CLEANUP
# ============================================================
def cleanup():
    logger.warning("Shutdown. Cleaning up processes...")
    script_keys_to_stop = list(bot_scripts.keys())
    if not script_keys_to_stop:
        return
    for key in script_keys_to_stop:
        if key in bot_scripts:
            kill_process_tree(bot_scripts[key])


atexit.register(cleanup)


# ============================================================
# MAIN
# ============================================================
if __name__ == '__main__':
    logger.info("=" * 40)
    logger.info("🤖 Bot Starting...")
    logger.info(f"🐍 Python: {sys.version.split()[0]}")
    logger.info(f"🔑 Owner ID: {OWNER_ID}")
    logger.info(f"🛡️ Admins: {admin_ids}")
    logger.info("=" * 40)
    keep_alive()
    logger.info("🚀 Polling...")
    while True:
        try:
            bot.infinity_polling(logger_level=logging.INFO, timeout=60, long_polling_timeout=30)
        except requests.exceptions.ReadTimeout:
            logger.warning("ReadTimeout. Retry in 5s...")
            time.sleep(5)
        except requests.exceptions.ConnectionError as ce:
            logger.error(f"ConnectionError: {ce}. Retry in 15s...")
            time.sleep(15)
        except Exception as e:
            logger.critical(f"💥 Unrecoverable: {e}", exc_info=True)
            time.sleep(30)
        finally:
            logger.warning("Polling finished. Restarting...")
            time.sleep(1)
