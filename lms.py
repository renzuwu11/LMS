from flask import Flask, render_template, redirect, url_for, jsonify
import psycopg2
import requests
from datetime import datetime

app = Flask(__name__)

# Database connection
def lmsdb():
    conn = psycopg2.connect(
        host="localhost",  
        database="LMS",
        user="postgres",
        password="fms-group3"
    )
    return conn

@app.route('/')
def index():
    conn = lmsdb()
    cur = conn.cursor()

    # Fetch all medicines
    cur.execute("SELECT medicine_id, medicine_name, medicine_cost FROM medicines")
    medicines = cur.fetchall()

    # Fetch all customer purchases and aggregate by customer and purchase date
    cur.execute("""
        SELECT 
            mb.customer_id,
            p.full_name,
            JSON_AGG(
                JSON_BUILD_OBJECT(
                    'purchase_id', mb.purchase_id,
                    'medicine_name', m.medicine_name,
                    'medicine_cost', m.medicine_cost,
                    'quantity', mb.quantity
                )
            ) AS medicines_purchased,
            mb.purchase_date
        FROM medicine_bought mb
        JOIN pharmacy_customers p ON mb.customer_id = p.customer_id
        JOIN medicines m ON mb.medicine_id = m.medicine_id
        GROUP BY mb.customer_id, p.full_name, mb.purchase_date
        ORDER BY mb.purchase_date DESC
    """)
    customer_purchases = cur.fetchall()

    # Format the result for rendering
    formatted_purchases = []
    for purchase in customer_purchases:
        purchase_medicines = purchase[2]  # List of medicines for this purchase
        total_cost = sum(med['medicine_cost'] * med['quantity'] for med in purchase_medicines)

        formatted_purchases.append({
            "purchase_id": purchase[0],  # Add purchase_id here
            "customer_id": purchase[0],
            "full_name": purchase[1],
            "medicines": purchase_medicines,  # JSON array of medicines
            "total_cost": total_cost,
            "purchase_date": purchase[3].strftime("%B %d, %Y - %H:%M") if purchase[3] else None
        })

    cur.close()
    conn.close()

    # Pass the medicines list and formatted purchases to the template
    return render_template('index.html', medicines=medicines, customer_purchases=formatted_purchases)

@app.route('/send_to_billing/<int:customer_id>', methods=['POST'])
def send_to_billing(customer_id):
    conn_lms = lmsdb()
    cur_lms = conn_lms.cursor()

    # Fetch purchase details for the specific customer
    cur_lms.execute("""
        SELECT 
            mb.purchase_id, 
            mb.customer_id, 
            mb.medicine_id, 
            m.medicine_cost, 
            mb.quantity
        FROM medicine_bought mb
        JOIN medicines m ON mb.medicine_id = m.medicine_id
        WHERE mb.customer_id = %s
    """, (customer_id,))

    purchases = cur_lms.fetchall()

    if not purchases:
        return "No purchases found for this customer.", 404

    # Group purchases by customer_id and purchase_id to combine purchases on the same day
    purchase_data = {}
    for purchase in purchases:
        purchase_id = purchase[0]
        customer_id = purchase[1]
        medicine_id = purchase[2]
        medicine_cost = float(purchase[3])  # Convert Decimal to float here
        quantity = purchase[4]

        # Creating unique keys for purchases by customer_id and purchase_id
        if (customer_id, purchase_id) not in purchase_data:
            purchase_data[(customer_id, purchase_id)] = {
                'purchase_id': purchase_id,
                'customer_id': customer_id,
                'medicines': [],
                'total_cost': 0
            }

        # Add medicine data to the group
        purchase_data[(customer_id, purchase_id)]['medicines'].append({
            'medicine_id': medicine_id,  # Ensure this is included
            'quantity': quantity,
            'medicine_cost': medicine_cost
        })

        # Update total cost for this purchase group
        purchase_data[(customer_id, purchase_id)]['total_cost'] += (medicine_cost * quantity)

    # Send aggregated data to FMS
    fms_api_url = "http://127.0.0.1:7000/api/lms_purchase"  # FMS endpoint
    for purchase_key, data in purchase_data.items():
        # Prepare the payload for sending to FMS
        for medicine in data['medicines']:
            # Send each medicine as a separate purchase record if needed
            purchase_payload = {
                'purchase_id': data['purchase_id'],
                'customer_id': data['customer_id'],
                'medicine_id': medicine['medicine_id'],  # Make sure this is part of the payload
                'quantity': medicine['quantity'],
                'medicine_cost': medicine['medicine_cost']
            }

            try:
                response = requests.post(fms_api_url, json=purchase_payload)
                if response.status_code != 200:
                    app.logger.error(f"Error sending purchase {data['purchase_id']} to FMS: {response.text}")
            except Exception as e:
                app.logger.error(f"Exception while sending purchase {data['purchase_id']} to FMS: {e}")

    cur_lms.close()
    conn_lms.close()

    return redirect(url_for('index'))  # Redirect to LMS page after sending data

@app.route('/api/customers/<int:customer_id>', methods=['GET'])
def get_customer_details(customer_id):
    try:
        conn_lms = lmsdb()
        cur_lms = conn_lms.cursor()

        # Query to fetch customer details, including date_of_birth
        cur_lms.execute("""
            SELECT customer_id, full_name, contact_number, date_of_birth
            FROM pharmacy_customers
            WHERE customer_id = %s
        """, (customer_id,))

        customer = cur_lms.fetchone()

        if not customer:
            return jsonify({"error": "Customer not found"}), 404

        customer_data = {
            "customer_id": customer[0],
            "full_name": customer[1],
            "contact_number": customer[2],
            "date_of_birth": customer[3] 
        }

        cur_lms.close()
        conn_lms.close()

        return jsonify(customer_data), 200

    except Exception as e:
        print(f"Error retrieving customer details: {e}")
        return jsonify({"error": "Internal Server Error"}), 500


@app.route('/api/medicines/<int:medicine_id>', methods=['GET'])
def get_medicine_details(medicine_id):
    try:
        conn_lms = lmsdb()
        cur_lms = conn_lms.cursor()

        # Query to fetch medicine details
        cur_lms.execute("SELECT medicine_id, medicine_name, medicine_cost FROM medicines WHERE medicine_id = %s", (medicine_id,))
        medicine = cur_lms.fetchone()

        if not medicine:
            return jsonify({"error": "Medicine not found"}), 404

        medicine_data = {
            "medicine_id": medicine[0],
            "medicine_name": medicine[1],
            "medicine_cost": float(medicine[2])  # Convert Decimal to float
        }

        cur_lms.close()
        conn_lms.close()

        return jsonify(medicine_data), 200

    except Exception as e:
        print(f"Error retrieving medicine details: {e}")
        return jsonify({"error": "Internal Server Error"}), 500

if __name__ == '__main__':
    app.run(debug=True)
