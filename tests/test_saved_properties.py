import io
import struct
import unittest
from unittest.mock import patch

from fm_live_mcp import saved_properties as properties
from fm_live_mcp.saved_component_stream import BLOCK_SIZE, Reader


def integer(value):
    return struct.pack("<I", value)


def variant(kind, payload=b""):
    return bytes((1, kind)) + payload


def reader(data):
    return Reader(io.BytesIO(data), len(data))


class SavedPropertiesTests(unittest.TestCase):
    def test_empty_map_and_vector(self):
        for parse in (properties.skip_property_map, properties.skip_property_vector):
            value = reader(integer(0) + b"NEXT")
            parse(value)
            self.assertEqual(value.offset, 4)
            self.assertEqual(value.take(4), b"NEXT")

    def test_nested_vector_map_and_registered_extension(self):
        mapping = integer(2) + b"abcd" + variant(32, integer(99))
        mapping += b"efgh" + variant(26, integer(3) + b"caf")
        wire = integer(1) + variant(10, mapping)
        value = reader(wire + b"NEXT")
        properties.skip_property_vector(value)
        self.assertEqual(value.offset, len(wire))
        self.assertEqual(value.take(4), b"NEXT")

    def test_direct_map_with_nested_vector(self):
        wire = integer(1) + b"abcd" + variant(11, integer(1) + variant(18, b"\xff\xff"))
        value = reader(wire)
        properties.skip_property_map(value)
        self.assertEqual(value.offset, len(wire))

    def test_each_verified_scalar_and_empty_type(self):
        widths = {
            1: 4,
            2: 4,
            3: 1,
            5: 8,
            15: 8,
            17: 1,
            18: 2,
            19: 1,
            20: 2,
            21: 4,
            24: 8,
            25: 4,
            27: 8,
            32: 4,
        }
        wire = integer(len(widths) + 3)
        wire += b"".join(variant(kind, b"x" * size) for kind, size in widths.items())
        wire += b"".join(variant(kind) for kind in (0, 6, 7))
        value = reader(wire)
        properties.skip_property_vector(value)
        self.assertEqual(value.offset, len(wire))

    def test_every_truncation_of_nested_object(self):
        wire = integer(1) + variant(
            10, integer(1) + b"abcd" + variant(11, integer(1) + variant(32, integer(7)))
        )
        for end in range(len(wire)):
            with self.subTest(end=end), self.assertRaises(ValueError):
                properties.skip_property_vector(reader(wire[:end]))

    def test_unknown_extension_and_invalid_text(self):
        for wire in (
            integer(1) + variant(255),
            integer(1) + variant(26, integer(1) + b"\xff"),
            integer(1) + variant(26, integer(8193)),
        ):
            with self.subTest(wire=wire), self.assertRaises(ValueError):
                properties.skip_property_vector(reader(wire))

    def test_nested_objects_share_work_budget(self):
        # Each nested collection is small; their combined variants exceed four.
        child = variant(11, integer(2) + variant(0) + variant(0))
        wire = integer(2) + child + child
        with patch.object(properties, "MAX_PROPERTY_NODES", 4):
            with self.assertRaises(ValueError):
                properties.skip_property_vector(reader(wire))
        with self.assertRaises(ValueError):
            properties.skip_property_vector(
                reader(integer(properties.MAX_PROPERTY_NODES + 1))
            )

    def test_depth_and_byte_budgets(self):
        wire = variant(0)
        for _ in range(18):
            wire = variant(11, integer(1) + wire)
        with self.assertRaises(ValueError):
            properties.skip_property_vector(reader(integer(1) + wire))
        with patch.object(properties, "MAX_PROPERTY_BYTES", 8):
            with self.assertRaises(ValueError):
                properties.skip_property_vector(
                    reader(integer(1) + variant(32, integer(1)))
                )

    def test_cross_block_streaming_and_per_object_reset(self):
        count = BLOCK_SIZE // 3
        wire = integer(count) + variant(17, b"\x01") * count
        value = reader(wire + wire)
        properties.skip_property_vector(value)
        self.assertEqual(value.offset, len(wire))
        properties.skip_property_vector(value)
        self.assertEqual(value.offset, 2 * len(wire))


if __name__ == "__main__":
    unittest.main()
