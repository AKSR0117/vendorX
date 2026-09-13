from flask import Flask, render_template, request, Response
import sqlite3
import csv
import io

app = Flask(__name__)

DATABASE = r"C:\sqlite\smart_inventory.db"


# =========================
# DATABASE CONNECTION
# =========================

def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# =========================
# INITIALIZE DATABASE
# =========================

def init_db():

    conn = get_db()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS inventory_history (
            history_id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            action TEXT NOT NULL,
            quantity REAL NOT NULL,
            stock_after REAL NOT NULL,
            reason TEXT,
            history_date DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (product_id) REFERENCES products(id)
        )
    """)

    # Older databases may not have reason column
    try:
        conn.execute("""
            ALTER TABLE inventory_history
            ADD COLUMN reason TEXT
        """)
    except sqlite3.OperationalError:
        pass

    # Older databases may not have low_stock_level
    try:
        conn.execute("""
            ALTER TABLE products
            ADD COLUMN low_stock_level REAL DEFAULT 5
        """)
    except sqlite3.OperationalError:
        pass

    conn.commit()
    conn.close()


# =========================
# HOME
# =========================

@app.route("/")
def home():
    return render_template("index.html")


# =========================
# ADD PRODUCT
# =========================

@app.route("/add-product", methods=["POST"])
def add_product():

    data = request.get_json(silent=True) or {}

    barcode = str(data.get("barcode", "")).strip()
    name = str(data.get("name", "")).strip()
    category = str(data.get("category", "")).strip()
    unit = str(data.get("unit", "")).strip()

    if barcode == "":
        return {"error": "Barcode is required"}, 400

    if name == "":
        return {"error": "Product name is required"}, 400

    if unit == "":
        return {"error": "Unit is required"}, 400

    try:
        price = float(data.get("price", 0))
        quantity = float(data.get("quantity", 0))
        low_stock_level = float(
            data.get("low_stock_level", 5)
        )
    except (TypeError, ValueError):

        return {
            "error": "Price, quantity and low stock level must be numbers"
        }, 400

    if price < 0:
        return {"error": "Price cannot be negative"}, 400

    if quantity < 0:
        return {"error": "Quantity cannot be negative"}, 400

    if low_stock_level < 0:
        return {
            "error": "Low stock level cannot be negative"
        }, 400

    conn = get_db()

    try:

        cursor = conn.execute("""
            INSERT INTO products
            (
                barcode,
                name,
                category,
                price,
                quantity,
                unit,
                low_stock_level
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            barcode,
            name,
            category,
            price,
            quantity,
            unit,
            low_stock_level
        ))

        product_id = cursor.lastrowid

        if quantity > 0:

            conn.execute("""
                INSERT INTO inventory_history
                (
                    product_id,
                    action,
                    quantity,
                    stock_after,
                    reason
                )
                VALUES (?, 'ADD', ?, ?, ?)
            """, (
                product_id,
                quantity,
                quantity,
                "Initial stock"
            ))

        conn.commit()

        return {
            "message": "Product added successfully"
        }

    except sqlite3.IntegrityError:

        conn.rollback()

        return {
            "error": "Barcode already exists"
        }, 400

    finally:
        conn.close()


# =========================
# ALL PRODUCTS
# =========================

@app.route("/products")
def products():

    conn = get_db()

    data = conn.execute("""
        SELECT *
        FROM products
        ORDER BY id DESC
    """).fetchall()

    conn.close()

    return [dict(row) for row in data]


# =========================
# BARCODE LOOKUP
# =========================

@app.route("/product/<barcode>")
def get_product(barcode):

    conn = get_db()

    product = conn.execute("""
        SELECT *
        FROM products
        WHERE barcode = ?
    """, (barcode,)).fetchone()

    conn.close()

    if product is None:

        return {
            "error": "Product not found"
        }, 404

    return dict(product)


# =========================
# EDIT PRODUCT
# =========================

