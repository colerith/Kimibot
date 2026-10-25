import random

QUIZ_DURATION = 300


def expected_answers(question):
    return set(question['answers'] if question.get('type') == 'multiple' else [question['answer']])


def is_correct(question, selected):
    values = [selected] if isinstance(selected, str) else list(selected or [])
    return bool(values) and len(values) == len(set(values)) and set(values) == expected_answers(question)


def draw_questions(bank):
    single = [q for q in bank if q.get('type') != 'multiple']
    multi = [q for q in bank if q.get('type') == 'multiple']
    result = random.sample(single, 12) + random.sample(multi, 3)
    random.shuffle(result)
    return result
