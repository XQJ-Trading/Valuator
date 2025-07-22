import unittest
from valuator.utils.datalake.cache import Cache

class TestCache(unittest.TestCase):
    def test_singleton(self):
        """
        Test if the cache is a singleton.
        """
        cache1 = Cache()
        cache2 = Cache()
        self.assertIs(cache1, cache2)

    def test_set_get(self):
        """
        Test setting and getting values.
        """
        cache = Cache()
        cache.set("test_key", "test_value")
        self.assertEqual(cache.get("test_key"), "test_value")

    def test_getitem_setitem(self):
        """
        Test setting and getting values using dictionary-like syntax.
        """
        cache = Cache()
        cache["test_key_2"] = "test_value_2"
        self.assertEqual(cache["test_key_2"], "test_value_2")

    def test_get_default(self):
        """
        Test getting a default value for a non-existent key.
        """
        cache = Cache()
        self.assertEqual(cache.get("non_existent_key"), "")
        self.assertEqual(cache.get("non_existent_key", "default"), "default")

    def test_key_error(self):
        """
        Test that accessing a non-existent key with __getitem__ returns empty string.
        """
        cache = Cache()
        self.assertEqual(cache["non_existent_key_for_error"], "")

if __name__ == '__main__':
    unittest.main() 