from flask import Flask, render_template, request, jsonify, redirect, url_for, session
import secrets
import requests
from datetime import datetime
from functools import wraps
import json
import os

app = Flask(__name__)
app.secret_key = secrets.token_hex(32)

# ========== KONFIGURASI ==========
TELEGRAM_TOKEN = "8612708533:AAFGAqwjsqASljPT8-5ZXKYVcIwCK95w6W8"
TELEGRAM_CHAT_ID = "7297085736"
DANA_NUMBER = "6289654652309"

# ========== KONFIGURASI FONNTE ==========
FONNTE_TOKEN = "Ve55rMf3KPKLYQHY79E8"
FONNTE_API_URL = "https://api.fonnte.com/send"

# ========== KONFIGURASI QRIS (AZX GATEWAY) ==========
QRIS_API_KEY = "AZX_7741e02315c64118"
QRIS_BASE_URL = "https://azxgateway.my.id/api/v1/invoice"
QRIS_STATUS_URL = "https://azxgateway.my.id/api/v1/invoice/status"

# ========== FILE VOUCHER ==========
USED_VOUCHERS_FILE = 'used_vouchers.json'

def load_used_vouchers():
    if os.path.exists(USED_VOUCHERS_FILE):
        with open(USED_VOUCHERS_FILE, 'r') as f:
            try:
                return json.load(f)
            except:
                return {}
    return {}

def save_used_vouchers(data):
    with open(USED_VOUCHERS_FILE, 'w') as f:
        json.dump(data, f)

def is_voucher_used(phone, voucher_code):
    data = load_used_vouchers()
    key = f"{phone}_{voucher_code}"
    return data.get(key, False)

def mark_voucher_used(phone, voucher_code):
    data = load_used_vouchers()
    key = f"{phone}_{voucher_code}"
    data[key] = True
    save_used_vouchers(data)

# ========== KIRIM WA KE CUSTOMER ==========
def kirim_wa_ke_customer(nomor, pesan):
    try:
        if nomor.startswith('0'):
            nomor = '62' + nomor[1:]
        elif nomor.startswith('+'):
            nomor = nomor[1:]
        nomor = nomor.replace(' ', '').replace('-', '').replace('(', '').replace(')', '')
        headers = {"Authorization": FONNTE_TOKEN}
        data = {"target": nomor, "message": pesan, "countryCode": "62"}
        response = requests.post(FONNTE_API_URL, headers=headers, data=data, timeout=30)
        if response.status_code == 200:
            result = response.json()
            if result.get('status'):
                return True
        return False
    except Exception as e:
        print(f"[WA] Error: {e}")
        return False

# ========== KIRIM TELEGRAM KE OWNER ==========
def kirim_ke_telegram(pesan):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        data = {"chat_id": TELEGRAM_CHAT_ID, "text": pesan, "parse_mode": "HTML"}
        requests.post(url, json=data, timeout=10)
    except Exception as e:
        print(f"[Telegram] Error: {e}")

# ========== QRIS PAYMENT (AZX GATEWAY) ==========
def create_qris_invoice(amount, order_id, customer_name):
    """Buat invoice QRIS via AZX Gateway"""
    try:
        amount_int = int(amount)
        params = {
            "apikey": QRIS_API_KEY,
            "amount": amount_int
        }

        print(f"[QRIS] Membuat invoice untuk Rp {amount_int}")

        response = requests.get(QRIS_BASE_URL, params=params, timeout=30)

        print(f"[QRIS] Status: {response.status_code}")
        print(f"[QRIS] Response: {response.text}")

        if response.status_code == 200:
            result = response.json()
            if result.get('success') and result.get('qris_image'):
                return {
                    'success': True,
                    'qris_image': result.get('qris_image'),
                    'invoice_id': result.get('invoice_id'),
                    'amount': result.get('amount'),
                    'total': result.get('total'),
                    'expired_at': result.get('expired_at')
                }
            else:
                return {'success': False, 'message': result.get('message', 'Gagal buat invoice')}
        else:
            return {'success': False, 'message': f'HTTP {response.status_code}'}
    except Exception as e:
        print(f"[QRIS] Error: {e}")
        return {'success': False, 'message': str(e)}

def check_qris_status(invoice_id):
    """Cek status pembayaran invoice"""
    try:
        params = {
            "apikey": QRIS_API_KEY,
            "invoice_id": invoice_id
        }
        response = requests.get(QRIS_STATUS_URL, params=params, timeout=30)
        if response.status_code == 200:
            result = response.json()
            return {'status': result.get('status', 'unknown')}
        return {'status': 'error'}
    except Exception as e:
        print(f"[QRIS] Status Error: {e}")
        return {'status': 'error'}