@app.route("/edit-product/<int:id>", methods=["PUT"])
def edit_product(id):

    data = request.get_json(silent=True) or {}

    barcode = str(data.get("barcode", "")).strip()
    name = str(data.get("name", "")).strip()
    category = str(data.get("category", "")).strip()
    unit = str(data.get("unit", "")).strip()

    if barcode == "":
        return {"error": "Barcode is required"}, 400

    if name == "":
        return {"error": "Product name is required"}, 400

    if unit == "":
        return {"error": "Unit is required"}, 400

    try:

        price = float(data.get("price", 0))

        low_stock_level = float(
            data.get("low_stock_level", 5)
        )

    except (TypeError, ValueError):

        return {
            "error": "Price and low stock level must be numbers"
        }, 400

    if price < 0:
        return {
            "error": "Price cannot be negative"
        }, 400

    if low_stock_level < 0:
        return {
            "error": "Low stock level cannot be negative"
        }, 400

    conn = get_db()

    product = conn.execute("""
        SELECT *
        FROM products
        WHERE id = ?
    """, (id,)).fetchone()

    if product is None:

        conn.close()

        return {
            "error": "Product not found"
        }, 404

    duplicate = conn.execute("""
        SELECT id
        FROM products
        WHERE barcode = ?
        AND id != ?
    """, (barcode, id)).fetchone()

    if duplicate:

        conn.close()

        return {
            "error": "Another product already uses this barcode"
        }, 400

    conn.execute("""
        UPDATE products
        SET
            barcode = ?,
            name = ?,
            category = ?,
            price = ?,
            unit = ?,
            low_stock_level = ?
        WHERE id = ?
    """, (
        barcode,
        name,
        category,
        price,
        unit,
        low_stock_level,
        id
    ))

    conn.commit()
    conn.close()

    return {
        "message": "Product updated successfully"
    }


# =========================
# SELL
# =========================

@app.route("/sell", methods=["POST"])
def sell_product():

    data = request.get_json(silent=True) or {}

    barcode = str(data.get("barcode", "")).strip()

    try:
        quantity = float(data.get("quantity", 0))
    except (TypeError, ValueError):

        return {
            "error": "Invalid quantity"
        }, 400

    if barcode == "":
        return {
            "error": "Barcode is required"
        }, 400

    if quantity <= 0:
        return {
            "error": "Quantity must be greater than 0"
        }, 400

    conn = get_db()

    product = conn.execute("""
        SELECT *
        FROM products
        WHERE barcode = ?
    """, (barcode,)).fetchone()

    if product is None:

        conn.close()

        return {
            "error": "Product not found"
        }, 404

    if product["quantity"] < quantity:

        conn.close()

        return {
            "error": "Not enough stock"
        }, 400

    total = product["price"] * quantity

    remaining_stock = (
        product["quantity"] - quantity
    )

    try:

        conn.execute("""
            UPDATE products
            SET quantity = quantity - ?
            WHERE barcode = ?
        """, (quantity, barcode))

        conn.execute("""
            INSERT INTO sales
            (
                product_id,
                quantity_sold,
                total_amount
            )
            VALUES (?, ?, ?)
        """, (
            product["id"],
            quantity,
            total
        ))

        conn.execute("""
            INSERT INTO inventory_history
            (
                product_id,
                action,
                quantity,
                stock_after,
                reason
            )
            VALUES (?, 'SALE', ?, ?, ?)
        """, (
            product["id"],
            -quantity,
            remaining_stock,
            "Product sold"
        ))

        conn.commit()

    except Exception as e:

        conn.rollback()
        conn.close()

        return {
            "error": str(e)
        }, 500

    conn.close()

    return {
        "message": "Product sold successfully",
        "product": product["name"],
        "quantity_sold": quantity,
        "total_amount": total,
        "remaining_stock": remaining_stock
    }


# =========================
# RESTOCK
# =========================

@app.route("/restock", methods=["POST"])
def restock_product():

    data = request.get_json(silent=True) or {}

    barcode = str(data.get("barcode", "")).strip()

    try:
        quantity = float(data.get("quantity", 0))
    except (TypeError, ValueError):

        return {
            "error": "Invalid quantity"
        }, 400

    if barcode == "":
        return {
            "error": "Barcode is required"
        }, 400

    if quantity <= 0:
        return {
            "error": "Quantity must be greater than 0"
        }, 400

    conn = get_db()

    product = conn.execute("""
        SELECT *
        FROM products
        WHERE barcode = ?
    """, (barcode,)).fetchone()

    if product is None:

        conn.close()

        return {
            "error": "Product not found"
        }, 404

    new_quantity = (
        product["quantity"] + quantity
    )

    try:

        conn.execute("""
            UPDATE products
            SET quantity = quantity + ?
            WHERE barcode = ?
        """, (quantity, barcode))

        conn.execute("""
            INSERT INTO inventory_history
            (
                product_id,
                action,
                quantity,
                stock_after,
                reason
            )
            VALUES (?, 'RESTOCK', ?, ?, ?)
        """, (
            product["id"],
            quantity,
            new_quantity,
            "Stock restocked"
        ))

        conn.commit()

    except Exception as e:

        conn.rollback()
        conn.close()

        return {
            "error": str(e)
        }, 500

    conn.close()

    return {
        "message": "Product restocked successfully",
        "product": product["name"],
        "quantity_added": quantity,
        "new_quantity": new_quantity
    }


