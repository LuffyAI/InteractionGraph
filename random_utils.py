import random
import string


def roll_dice(count=2, sides=6):
    if count < 1 or sides < 1:
        raise ValueError("count and sides must be positive")
    return [random.randint(1, sides) for _ in range(count)]


def random_word(length=8):
    if length < 1:
        raise ValueError("length must be positive")
    return "".join(random.choices(string.ascii_lowercase, k=length))


def shuffled_copy(items):
    result = list(items)
    random.shuffle(result)
    return result
