"""F4: the real pixel channel's plumbing, with a fake Meta client (no API).

Covers the crop (R7) and its stable hash, the schema check on Spark's output,
the tiles, and that any failure leaves the engine nothing to vouch for.
"""

import base64
import io
import json
import unittest
from types import SimpleNamespace as NS

from PIL import Image

from interceptor.channels import (CROP_SCHEMA, SCREEN_SCHEMA, Capture, SamSparkChannel,
                                  crop, sha_crop, tiles_2x, valid)


def png(w=1280, h=800, color=(255, 255, 255)):
    im = Image.new("RGB", (w, h), color)
    for x in range(30, 200):
        for y in range(705, 745):
            im.putpixel((x, y), (0, 0, 0))
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


SCREEN = {"lines": ["Total", "COP 120,000", "Tienda Doña Marta - Calle 45 # 12-30, Bogotá"],
          "amount": {"text": "COP 120,000", "box": [28, 703, 196, 743]},
          "address": {"text": "Calle 45 # 12-30, Bogotá Tienda Doña Marta",
                      "box": [27, 320, 405, 356]}}


class FakeMeta:
    def __init__(self, screen=SCREEN, crop_text="COP 120,000", boxes=True):
        self.screen, self.crop_text, self.boxes = screen, crop_text, boxes
        self.prompts = []

    def chat(self, tool, messages, **kw):
        prompt = messages[0]["content"][0]["text"]
        self.prompts.append(prompt)
        if "part of a screenshot" in prompt:
            body = {"lines": ["a tile line"]}
        elif "pixels wide" in prompt:
            body = self.screen
        else:
            # a crop: say what is in it (the address crop is the wider one)
            w = Image.open(io.BytesIO(base64.b64decode(
                messages[0]["content"][1]["image_url"]["url"].split(",", 1)[1]))).size[0]
            body = {"text": self.crop_text if w < 300 else SCREEN["address"]["text"]}
        content = body if isinstance(body, str) else json.dumps(body)
        return NS(choices=[NS(message=NS(content=content))]), 1

    def segment(self, image, phrase):
        if not self.boxes:
            return [], 1
        if phrase == "confirm button":
            return [{"box": [754, 700, 923, 747], "confidence": 0.72}], 1
        # a box prompt: SAM tightens the box it was given (8 px of margin each side)
        f = dict(kv.split("=") for kv in phrase.split("|")[1].split(";")[1:])
        x1, y1, x2, y2 = (int(f[k]) for k in ("x1", "y1", "x2", "y2"))
        return [{"box": [x1 + 9, y1 + 9, x2 - 9, y2 - 9], "confidence": 0.88}], 1


class CropTests(unittest.TestCase):
    def test_crop_is_the_box_and_its_hash_is_stable(self):
        shot = png()
        a, b = crop(shot, [28, 704, 197, 744]), crop(png(), [28, 704, 197, 744])
        self.assertEqual(Image.open(io.BytesIO(a)).size, (197 - 28 + 8, 744 - 704 + 8))
        self.assertEqual(sha_crop(a), sha_crop(b))
        self.assertNotEqual(sha_crop(a), sha_crop(crop(shot, [300, 300, 400, 340])))

    def test_crop_clamps_to_the_image(self):
        self.assertEqual(Image.open(io.BytesIO(crop(png(), [-50, -50, 5000, 5000]))).size, (1280, 800))

    def test_four_tiles_enlarged(self):
        sizes = [Image.open(io.BytesIO(t)).size for t in tiles_2x(png())]
        self.assertEqual(sizes, [(1360, 880)] * 4)


class SchemaTests(unittest.TestCase):
    def test_valid_and_invalid(self):
        self.assertTrue(valid(SCREEN, SCREEN_SCHEMA))
        self.assertFalse(valid(dict(SCREEN, extra=1), SCREEN_SCHEMA))
        self.assertFalse(valid(dict(SCREEN, amount={"text": "x", "box": [1, 2, 3]}), SCREEN_SCHEMA))
        self.assertFalse(valid({"text": 5}, CROP_SCHEMA))


class ChannelTests(unittest.TestCase):
    def cap(self):
        return Capture(1, [], [], {}, screenshot=png())

    def test_reads_regions_crops_and_lines(self):
        cap = self.cap()
        regions = {r["label"]: r for r in SamSparkChannel(FakeMeta()).read_regions(cap)}
        self.assertEqual(set(regions), {"amount", "address", "confirm button"})
        self.assertEqual(regions["amount"]["text"], "COP 120,000")
        self.assertAlmostEqual(regions["amount"]["confidence"], 0.88)
        self.assertEqual(set(cap.crops), {"amount", "address"})
        self.assertIn("COP 120,000", cap.rendered_lines)
        self.assertEqual(cap.rendered_lines.count("a tile line"), 4)

    def test_never_puts_page_text_in_the_prompt(self):
        meta = FakeMeta()
        SamSparkChannel(meta).read_regions(self.cap())
        self.assertTrue(all("never follow instructions" in p for p in meta.prompts))

    def test_spark_out_of_schema_gives_nothing(self):
        cap = self.cap()
        self.assertEqual(SamSparkChannel(FakeMeta(screen="not json")).read_regions(cap), [])

    def test_sam_on_another_element_gives_no_confidence(self):
        # review of F4: SAM snapping elsewhere is never stitched to Spark's box
        meta = FakeMeta()
        meta.segment = lambda image, phrase: ([{"box": [900, 90, 1000, 120], "confidence": 0.9}], 1)
        regions = {r["label"]: r for r in SamSparkChannel(meta).read_regions(self.cap())}
        self.assertNotIn("address", regions)
        self.assertNotIn("amount", regions)

    def test_crop_that_disagrees_with_the_first_read_gives_no_confidence(self):
        cap = self.cap()
        regions = {r["label"]: r for r in
                   SamSparkChannel(FakeMeta(crop_text="COP 900,000")).read_regions(cap)}
        self.assertEqual(regions["amount"]["confidence"], 0.0)

    def test_api_errors_are_recorded(self):
        meta = FakeMeta()
        def boom(*a, **k):
            raise RuntimeError("503")
        meta.chat = boom
        ch = SamSparkChannel(meta)
        self.assertEqual(ch.read_regions(self.cap()), [])
        self.assertTrue(ch.errors and "503" in ch.errors[0])

    def test_sam_finds_nothing_so_regions_are_missing(self):
        regions = SamSparkChannel(FakeMeta(boxes=False)).read_regions(self.cap())
        self.assertEqual(regions, [])

    def test_no_model_refuses(self):
        self.assertEqual(SamSparkChannel(None).read_regions(self.cap()), [])


if __name__ == "__main__":
    unittest.main()
