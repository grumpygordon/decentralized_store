import asyncio
import sqlite3
from flask import Flask, request, abort, jsonify
from threading import Thread
import datetime
import re
from argparse import ArgumentParser

app = Flask(__name__)

# Сервер на Flask с использованием дополнительного треда для отложенных операций отмены бронирования (asyncio, Thread)

# Имеется 2 таблицы в формате SQLite: items (хранит предметы на складе), bookings (хранит бронирования)
# Схема таблиц описана в schema.sql

# Концепция работы следующая:

# Клиент отправляет запрос /items_by_string?query=S
# Из items возвращаются все элементы с названием, содержащим S как подстроку

# Клиент отправляет запрос бронирования /booking конкретного предмета id в количестве quantity
# Если такое количество доступно для бронирования, то возвращается уникальный номер бронирования,
# а это количество бронируется для покупателя

# В течение суток клиент должен подтвердить бронирование /confirm_booking (если он нашел доставщика),
# либо отменить его /cancel_booking.
# Если клиент не подтвердит бронирование в течение суток,
# то происходит автоматическая отмена бронирования (для этого используется отдельный поток).

# При отмене бронирования забронированное количество снова становится доступно для бронирования, бронирование удаляется.
# При подтверждении бронирования ставится соответствующий флаг в таблице bookings,
# при фактическом получении груза ответственный работник на складе должен это бронирование пометить как выполненное.

# Операции к БД выполняются атомарно, если это возможно.


# получить доступ
def get_db_connection():
    conn = sqlite3.connect('store.db', check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


# операция отмены бронирования в БД
def cancel_booking(booking_id):
    con = get_db_connection()
    # increase amount back to what it was before (if booking still exists)
    con.execute('''
    UPDATE items
     SET amount = amount +
     (SELECT amount FROM bookings b WHERE b.booking_id = ? AND items.id = b.item_id AND b.confirmed = 0)
     WHERE id IN (SELECT item_id FROM bookings b WHERE b.booking_id = ? AND b.confirmed = 0)
     ''', (booking_id, booking_id))
    # delete booking
    con.execute('DELETE FROM bookings WHERE booking_id = ? AND confirmed = 0', (booking_id, ))
    con.commit()
    w = con.total_changes
    con.close()
    if w > 0:
        print('canceled booking', booking_id)
    return w


# отложенная операция отмены бронирования
async def check_booking(booking_id):
    # change to 60 * 60 * 24 for 1 day delay
    await asyncio.sleep(600)
    w = cancel_booking(booking_id)
    return w


# получить предметы с подходящим названием
@app.route('/items_by_string', methods=['GET'])
def get_everything():
    substring = None
    try:
        substring = str(request.args.get('query', ''))
    except:
        pass
    if substring is None:
        substring = ''
    # оставляем только буквы и цифры для защиты от SQL инъекций
    substring = re.sub('[^a-zA-Z А-Яа-я0-9]+', '', substring)
    con = get_db_connection()
    res = con.execute("SELECT * FROM items WHERE name LIKE '%' || ? || '%'", (substring, )).fetchall()
    if res is None:
        return jsonify([])
    con.close()
    return jsonify([{x: str(w[x]) if x == 'id' else w[x] for x in w.keys()} for w in res])


# создать бронирование
@app.route('/booking', methods=['POST'])
def make_booking():
    item_id = 0
    quantity = 0
    q = request.json
    try:
        item_id = int(q.get('item_id'))
        quantity = int(q.get('quantity'))
    except:
        abort(400, "item_id or quantity not provided")
    con = get_db_connection()
    cursor = con.cursor()
    res = cursor.execute('SELECT * FROM items WHERE id = ?', (item_id, )).fetchone()
    if res is None:
        abort(400, "no such item")
    if res['amount'] < quantity:
        abort(400, "not enough amount")
    cursor.execute('UPDATE items SET amount = amount - ? WHERE id = ?', (quantity, item_id))
    cursor.execute('INSERT INTO bookings (item_id, amount, confirmed) VALUES (?, ?, 0)', (item_id, quantity))
    con.commit()
    booking_id = cursor.lastrowid
    asyncio.run_coroutine_threadsafe(check_booking(booking_id), loop)
    date = (datetime.datetime.now() + datetime.timedelta(days=2)).strftime('%Y-%m-%d')
    con.close()
    return {'id': str(booking_id), 'address': res['coordinates'], 'available_date': date}


# отменить бронирование
@app.route('/cancel_booking', methods=['POST'])
def cancel():
    booking_id = -1
    q = request.json
    try:
        booking_id = int(q.get('booking_id'))
    except:
        abort(400, "booking_id not provided")
    w = cancel_booking(booking_id)
    if w > 0:
        return {}
    else:
        abort(400, "This booking cannot be canceled")


# подтвердить бронирование
@app.route('/confirm_booking', methods=['POST'])
def confirm_booking():
    booking_id = -1
    q = request.json
    try:
        booking_id = int(q.get('booking_id'))
    except:
        abort(400, "booking_id not provided")
    con = get_db_connection()
    con.execute('UPDATE bookings SET confirmed = 1 WHERE booking_id = ? AND confirmed = 0', (booking_id,))
    con.commit()
    w = con.total_changes
    con.close()
    if w > 0:
        return {}
    else:
        abort(400, "This booking cannot be confirmed")


# запустить тред
def start_background_loop(loop):
    asyncio.set_event_loop(loop)
    loop.run_forever()


if __name__ == '__main__':
    parser = ArgumentParser()
    parser.add_argument('-init', help='initialize database', action='store_true')
    args = parser.parse_args()
    if args.init:
        # создать тестовую БД
        print('initializing database from schema.sql')
        con = get_db_connection()
        with open('schema.sql') as f:
            con.executescript(f.read())
        cur = con.cursor()
        cur.execute("INSERT INTO items (weight, volume, amount, price, image_url, name, street_address, coordinates) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (5, 7, 1000, 12, 'https://a.d-cd.net/9b4IHEwEtY01H94Gfk1mXPpkNF8-480.jpg', 'biba', 'Мясницкая 21', '123.52;74.81')
                    )
        cur.execute("INSERT INTO items (weight, volume, amount, price, image_url, name, street_address, coordinates) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (5, 7, 1000, 13, 'https://i.ytimg.com/vi/9cRuLmNlOwU/maxresdefault.jpg', 'boba', 'Покровский бульвар 17', '65.23;81.64')
                    )
        con.commit()
        con.close()

    # создать и запустить тред
    loop = asyncio.new_event_loop()
    t = Thread(target=start_background_loop, args=(loop,), daemon=True)
    t.start()

    # запустить сервер
    app.run()
