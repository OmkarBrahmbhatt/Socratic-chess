import unittest

from app import create_app


class HomePageTests(unittest.TestCase):
    def setUp(self):
        self.client = create_app().test_client()

    def test_home_page_has_rating_form(self):
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"What is your chess rating?", response.data)

    def test_valid_rating_is_confirmed(self):
        response = self.client.post("/", data={"rating": "1200"})

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Rating received: 1200", response.data)

    def test_non_integer_rating_is_rejected(self):
        response = self.client.post("/", data={"rating": "beginner"})

        self.assertEqual(response.status_code, 400)
        self.assertIn(b"Enter a whole-number rating.", response.data)

    def test_negative_rating_is_rejected(self):
        response = self.client.post("/", data={"rating": "-1"})

        self.assertEqual(response.status_code, 400)
        self.assertIn(b"Enter a rating of zero or higher.", response.data)


if __name__ == "__main__":
    unittest.main()
