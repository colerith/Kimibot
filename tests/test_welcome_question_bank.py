import json
import unittest
from pathlib import Path
from cogs.welcome.data import QUIZ_QUESTIONS


class QuestionBankTests(unittest.TestCase):
    def test_live_bank_compatible_and_valid(self):
        self.assertEqual(len(QUIZ_QUESTIONS), 150)
        self.assertEqual(len({q['id'] for q in QUIZ_QUESTIONS}), 150)
        for q in QUIZ_QUESTIONS:
            with self.subTest(id=q['id']):
                self.assertTrue(q['question'].strip())
                self.assertEqual(set(q['options']), set('ABCD'))
                answers = q['answers'] if q.get('type') == 'multiple' else [q['answer']]
                self.assertTrue(set(answers) <= set(q['options']))
                self.assertEqual(len(answers), len(set(answers)))
                if q.get('type') == 'multiple':
                    self.assertGreaterEqual(len(answers), 2)
                    self.assertLess(len(answers), len(q['options']))
                self.assertEqual(len(set(q['options'].values())), 4)
                self.assertTrue(all(v.strip() for v in q['options'].values()))
                self.assertLess(len(q['question']) + sum(map(len, q['options'].values())), 3500)
                if 'reviewed_at' in q:
                    self.assertTrue(q['explanation'])
                    self.assertTrue(all(s.startswith('https://') for s in q['sources']))
        self.assertEqual(sum('reviewed_at' in q for q in QUIZ_QUESTIONS), 82)

    def test_multiple_drafts_not_in_live_bank(self):
        path = Path(__file__).resolve().parents[1] / 'docs/quiz-multiple-choice-draft.json'
        drafts = json.loads(path.read_text(encoding='utf-8'))
        self.assertEqual(len(drafts), 6)
        for q in drafts:
            self.assertFalse(q['enabled'])
            self.assertEqual(q['type'], 'multiple')
            self.assertLess(len(q['answers']), len(q['options']))
            self.assertGreaterEqual(len(q['answers']), 2)
            self.assertEqual(len(set(q['answers'])), len(q['answers']))
            self.assertTrue(set(q['answers']) <= set(q['options']))
            self.assertNotIn(q['id'], {row['id'] for row in QUIZ_QUESTIONS})
