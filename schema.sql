DROP TABLE IF EXISTS items;

CREATE TABLE items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    weight INTEGER NOT NULL,
    volume INTEGER NOT NULL,
    amount INTEGER NOT NULL,
    price REAL NOT NULL,
    image_url TEXT NULL,
    name TEXT NOT NULL,
    street_address TEXT NOT NULL,
    coordinates TEXT NOT NULL
);

DROP TABLE IF EXISTS bookings;

CREATE TABLE bookings (
    booking_id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id INTEGER NOT NULL,
    amount INTEGER NOT NULL,
    confirmed INTEGER NOT NULL
);
