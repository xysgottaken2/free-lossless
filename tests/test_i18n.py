import re
import unittest

import i18n
from settings import DEFAULT_SETTINGS, normalize_settings


PLACEHOLDER = re.compile(r"\{([a-z_]+)\}")


class CatalogTests(unittest.TestCase):
    def tearDown(self):
        i18n.set_language(i18n.DEFAULT_LANGUAGE)

    def test_every_language_carries_the_same_keys(self):
        tables = i18n._TRANSLATIONS
        base = set(tables[i18n.DEFAULT_LANGUAGE])
        self.assertIn("en", i18n.LANGUAGES)
        self.assertEqual(set(i18n.LANGUAGES), {"en", "pt-BR", "zh-CN"})
        for language in i18n.LANGUAGES:
            with self.subTest(language=language):
                self.assertEqual(set(tables[language]), base)

    def test_no_translation_is_empty(self):
        for language, table in i18n._TRANSLATIONS.items():
            for key, value in table.items():
                with self.subTest(language=language, key=key):
                    self.assertTrue(value.strip())

    def test_placeholders_match_the_english_text(self):
        english = i18n._TRANSLATIONS["en"]
        for language, table in i18n._TRANSLATIONS.items():
            for key, value in table.items():
                with self.subTest(language=language, key=key):
                    self.assertEqual(set(PLACEHOLDER.findall(value)),
                                     set(PLACEHOLDER.findall(english[key])))

    def test_the_tagline_exists_in_all_three_languages(self):
        self.assertEqual(i18n.translate("app.subtitle", "en"),
                         "More fluidity. Without modifying your game.")
        self.assertEqual(i18n.translate("app.subtitle", "pt-BR"),
                         "Mais fluidez. Sem modificar seu jogo.")
        self.assertTrue(i18n.translate("app.subtitle", "zh-CN"))


class LookupTests(unittest.TestCase):
    def tearDown(self):
        i18n.set_language(i18n.DEFAULT_LANGUAGE)

    def test_unknown_languages_fall_back_to_english(self):
        self.assertEqual(i18n.normalize_language("klingon"), "en")
        self.assertEqual(i18n.normalize_language(None), "en")
        self.assertEqual(i18n.normalize_language("PT-BR"), "pt-BR")
        self.assertEqual(i18n.set_language("de"), "en")

    def test_first_launch_defaults_to_english(self):
        self.assertEqual(i18n.DEFAULT_LANGUAGE, "en")
        self.assertEqual(DEFAULT_SETTINGS["language"], "en")
        self.assertEqual(normalize_settings(None)["language"], "en")
        self.assertEqual(normalize_settings({"language": "zh-CN"})["language"], "zh-CN")
        self.assertEqual(normalize_settings({"language": 7})["language"], "en")

    def test_translation_falls_back_when_a_key_is_missing(self):
        self.assertEqual(i18n.translate("does.not.exist", "pt-BR"), "does.not.exist")

    def test_missing_fields_never_raise(self):
        self.assertEqual(i18n.translate("source.count_many", "en"), "{count} sources available")
        self.assertIn("3", i18n.translate("source.count_many", "en", count=3))

    def test_language_name_and_code_round_trip(self):
        for code in i18n.LANGUAGES:
            name = i18n.language_name(code)
            self.assertTrue(name)
            self.assertEqual(i18n.language_code(name), code)
        self.assertEqual(i18n.language_code("unknown"), "en")


if __name__ == "__main__":
    unittest.main()