# =========================
# STOCK ADJUSTMENT
# =========================

@app.route("/adjust-stock", methods=["POST"])
def adjust_stock():

    data = request.get_json(silent=True) or {}

    barcode = str(data.get("barcode", "")).strip()
    reason = str(data.get("reason", "")).strip()

    try:
        quantity = float(data.get("quantity", 0))
    except (TypeError, ValueError):

        return {
            "error": "Invalid quantity"
        }, 400

    if barcode == "":
        return {
            "error": "Barcode is required"
        }, 400

    if quantity == 0:
        return {
            "error": "Quantity cannot be zero"
        }, 400

    conn = get_db()

    product = conn.execute("""
        SELECT *
        FROM products
        WHERE barcode = ?
    """, (barcode,)).fetchone()

    if product is None:

        conn.close()

        return {
            "error": "Product not found"
        }, 404

    new_stock = product["quantity"] + quantity

    if new_stock < 0:

        conn.close()

        return {
            "error": "Stock cannot become negative"
        }, 400

    try:

        conn.execute("""
            UPDATE products
            SET quantity = ?
            WHERE barcode = ?
        """, (
            new_stock,
            barcode
        ))

        conn.execute("""
            INSERT INTO inventory_history
            (
                product_id,
                action,
                quantity,
                stock_after,
                reason
            )
            VALUES (?, 'ADJUST', ?, ?, ?)
        """, (
            product["id"],
            quantity,
            new_stock,
            reason
        ))

        conn.commit()

    except Exception as e:

        conn.rollback()
        conn.close()

        return {
            "error": str(e)
        }, 500

    conn.close()

    return {
        "message": "Stock adjusted successfully",
        "product": product["name"],
        "change": quantity,
        "new_stock": new_stock
    }


# =========================
# SALES HISTORY
# =========================

@app.route("/sales")
def sales():

    conn = get_db()

    data = conn.execute("""
        SELECT
            sales.sale_id,
            products.name,
            products.barcode,
            products.unit,
            sales.quantity_sold,
            sales.total_amount,
            sales.sale_date
        FROM sales
        JOIN products
        ON sales.product_id = products.id
        ORDER BY sales.sale_id DESC
    """).fetchall()

    conn.close()

    return [dict(row) for row in data]


# =========================
# INVENTORY HISTORY
# =========================

@app.route("/inventory-history")
def inventory_history():

    conn = get_db()

    data = conn.execute("""
        SELECT
            inventory_history.history_id,
            products.name,
            products.barcode,
            inventory_history.action,
            inventory_history.quantity,
            products.unit,
            inventory_history.stock_after,
            inventory_history.reason,
            inventory_history.history_date
        FROM inventory_history
        JOIN products
        ON inventory_history.product_id = products.id
        ORDER BY inventory_history.history_id DESC
    """).fetchall()

    conn.close()

    return [dict(row) for row in data]


# =========================
# LOW STOCK
# =========================

@app.route("/low-stock")
def low_stock():

    conn = get_db()

    data = conn.execute("""
        SELECT
            id,
            barcode,
            name,
            category,
            price,
            quantity,
            unit,
            low_stock_level
        FROM products
        WHERE quantity <= low_stock_level
        ORDER BY quantity ASC
    """).fetchall()

    conn.close()

    return [dict(row) for row in data]


# =========================
# DASHBOARD
# =========================

