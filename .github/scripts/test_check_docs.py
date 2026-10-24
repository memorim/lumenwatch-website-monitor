import tempfile
import unittest
from pathlib import Path

from check_docs import check_document


class PathsTest(unittest.TestCase):
    def test_real_paths_references_and_code_examples(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            (root / "screen shot.png").write_bytes(b"png")
            file = root / "README.md"
            file.write_text(
                "![image](<screen shot.png>)\n[ref][asset]\n"
                "[asset]: screen%20shot.png\n```md\n[example](missing.png)\n```\n",
                encoding="utf-8",
            )
            self.assertEqual(check_document(file, root)[0], [])
            file.write_text(
                "[missing](missing.png)\n[private](C:/Users/example/file.md)\n[local](http://localhost:8000/)\n",
                encoding="utf-8",
            )
            self.assertEqual(len(check_document(file, root)[0]), 3)


if __name__ == "__main__":
    unittest.main()
