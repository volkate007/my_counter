from flask import Flask

app = Flask(__name__)

@app.route("/")
def hello_world():
    return "<h1>Hello, World!</h1><p>Добро пожаловать в моё первое веб-приложение на Python!</p>"

if __name__ == "__main__":
    app.run(debug=True)
