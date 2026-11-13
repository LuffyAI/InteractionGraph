import random


def greet(name="World"):
    return f"Hello {name}!"


def random_greeting():
    return greet(random.choice(["World", "Python", "Codex"]))


def greet_many(names):
    return [greet(name) for name in names]


if __name__ == "__main__":
    for name in ["World", "Python", "Codex"]:
        print(greet(name))
