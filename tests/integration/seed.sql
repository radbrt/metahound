CREATE TABLE orders (
    id integer PRIMARY KEY,
    customer text,
    status text,
    total numeric
);

CREATE TABLE customers (
    id integer PRIMARY KEY,
    email text
);

INSERT INTO orders (id, customer, status, total)
SELECT i, 'cust_' || (i % 5), CASE WHEN i % 3 = 0 THEN 'open' ELSE 'shipped' END, i * 9.5
FROM generate_series(1, 50) AS i;

INSERT INTO customers (id, email)
SELECT i, 'user' || i || '@example.com' FROM generate_series(1, 10) AS i;
