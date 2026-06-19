from flask import Flask, render_template

app = Flask(__name__)

@app.route("/")
def login():
    return """
    <h1>Essayons Operations Management System</h1>
    <h2>Login Screen</h2>
    <p>Admin: xperez2301</p>
    """

@app.route("/dispatch-map")
def dispatch_map():
    return """
    <h1>Dispatch Map</h1>

    <h3>Selected Stores</h3>

    <p>Stores: 0</p>
    <p>Racks: 0</p>
    <p>Weight: 0 lbs</p>
    """

if __name__ == "__main__":
    app.run(debug=True)