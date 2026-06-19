from flask import Flask

app = Flask(__name__)

@app.route("/")
def home():
    return """
    <h1>Essayons Bax Operations</h1>
    <p>Dispatch Hub Coming Soon</p>
    <a href='/login'>Login</a>
    """

@app.route("/login")
def login():
    return """
    <h1>Login</h1>
    <p>Login screen coming soon...</p>
    """

if __name__ == "__main__":
    app.run(debug=True)
