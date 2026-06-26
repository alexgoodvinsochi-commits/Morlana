from datetime import date


ZODIAC_DATES = [
    ((1, 20), (2, 18), "Водолей"),
    ((2, 19), (3, 20), "Рыбы"),
    ((3, 21), (4, 19), "Овен"),
    ((4, 20), (5, 20), "Телец"),
    ((5, 21), (6, 20), "Близнецы"),
    ((6, 21), (7, 22), "Рак"),
    ((7, 23), (8, 22), "Лев"),
    ((8, 23), (9, 22), "Дева"),
    ((9, 23), (10, 22), "Весы"),
    ((10, 23), (11, 21), "Скорпион"),
    ((11, 22), (12, 21), "Стрелец"),
    ((12, 22), (1, 19), "Козерог"),
]


def get_zodiac_sign(birth_date: date) -> str:
    month, day = birth_date.month, birth_date.day
    for (start_m, start_d), (end_m, end_d), sign in ZODIAC_DATES:
        if start_m == end_m:
            if start_m == month and start_d <= day <= end_d:
                return sign
        else:
            if (month == start_m and day >= start_d) or (month == end_m and day <= end_d):
                return sign
    return "Козерог"