@app.route("/dashboard")
def dashboard():

    conn = get_db()

    product_data = conn.execute("""
        SELECT
            COUNT(*) AS total_products,
            COALESCE(SUM(quantity), 0) AS total_stock,
            COALESCE(
                SUM(
                    CASE
                        WHEN quantity <= low_stock_level
                        THEN 1
                        ELSE 0
                    END
                ),
                0
            ) AS low_stock
        FROM products
    """).fetchone()

    sales_data = conn.execute("""
        SELECT
            COALESCE(SUM(total_amount), 0)
            AS total_sales
        FROM sales
    """).fetchone()

    conn.close()

    return {
        "total_products":
            product_data["total_products"],

        "total_stock":
            product_data["total_stock"],

        "low_stock":
            product_data["low_stock"],

        "total_sales":
            sales_data["total_sales"]
    }


# =========================
# SALES REPORT
# =========================

@app.route("/sales-report")
def sales_report():

    conn = get_db()

    summary = conn.execute("""
        SELECT
            COUNT(*) AS transactions,
            COALESCE(SUM(quantity_sold), 0)
                AS items_sold,
            COALESCE(SUM(total_amount), 0)
                AS revenue
        FROM sales
    """).fetchone()

    today = conn.execute("""
        SELECT
            COALESCE(SUM(total_amount), 0)
            AS today_sales
        FROM sales
        WHERE date(sale_date) = date('now')
    """).fetchone()

    conn.close()

    return {
        "transactions":
            summary["transactions"],

        "items_sold":
            summary["items_sold"],

        "revenue":
            summary["revenue"],

        "today_sales":
            today["today_sales"]
    }


# =========================
# EXPORT INVENTORY CSV
# =========================

@app.route("/export/inventory")
def export_inventory():

    conn = get_db()

    data = conn.execute("""
        SELECT
            id,
            barcode,
            name,
            category,
            price,
            quantity,
            unit,
            low_stock_level
        FROM products
        ORDER BY id
    """).fetchall()

    conn.close()

    output = io.StringIO()

    writer = csv.writer(output)

    writer.writerow([
        "ID",
        "Barcode",
        "Product",
        "Category",
        "Price",
        "Quantity",
        "Unit",
        "Low Stock Level"
    ])

    for row in data:

        writer.writerow([
            row["id"],
            row["barcode"],
            row["name"],
            row["category"],
            row["price"],
            row["quantity"],
            row["unit"],
            row["low_stock_level"]
        ])

    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={
            "Content-Disposition":
                "attachment; filename=inventory.csv"
        }
    )


# =========================
# EXPORT SALES CSV
# =========================

@app.route("/export/sales")
def export_sales():

    conn = get_db()

    data = conn.execute("""
        SELECT
            sales.sale_id,
            products.name,
            products.barcode,
            sales.quantity_sold,
            sales.total_amount,
            sales.sale_date
        FROM sales
        JOIN products
        ON sales.product_id = products.id
        ORDER BY sales.sale_id DESC
    """).fetchall()

    conn.close()

    output = io.StringIO()

    writer = csv.writer(output)

    writer.writerow([
        "Sale ID",
        "Product",
        "Barcode",
        "Quantity Sold",
        "Total Amount",
        "Sale Date"
    ])

    for row in data:

        writer.writerow([
            row["sale_id"],
            row["name"],
            row["barcode"],
            row["quantity_sold"],
            row["total_amount"],
            row["sale_date"]
        ])

    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={
            "Content-Disposition":
                "attachment; filename=sales.csv"
        }
    )


# =========================
# DELETE PRODUCT
# =========================

@app.route("/delete-product/<int:id>", methods=["DELETE"])
def delete_product(id):

    conn = get_db()

    product = conn.execute("""
        SELECT *
        FROM products
        WHERE id = ?
    """, (id,)).fetchone()

    if product is None:

        conn.close()

        return {
            "error": "Product not found"
        }, 404

    sales_count = conn.execute("""
        SELECT COUNT(*)
        FROM sales
        WHERE product_id = ?
    """, (id,)).fetchone()[0]

    history_count = conn.execute("""
        SELECT COUNT(*)
        FROM inventory_history
        WHERE product_id = ?
    """, (id,)).fetchone()[0]

    if sales_count > 0 or history_count > 0:

        conn.close()

        return {
            "error":
            "This product has transaction history and cannot be deleted"
        }, 400

    conn.execute("""
        DELETE FROM products
        WHERE id = ?
    """, (id,))

    conn.commit()
    conn.close()

    return {
        "message": "Product deleted successfully"
    }


# =========================
# START
# =========================

init_db()

if __name__ == "__main__":
    app.run(debug=True)