@app.route('/api/create-qris', methods=['POST'])
def create_qris():
    try:
        data = request.json
        order_id = data.get('order_id')
        amount = data.get('amount')
        customer_name = data.get('customer_name')

        result = create_qris_invoice(amount, order_id, customer_name)

        if result.get('success'):
            if hasattr(app, 'orders'):
                for order in app.orders:
                    if order['order_id'] == order_id:
                        order['invoice_id'] = result.get('invoice_id')
                        break
            return jsonify({
                'success': True,
                'qris_image': result.get('qris_image'),
                'invoice_id': result.get('invoice_id'),
                'amount': result.get('amount'),
                'total': result.get('total'),
                'expired_at': result.get('expired_at')
            })
        else:
            return jsonify({'success': False, 'message': result.get('message')})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/api/check-qris-status', methods=['POST'])
def check_qris_status_route():
    try:
        data = request.json
        invoice_id = data.get('invoice_id')
        order_id = data.get('order_id')

        result = check_qris_status(invoice_id)

        if result.get('status') == 'paid':
            if hasattr(app, 'orders'):
                for order in app.orders:
                    if order['order_id'] == order_id:
                        order['status'] = 'completed'
                        break
            return jsonify({'status': 'completed'})
        elif result.get('status') == 'expired':
            return jsonify({'status': 'expired'})
        else:
            return jsonify({'status': 'pending'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

# ========== VOUCHER ==========
VOUCHERS = {
    'JUANVARIASI': {'type': 'percent', 'value': 20, 'name': 'Diskon 20%', 'once_per_phone': True},
    'MEMEK': {'type': 'percent', 'value': 10, 'name': 'Diskon 10%', 'once_per_phone': True},
    'AHAH': {'type': 'nominal', 'value': 5000, 'name': 'Potong Rp5.000', 'once_per_phone': True},
    'CEPAK': {'type': 'percent', 'value': 50, 'name': 'Diskon 50%', 'once_per_phone': False},
}

def hitung_diskon(harga, voucher_code):
    if not voucher_code or voucher_code not in VOUCHERS:
        return harga
    v = VOUCHERS[voucher_code]
    if v['type'] == 'percent':
        return int(harga - (harga * v['value'] / 100))
    else:
        return max(0, int(harga - v['value']))

def bulatkan_harga_cash(harga):
    if harga <= 1000:
        return 2000
    return ((harga + 999) // 1000) * 1000

# ========== PRODUK ==========
PRODUCTS = {
    'ff_5': {'name': '5 Diamonds', 'game': 'FF', 'price': 1000},
    'ff_10': {'name': '10 Diamonds', 'game': 'FF', 'price': 1900},
    'ff_20': {'name': '20 Diamonds', 'game': 'FF', 'price': 3800},
    'ff_50': {'name': '50 Diamonds', 'game': 'FF', 'price': 8000},
    'ff_70': {'name': '70 Diamonds', 'game': 'FF', 'price': 9800},
    'ff_90': {'name': '90 Diamonds', 'game': 'FF', 'price': 12800},
    'ff_100': {'name': '100 Diamonds', 'game': 'FF', 'price': 16500},
    'ff_125': {'name': '125 Diamonds', 'game': 'FF', 'price': 16800},
    'ff_130': {'name': '130 Diamonds', 'game': 'FF', 'price': 17500},
    'ff_140': {'name': '140 Diamonds', 'game': 'FF', 'price': 18800},
    'ff_145': {'name': '145 Diamonds', 'game': 'FF', 'price': 19500},
    'ff_200': {'name': '200 Diamonds', 'game': 'FF', 'price': 26500},
    'ff_300': {'name': '300 Diamonds', 'game': 'FF', 'price': 39600},
}

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'logged_in' not in session:
            return redirect(url_for('login_owner'))
        return f(*args, **kwargs)
    return decorated_function

# ========== ROUTES ==========
@app.route('/')
def index():
    return render_template('juanshop.html', products=PRODUCTS, dana_number=DANA_NUMBER, vouchers=VOUCHERS)

@app.route('/api/create-order', methods=['POST'])
def create_order():
    try:
        data = request.json
        order_id = secrets.token_hex(4).upper()
        product = PRODUCTS.get(data.get('product_code'))
        customer_phone = data.get('customer_phone')
        customer_name = data.get('customer_name') or 'Customer'
        metode = data.get('metode', 'dana')
        voucher_code = data.get('voucher')

        if not product:
            return jsonify({'success': False, 'message': 'Produk tidak ditemukan'}), 400

        if voucher_code and voucher_code in VOUCHERS and VOUCHERS[voucher_code].get('once_per_phone', True):
            if is_voucher_used(customer_phone, voucher_code):
                return jsonify({'success': False, 'message': f'Voucher {voucher_code} sudah pernah digunakan!'}), 400

        harga_dasar = product['price']
        if voucher_code and voucher_code in VOUCHERS:
            harga_setelah_voucher = hitung_diskon(harga_dasar, voucher_code)
        else:
            harga_setelah_voucher = harga_dasar
        if metode == 'cash':
            harga_bayar = bulatkan_harga_cash(harga_setelah_voucher)
        else:
            harga_bayar = harga_setelah_voucher

        metode_text = "DANA" if metode == 'dana' else ("CASH" if metode == 'cash' else "QRIS")

        if metode == 'dana':
            wa_pesan = f"""*JUANSHOP - Order Diterima*

Halo {customer_name},

✅ Order Anda sudah kami terima!

🆔 *ORDER ID:* {order_id}
💎 *Produk:* {product['name']}
💰 *Harga:* Rp {int(harga_bayar):,}
💳 *Metode:* DANA

*CARA BAYAR DANA:*
📲 Transfer ke DANA: {DANA_NUMBER}
📝 Catatan: ORDER {order_id}

Terima kasih!
JUANSHOP"""
        elif metode == 'qris':
            wa_pesan = f"""*JUANSHOP - Order Diterima*

Halo {customer_name},

✅ Order Anda sudah kami terima!

🆔 *ORDER ID:* {order_id}
💎 *Produk:* {product['name']}
💰 *Harga:* Rp {int(harga_bayar):,}
💳 *Metode:* QRIS

*CARA BAYAR QRIS:*
Scan QR Code yang muncul di website

Terima kasih!
JUANSHOP"""
        else:
            wa_pesan = f"""*JUANSHOP - Order Diterima*

Halo {customer_name},

✅ Order Anda sudah kami terima!

🆔 *ORDER ID:* {order_id}
💎 *Produk:* {product['name']}
💰 *Harga:* Rp {int(harga_bayar):,}
💳 *Metode:* CASH

*CARA BAYAR CASH:*
Chat JUAN: {DANA_NUMBER}

Terima kasih!
JUANSHOP"""

        wa_terkirim = kirim_wa_ke_customer(customer_phone, wa_pesan)

        diskon_info = ""
        if voucher_code and voucher_code in VOUCHERS:
            v = VOUCHERS[voucher_code]
            hemat = harga_dasar - harga_bayar
            if v['type'] == 'percent':
                diskon_info = f"\n🎟️ Voucher {voucher_code}: Diskon {v['value']}% (hemat Rp{int(hemat):,})"
            else:
                diskon_info = f"\n🎟️ Voucher {voucher_code}: Potong Rp{v['value']:,}"

        pesan_telegram = f"""
🛒 ORDER BARU!

🆔 ORDER ID: {order_id}
🎮 Game: Free Fire
👤 Nama: {customer_name}
📱 WA: {customer_phone}
🎮 User ID: {data.get('customer_id')}
💎 Produk: {product['name']}
💰 Harga Asli: Rp {int(harga_dasar):,}
💰 Harga Bayar: Rp {int(harga_bayar):,}{diskon_info}
📌 Metode: {metode.upper()}
📨 WA Customer: {'✅' if wa_terkirim else '❌'}
        """
        kirim_ke_telegram(pesan_telegram)

        if not hasattr(app, 'orders'):
            app.orders = []
        app.orders.append({
            'order_id': order_id,
            'customer_name': customer_name,
            'customer_phone': customer_phone,
            'customer_id': data.get('customer_id'),
            'product_name': product['name'],
            'price': harga_bayar,
            'original_price': harga_dasar,
            'metode': metode,
            'voucher': voucher_code,
            'status': 'pending',
            'created_at': datetime.now().isoformat(),
            'wa_sent': wa_terkirim
        })

        if voucher_code and voucher_code in VOUCHERS and VOUCHERS[voucher_code].get('once_per_phone', True):
            mark_voucher_used(customer_phone, voucher_code)

        return jsonify({
            'success': True,
            'order_id': order_id,
            'product_name': product['name'],
            'price': harga_bayar,
            'original_price': harga_dasar,
            'dana_number': DANA_NUMBER,
            'customer_id': data.get('customer_id'),
            'wa_sent': wa_terkirim,
            'metode': metode
        })
    except Exception as e:
        print(f"ERROR: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/check-login', methods=['GET'])
def check_login():
    if 'logged_in' in session:
        return jsonify({'logged_in': True, 'username': session.get('username')})
    return jsonify({'logged_in': False})

@app.route('/login', methods=['GET', 'POST'])
def login_owner():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        if username == 'admin' and password == 'juanshop123':
            session['logged_in'] = True
            session['username'] = username
            return redirect(url_for('admin_dashboard'))
        else:
            return render_template('login.html', error='Username atau password salah!')
    return render_template('login.html', error=None)

@app.route('/logout')
def logout_owner():
    session.clear()
    return redirect(url_for('index'))

@app.route('/admin')
@login_required
def admin_dashboard():
    orders = getattr(app, 'orders', [])
    return render_template('admin_dashboard.html', username=session.get('username'), orders=orders)

@app.route('/api/admin/get-orders', methods=['GET'])
@login_required
def get_orders():
    orders = getattr(app, 'orders', [])
    return jsonify({'success': True, 'orders': orders})

@app.route('/api/admin/delete-order', methods=['POST'])
@login_required
def delete_order():
    data = request.json
    order_id = data.get('order_id')
    app.orders = [o for o in app.orders if o['order_id'] != order_id]
    return jsonify({'success': True})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)