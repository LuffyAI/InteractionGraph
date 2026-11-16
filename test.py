"""A few small functions to try out."""

import random


def roll_dice(sides=6):
    return random.randint(1, sides)


def reverse_words(sentence):
    return " ".join(sentence.split()[::-1])


def sum_squares(numbers):
    return sum(number ** 2 for number in numbers)


def is_palindrome(text):
    normalized = "".join(char.lower() for char in text if char.isalnum())
    return normalized == normalized[::-1]


if __name__ == "__main__":
    print("Dice roll:", roll_dice())
    print("Reversed words:", reverse_words("hello from Python"))
    print("Sum of squares:", sum_squares([1, 2, 3, 4, 5]))
    print("Palindrome check:", is_palindrome("A man, a plan, a canal: Panama"))
