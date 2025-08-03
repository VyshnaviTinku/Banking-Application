from flask import Flask, render_template, request, redirect, url_for, session, flash
from flask_mysqldb import MySQL
import MySQLdb.cursors
from datetime import datetime

app = Flask(__name__)
app.secret_key = 'aslbank_secret'

# MySQL Config
app.config['MYSQL_HOST'] = 'localhost'
app.config['MYSQL_USER'] = 'root'
app.config['MYSQL_PASSWORD'] = 'root'
app.config['MYSQL_DB'] = 'bankdb'

mysql = MySQL(app)

@app.route('/')
def home():
    return render_template("home.html")

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        cursor.execute("SELECT * FROM users WHERE username = %s", (username,))
        account = cursor.fetchone()
        if account:
            flash("⚠️ Account already exists!", "danger")
        else:
            cursor.execute("INSERT INTO users (username, email, password) VALUES (%s, %s, %s)", (username, email, password))
            mysql.connection.commit()
            flash("✅ Registered successfully. Please log in.", "success")
            return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        cursor.execute("SELECT * FROM users WHERE username = %s AND password = %s", (username, password))
        account = cursor.fetchone()
        if account:
            session['loggedin'] = True
            session['id'] = account['id']
            session['username'] = account['username']
            return redirect(url_for('dashboard'))
        else:
            flash("Invalid username or password!", "danger")
    return render_template('login.html')

@app.route('/dashboard')
def dashboard():
    if 'loggedin' not in session:
        return redirect(url_for('login'))

    user_id = session['id']
    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)

    # Fetch balance
    cursor.execute("SELECT balance FROM users WHERE id = %s", (user_id,))
    balance = cursor.fetchone()['balance']

    # Fetch recent transactions
    cursor.execute("SELECT * FROM transactions WHERE user_id = %s ORDER BY timestamp DESC", (user_id,))
    transactions = cursor.fetchall()

    # Fetch month-wise inflows (deposit + receive) and outflows (withdraw + transfer)
    cursor.execute("""
        SELECT 
            MONTHNAME(timestamp) AS month,
            MONTH(timestamp) AS month_num,
            SUM(CASE WHEN type IN ('deposit', 'receive') THEN amount ELSE 0 END) AS inflows,
            SUM(CASE WHEN type IN ('withdraw', 'transfer') THEN amount ELSE 0 END) AS outflows
        FROM transactions
        WHERE user_id = %s AND YEAR(timestamp) = YEAR(CURDATE())
        GROUP BY MONTHNAME(timestamp), MONTH(timestamp)
        ORDER BY MONTH(timestamp)
    """, (user_id,))
    monthly_data = cursor.fetchall()

    # Convert to dictionary for Chart.js
    monthly_summary = {
        row['month']: {
            'inflows': row['inflows'] or 0,
            'outflows': row['outflows'] or 0
        }
        for row in monthly_data
    }

    return render_template('dashboard.html',
                           username=session['username'],
                           balance=balance,
                           transactions=transactions,
                           monthly_summary=monthly_summary)



@app.route('/deposit', methods=['GET', 'POST'])
def deposit():
    if 'loggedin' not in session:
        return redirect(url_for('login'))

    if request.method == 'POST':
        amount = float(request.form['amount'])
        user_id = session['id']
        cursor = mysql.connection.cursor()
        cursor.execute("UPDATE users SET balance = balance + %s WHERE id = %s", (amount, user_id))
        cursor.execute("INSERT INTO transactions (user_id, type, amount) VALUES (%s, 'deposit', %s)", (user_id, amount))
        mysql.connection.commit()
        return redirect(url_for('dashboard'))

    return render_template('deposit.html')

@app.route('/withdraw', methods=['GET', 'POST'])
def withdraw():
    if 'loggedin' not in session:
        return redirect(url_for('login'))

    if request.method == 'POST':
        amount = float(request.form['amount'])
        user_id = session['id']
        cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)
        cursor.execute("SELECT balance FROM users WHERE id = %s", (user_id,))
        balance = cursor.fetchone()['balance']

        if balance >= amount:
            cursor.execute("UPDATE users SET balance = balance - %s WHERE id = %s", (amount, user_id))
            cursor.execute("INSERT INTO transactions (user_id, type, amount) VALUES (%s, 'withdraw', %s)", (user_id, amount))
            mysql.connection.commit()
        else:
            flash("Insufficient balance!", "danger")
        return redirect(url_for('dashboard'))

    return render_template('withdraw.html')

@app.route('/transfer', methods=['GET', 'POST'])
def transfer():
    if 'loggedin' not in session:
        return redirect(url_for('login'))

    user_id = session['id']
    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)

    if request.method == 'POST':
        recipient_username = request.form['recipient']
        amount = float(request.form['amount'])

        # Get sender balance
        cursor.execute("SELECT balance FROM users WHERE id = %s", (user_id,))
        sender_balance = cursor.fetchone()['balance']

        if amount <= 0:
            flash("Enter a valid amount.", "danger")
        elif amount > sender_balance:
            flash("Insufficient balance!", "danger")
        else:
            # Check recipient
            cursor.execute("SELECT id FROM users WHERE username = %s", (recipient_username,))
            recipient = cursor.fetchone()

            if recipient and recipient['id'] != user_id:
                recipient_id = recipient['id']

                # Update sender balance
                cursor.execute("UPDATE users SET balance = balance - %s WHERE id = %s", (amount, user_id))
                # Update recipient balance
                cursor.execute("UPDATE users SET balance = balance + %s WHERE id = %s", (amount, recipient_id))

                # Insert transaction for sender
                cursor.execute("""
                    INSERT INTO transactions (user_id, type, amount, description) 
                    VALUES (%s, 'transfer', %s, %s)
                """, (user_id, amount, f'Transferred to {recipient_username}'))

                # Insert transaction for recipient
                cursor.execute("""
                    INSERT INTO transactions (user_id, type, amount, description) 
                    VALUES (%s, 'receive', %s, %s)
                """, (recipient_id, amount, f'Received from {session["username"]}'))

                mysql.connection.commit()
                flash("Transfer successful ✅", "success")
                return redirect(url_for('dashboard'))
            else:
                flash("Invalid recipient.", "danger")

    return render_template("transfer.html")



@app.route('/history')
def history():
    if 'loggedin' not in session:
        return redirect(url_for('login'))

    user_id = session['id']
    username = session['username']
    cursor = mysql.connection.cursor(MySQLdb.cursors.DictCursor)

    # Fetch transfer and receive transactions
    cursor.execute("""
        SELECT 
            t.type,
            t.amount,
            t.timestamp,
            CASE 
                WHEN t.type = 'transfer' THEN 
                    SUBSTRING_INDEX(t.description, 'to ', -1)
                WHEN t.type = 'receive' THEN 
                    SUBSTRING_INDEX(t.description, 'from ', -1)
            END AS counterparty
        FROM transactions t
        WHERE t.user_id = %s AND (t.type = 'transfer' OR t.type = 'receive')
        ORDER BY t.timestamp DESC
    """, (user_id,))
    transactions = cursor.fetchall()

    return render_template("history.html", transactions=transactions)







@app.route('/logout')
def logout():
    session.clear()
    flash("👋 Logged out successfully.", "info")
    return redirect(url_for('home'))

if __name__ == '__main__':
    app.run(debug=True)