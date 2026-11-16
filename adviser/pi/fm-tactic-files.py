#!/usr/bin/env python3
"""Bounded standalone native tactic authoring using the existing FM26 codec.

Never attaches to Football Manager. Writes a new file in its Tactics folder only
when explicitly requested; existing files are never overwritten.
"""
from __future__ import annotations

import hashlib
import base64
import subprocess
import json
import os
from pathlib import Path
import re
import struct
import sys
import tempfile
import unicodedata
from datetime import datetime, timezone
from uuid import uuid4

CODEC_ROOT = Path(os.environ.get('PI_FM_TACTIC_CODEC_ROOT', '/Users/jamesheffernan/GitHub/FM26 Deepener'))
sys.path.insert(0, str(CODEC_ROOT))
from scripts.probe_fmf_tactic_archive import probe, INNER_MAGIC
from scripts.decode_fmf_tactic import parse_tac_plaintext
from scripts.repack_fmf_tactic import (
    extract_member_plaintexts, repack_native_fmf, replace_tac_name, replace_mentality,
)
import zstandard as zstd

NATIVE_READER_ROOT = Path(os.environ.get('PI_FM_TACTIC_READER_ROOT', '/Volumes/4TB Private/Offloaded/FMCP 27'))
sys.path.insert(0, str(NATIVE_READER_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
if os.environ.get('PI_FM_NATIVE_BINARY') and not os.environ.get('FMCP_PLUGIN_PATH'):
    os.environ['FMCP_PLUGIN_PATH'] = os.environ['PI_FM_NATIVE_BINARY']   # the address book identifies the plugin the writer runs
try:
    # Binds this writer to the installed game build through the reader's address map; on the
    # pinned build (and with a reader that lacks it) nothing changes.
    from fm_live_mcp import adviser_book
except ImportError:
    adviser_book = None
if __name__ == '__main__' and adviser_book is not None and adviser_book.rerun_as_main(__file__, globals()):
    raise SystemExit(0)
from fm_live_mcp.prepared_tactic_instructions import OPTION_NAMES
from fm_live_mcp.prepared_tactic_roles import ENGLISH_RESOURCE_SHA256
from fm_live_mcp.prepared_tactic_roles import decode_word
from fm_live_mcp.prepared_tactic_roles import DUTY_BRANCHES as FIXED_BIT_BRANCHES
from fm_tactic_position_records import decode_position_records


def word_label_binding(word: int, phase: str) -> tuple:
    """(role name, fixed-bit text, role text id, fixed-bit text id) of one stored role word.

    A stored word is the role's bit plus one bit the game fixes for that role. The donor
    validators compare both with their proved records. Football Manager 27 shows a role and
    nothing else, so the fixed bit is never requested and never part of a result.
    """
    decoded = decode_word(word, phase)
    fixed = next((row for row in FIXED_BIT_BRANCHES if word & (1 << row[0])), None)
    return (decoded['compiled_english_name'], fixed[2] if fixed else None,
            decoded['native_resource_key'], fixed[1] if fixed else None)

TEMPLATES = Path(os.environ.get('FM27_TACTICS_DIR', str(Path.home() / 'Library/Application Support/Sports Interactive/Football Manager 27/Tactics'))).expanduser()
OUTPUTS = Path.home() / 'Agent Outputs'
MAX_TEMPLATE_BYTES = 16 * 1024 * 1024
MENTALITIES = {1: 'Very Defensive', 2: 'Defensive', 3: 'Cautious', 4: 'Balanced', 5: 'Positive', 6: 'Attacking', 7: 'Very Attacking'}
TACKLING_FLAGS = {'No explicit selection': 0, 'Get Stuck In': 1, 'Stay On Feet': 2}
CODEC_FILES = ['probe_fmf_tactic_archive.py', 'decode_fmf_tactic.py', 'repack_fmf_tactic.py']
ROLE_RECORD_PREFIX_SHA = '0ee9abe8ab6dfb5d0d64e4f86747e601a558c81409423a5d6bffa3ab5d02327e'
ROLE_NATIVE_PLUGIN = Path.home() / 'Library/Application Support/Steam/steamapps/common/Football Manager 27/fm.app/Contents/PlugIns/game_plugin.bundle/Contents/MacOS/game_plugin'
ROLE_NATIVE_SPANS = (
    (0x53910C, 0x120, '00438b98b02bc6b475b44f33d80417f814f4c9cd0e18810ab52d1a3fff51f29d'),
    (0x4976E00, 0x840, '0a753195cea3fb9b873eb2759a7b2240e3792f14381085a48663c12a97287531'),
    (0x4975000, 0x1200, '4d20d46b9887e17c5c5acf8834512e1f55820cb8e4e036fee17ccce47c3fc327'),
    (0x4ADE568, 0x294, 'fd5cb2de2e7b332df5b30fdd4045ed8ca4b4136e72da011822ac765d51d7a081'),
)
LOSS_NATIVE_PLUGIN = ROLE_NATIVE_PLUGIN
LOSS_ENGLISH_RESOURCE = LOSS_NATIVE_PLUGIN.parent.parent / 'Resources/data/game_simulation/templates/user_folder/languages/example.ltf'
LOSS_NATIVE_SPANS = (
    (0x54010E4, 792, 'dc072c6bed505968347c2e8f5c83d4db7187231c97f9ad57f02d27099aa1d10a'),
    (0x5401002, 4, 'd484c09a42aaba8061f732919ae178624ab91633ab0851553d8eaf4a0209bdd1'),
    (0x4867D64, 16, 'a9a39e75e643c1e8f1f38dec5be867f83aa36d5ef9db1c64193291d8a7fe01de'),
    (0x4866C64, 20, 'e96503e04c9768cea007656789d83fa115a052472425ae21799f1ac7040dbbfc'),
    (0x44694E8, 112, '10c4d9afee07bc30c2e3923376554490854386df9b82b8809f7ef4554296fcf4'),
    (0x44695D0, 36, '26d1bb0b82ccdc7a0dbc5e7e941e448604c062a5c728dd17bdf933fad437c74d'),
    (0x4469558, 44, '01b10cb8d5d37bb4c58819545a2dc6d6592b00be2c411dd50e27fff0c67687db'),
    (0x19F345C, 136, '9102590af3e5e01941a99395a2205db1d415f7ff98480b00b0de2e4400eb3246'),
    (0x4A8E878, 372, '72f82016468792d460d84bb6a83cf712fc1b9e46324864532d41036dcb100674'),
    (0x4A8EB90, 228, '301780014cd1c3808038f815e76264f2c8e38af0d57c98bc3cd10ff01b8742c5'),
)


GAIN_NATIVE_PLUGIN = ROLE_NATIVE_PLUGIN
GAIN_ENGLISH_RESOURCE = GAIN_NATIVE_PLUGIN.parent.parent / 'Resources/data/game_simulation/templates/user_folder/languages/example.ltf'
GAIN_NATIVE_SPANS = (
    (0x54010e4, 792, 'dc072c6bed505968347c2e8f5c83d4db7187231c97f9ad57f02d27099aa1d10a'),
    (0x5400fe2, 4, '5c0f4a5fb00bfc596a4cd33ae7d3dbbd7ab530d1760932a9139c88f6c9013ef1'),
    (0x4866118, 20, 'af4d8d3ee65a61e57a00b5c77f1a4c4ce32fb93fa4b55f0ae8962f0788f4f3dd'),
    (0x4867360, 20, '28ff88470b81eb916a642b03d459ac8469056be38c07a3bfc2c48379af7bebcc'),
    (0x44694e8, 112, '10c4d9afee07bc30c2e3923376554490854386df9b82b8809f7ef4554296fcf4'),
    (0x44695d0, 36, '26d1bb0b82ccdc7a0dbc5e7e941e448604c062a5c728dd17bdf933fad437c74d'),
    (0x4469558, 44, '01b10cb8d5d37bb4c58819545a2dc6d6592b00be2c411dd50e27fff0c67687db'),
    (0x19f345c, 136, '9102590af3e5e01941a99395a2205db1d415f7ff98480b00b0de2e4400eb3246'),
    (0x4a8e878, 372, '72f82016468792d460d84bb6a83cf712fc1b9e46324864532d41036dcb100674'),
    (0x4a8eb90, 228, '301780014cd1c3808038f815e76264f2c8e38af0d57c98bc3cd10ff01b8742c5'),
)


GOAL_KICKS_NATIVE_PLUGIN = ROLE_NATIVE_PLUGIN
GOAL_KICKS_ENGLISH_RESOURCE = GOAL_KICKS_NATIVE_PLUGIN.parent.parent / 'Resources/data/game_simulation/templates/user_folder/languages/example.ltf'
GOAL_KICKS_NATIVE_SPANS = (
    (0x54010e4, 792, 'dc072c6bed505968347c2e8f5c83d4db7187231c97f9ad57f02d27099aa1d10a'),
    (0x5400fce, 4, 'b98fb75c938f7125064d237c62cf637edf49766a3ea78263b2e3911da27940a3'),
    (0x4865fc8, 20, '66889992f7d5ee0bbcd0f5da04434337896ab223fa910327d6c4e6b5a0cf3449'),
    (0x4866348, 20, '98ae492f65899ae68e1324422513911f8f3ef7eeeec68570c302e5cf701411f9'),
    (0x44694e8, 112, '10c4d9afee07bc30c2e3923376554490854386df9b82b8809f7ef4554296fcf4'),
    (0x44695d0, 36, '26d1bb0b82ccdc7a0dbc5e7e941e448604c062a5c728dd17bdf933fad437c74d'),
    (0x4469558, 44, '01b10cb8d5d37bb4c58819545a2dc6d6592b00be2c411dd50e27fff0c67687db'),
    (0x19f345c, 136, '9102590af3e5e01941a99395a2205db1d415f7ff98480b00b0de2e4400eb3246'),
    (0x4a8e878, 372, '72f82016468792d460d84bb6a83cf712fc1b9e46324864532d41036dcb100674'),
    (0x4a8eb90, 228, '301780014cd1c3808038f815e76264f2c8e38af0d57c98bc3cd10ff01b8742c5'),
    (0x4a8d728, 312, '437beadc001edff7f1261ca71fa02ee305912f4ba989697394f5ddc9f02c68b4'),
)


CROSSING_NATIVE_PLUGIN = ROLE_NATIVE_PLUGIN
CROSSING_ENGLISH_RESOURCE = CROSSING_NATIVE_PLUGIN.parent.parent / 'Resources/data/game_simulation/templates/user_folder/languages/example.ltf'
CROSSING_NATIVE_SPANS = (
    (0x54010e4, 792, 'dc072c6bed505968347c2e8f5c83d4db7187231c97f9ad57f02d27099aa1d10a'),
    (0x5400f8a, 6, 'c860ea7905d056ac3de44080d485851b55f34304d695800e492a125bda0470b8'),
    (0x48672f0, 20, '4337c74913e729e3a1d448a0fe37ba4a8c52a77fb6d34f630054f9718b01f719'),
    (0x48666c4, 20, 'd3c703e07bdcd21e9ad32fef77dc000826fc5feac9dd77f3dee00e3a2528e6dd'),
    (0x4866bf8, 16, 'cce75e24f7e3ab08570e728fad282d6e90272956bb9ed69bf166dc41c8c0d154'),
    (0x44694e8, 112, '10c4d9afee07bc30c2e3923376554490854386df9b82b8809f7ef4554296fcf4'),
    (0x44695d0, 36, '26d1bb0b82ccdc7a0dbc5e7e941e448604c062a5c728dd17bdf933fad437c74d'),
    (0x4469558, 44, '01b10cb8d5d37bb4c58819545a2dc6d6592b00be2c411dd50e27fff0c67687db'),
    (0x19f345c, 136, '9102590af3e5e01941a99395a2205db1d415f7ff98480b00b0de2e4400eb3246'),
    (0x4a8e878, 372, '72f82016468792d460d84bb6a83cf712fc1b9e46324864532d41036dcb100674'),
    (0x4a8eb90, 228, '301780014cd1c3808038f815e76264f2c8e38af0d57c98bc3cd10ff01b8742c5'),
    (0x4a8d728, 312, '437beadc001edff7f1261ca71fa02ee305912f4ba989697394f5ddc9f02c68b4'),
)


WING_BACK_ENGLISH_RESOURCE = LOSS_ENGLISH_RESOURCE
WING_BACK_RECORD_PREFIX_SHA = '43473e4c28de327b3615cc1eeb6ca8c32870125f7a75068b21b1e55aa2aaaf71'
WING_BACK_NATIVE_SPANS = (
    (0x5394bc, 176, 'ee8bc9a87facf0f2f5472b6ac2e95b4be8f091ccf08bf00320e4ebe414c5ef93'),
    (0x4977508, 140, '362d9d916ce6af350d607c24d1c8ed7293bc735f3694d27800d736b57701b0f4'),
    (0x49771cc, 664, '52a55a3cc173f9efd49055f69a04df50f80c45dea3974edbbccf43f7ed4740f4'),
    (0x4975150, 232, 'be3b1df97a4d179417aa6e84952a076208a3e56ea9b5fc78cbcede02e3e9acc3'),
    (0x49756f0, 32, '7048016b88c97361e3399c05c5e75069c163813f8116817f9edaa82071bfc3ca'),
    (0x4ade568, 660, 'fd5cb2de2e7b332df5b30fdd4045ed8ca4b4136e72da011822ac765d51d7a081'),
    (0x4a8d728, 1132, 'a175d89d31de94f5b14e0cdc898e82be820b3029037fa8fa601b229c67a57c26'),
)

LEFT_WING_BACK_RECORD_PREFIX_SHA = '8e859ae696155c35ff577cd0ce004aa7a4a99d45ac58ffa25f85af5ee68a118d'
INSIDE_FORWARD_RECORD_PREFIX_SHA = 'dc62bd5968ba03ee5eb81a95b23da41de198a17f8aed97678f3abb2a2e910e04'
LEFT_INSIDE_FORWARD_RECORD_PREFIX_SHA = 'b57f66667589542a99e1831a3f5f8915253229d43229c8022c2c90c7a2d45672'
INSIDE_FORWARD_NATIVE_SPANS = (
    (0x539000, 4096, '105d490206b4c74e755521e87c8dd45e8eec2f8659bd6a628db7c620cfefee6a'),
    (0x4973000, 4096, 'e41b81a598083b3778b8e9a50b9c4d7768d391f55395156fad5f0ab94c400f9b'),
    (0x4974000, 4096, 'ca2a368c29218bab2a001a7c9863a529d2ae320cfdc0602a454d6d35adca9db1'),
    (0x4975000, 4096, '7afea19f00597213187e2e4299c48c1c2e41f766cbf7a445acbed9f19fb99bf3'),
    (0x4976000, 4096, '12915dc5e7e16a6aeb07d68b5f2701a2f8435ba2f2fb20fcd6c5ded952bd64e1'),
    (0x4977000, 4096, 'adab3ddd0ea95be6a5e4aaf2bbde7dac163d7d1b7da28936ccc2a1293ecb04c5'),
    (0x5406000, 4096, 'b4afdd9d9929d572afeb3e1c76733ecaa478a5424afd260f79b90423c7063ab4'),
    (0x4ADE568, 660, 'fd5cb2de2e7b332df5b30fdd4045ed8ca4b4136e72da011822ac765d51d7a081'),
)

TRACKING_MIDFIELDER_PREFIXES = {
    8: ('AM(CR)', 2105344, '40c649d5970c7afe8c786415da1258b6a0029905243d78647a7cf7b73bb9014a'),
    9: ('AM(CL)', 1056768, '83bdbe314a1ff392e7b20d884e9faf420ddf92a86393a008329502e519c0d6b5'),
}
TRACKING_MIDFIELDER_NATIVE_SPANS = (
    (0x539000, 4096, '105d490206b4c74e755521e87c8dd45e8eec2f8659bd6a628db7c620cfefee6a'),
    (0x4975000, 4096, '7afea19f00597213187e2e4299c48c1c2e41f766cbf7a445acbed9f19fb99bf3'),
    (0x4977000, 4096, 'adab3ddd0ea95be6a5e4aaf2bbde7dac163d7d1b7da28936ccc2a1293ecb04c5'),
    (0x4ADE568, 660, 'fd5cb2de2e7b332df5b30fdd4045ed8ca4b4136e72da011822ac765d51d7a081'),
)

# Nine observed complete prefixes; every distinct word pair was reproduced by
# the original native setter and reconciliation code in the offline matrix.
# Values are position mask, prefix SHA256, observed words, exact target PI word.
MATRIX_ROLE_CASES = {
    (27, 'in_possession', 5): (2097280, ROLE_RECORD_PREFIX_SHA, (0x410000, 0x200010), 0),
    (27, 'out_of_possession', 4): (32, WING_BACK_RECORD_PREFIX_SHA, (0x402000, 0x201000), 0x80000000),
    (27, 'out_of_possession', 7): (64, LEFT_WING_BACK_RECORD_PREFIX_SHA, (0x402000, 0x201000), 0x80000000),
    (27, 'out_of_possession', 8): (2105344, TRACKING_MIDFIELDER_PREFIXES[8][2], (0x40400000, 0x80200000), 0),
    (27, 'out_of_possession', 9): (1056768, TRACKING_MIDFIELDER_PREFIXES[9][2], (0x40400000, 0x80200000), 0),
    (26, 'in_possession', 7): (2048, INSIDE_FORWARD_RECORD_PREFIX_SHA, (0x400080, 0x8800000), 0x2050000),
    (26, 'in_possession', 9): (4096, LEFT_INSIDE_FORWARD_RECORD_PREFIX_SHA, (0x400080, 0x8800000), 0x2050000),
    (26, 'out_of_possession', 1): (4, 'ea06132001810bfd5b334f5e99dd08832f17987a82b97be3591ca4685d222918', (0x400400, 0x200200, 0x200800), 0x280000000),
    (26, 'out_of_possession', 4): (8, '325eb3d2245e55888b06c170121a2dc01f8fd78e2ce2752dd16bcf42d3d1ecf7', (0x400400, 0x200200, 0x200800), 0x280000000),
}
MATRIX_ROLE_LABELS = {
    ('in_possession', 0x410000): ('Box-To-Box Midfielder', 'Support', 688121, 297464),
    ('in_possession', 0x200010): ('Defensive Midfielder', 'Defend', 688083, 297461),
    ('in_possession', 0x400080): ('Winger', 'Support', 688102, 297464),
    ('in_possession', 0x8800000): ('Inside Forward', 'Attack', 688109, 297465),
    ('out_of_possession', 0x402000): ('Pressing Wing-Back', 'Support', 688082, 297464),
    ('out_of_possession', 0x201000): ('Wing-Back', 'Defend', 688080, 297461),
    ('out_of_possession', 0x40400000): ('Attacking Midfielder', 'Support', 688095, 297464),
    ('out_of_possession', 0x80200000): ('Tracking Attacking Midfielder', 'Defend', 688098, 297461),
    ('out_of_possession', 0x400400): ('Pressing Full-Back', 'Support', 688079, 297464),
    ('out_of_possession', 0x200200): ('Full-Back', 'Defend', 688077, 297461),
    ('out_of_possession', 0x200800): ('Holding Full-Back', 'Defend', 688078, 297461),
}
MATRIX_ROLE_NATIVE_SPANS = INSIDE_FORWARD_NATIVE_SPANS + (
    (0x4A8D728, 1132, 'a175d89d31de94f5b14e0cdc898e82be820b3029037fa8fa601b229c67a57c26'),
)
STORED_ROLE_PI_CANONICAL_SHA = '0904a6cd871a46e8a91463008482d25d66238c86f0fedfe589ede48dcd994e96'
STORED_ROLE_PI_METADATA = ROLE_NATIVE_PLUGIN.parents[4] / 'Resources/data/il2cpp_data/Metadata/global-metadata.dat'
STORED_ROLE_PI_METADATA_SHA = 'ff4780c66f37e088f363d0c4365110dd0d7968204cb36283a6262055badab21d'
STORED_ROLE_PI_NATIVE_SPANS = MATRIX_ROLE_NATIVE_SPANS + (
    (0x4ADE000, 4096, 'a3c7758b6154693a10b0b187a32dc6aa571f72f498ed1dac0bb9376b1e6717f3'),
    (0x4ADF000, 4096, '3cdff7c0027f5dcda744ad0d3cf5ae2c200ac33bfcb341a48ae4f208ac02a142'),
)
STORED_ROLE_PI_OPTIONS = ((24, 'PI_ROAM_FROM_POSITION'), (27, 'PI_MOVE_INTO_CHANNELS'))


PRESSING_BLOCK_NATIVE_PLUGIN = ROLE_NATIVE_PLUGIN
PRESSING_BLOCK_ENGLISH_RESOURCE = PRESSING_BLOCK_NATIVE_PLUGIN.parent.parent / 'Resources/data/game_simulation/templates/user_folder/languages/example.ltf'
PRESSING_BLOCK_NATIVE_SPANS = (
    (0x54010e4, 792, 'dc072c6bed505968347c2e8f5c83d4db7187231c97f9ad57f02d27099aa1d10a'),
    (0x5400ff0, 6, '63ee05530e98734ced8e8f1be8795c767ee91897592dc5fdb56581616e020f7a'),
    (0x4867cf8, 16, '12ab2f24f7b417af7756fefea6b3be41ed27fa434e7926239ef55d8b6dbb01ba'),
    (0x4867e40, 20, '6893c62a9de4958fdb792fa0c0a84e8a63658f3a6b7fd99dbfb67b347ff59af1'),
    (0x48677bc, 20, '09f895da9f43c3fc1d1ff09e2386484f3d90f59efa4439603a3528dd9a559355'),
    (0x44694e8, 112, '10c4d9afee07bc30c2e3923376554490854386df9b82b8809f7ef4554296fcf4'),
    (0x44695d0, 36, '26d1bb0b82ccdc7a0dbc5e7e941e448604c062a5c728dd17bdf933fad437c74d'),
    (0x4469558, 44, '01b10cb8d5d37bb4c58819545a2dc6d6592b00be2c411dd50e27fff0c67687db'),
    (0x19f345c, 136, '9102590af3e5e01941a99395a2205db1d415f7ff98480b00b0de2e4400eb3246'),
    (0x4a8e878, 372, '72f82016468792d460d84bb6a83cf712fc1b9e46324864532d41036dcb100674'),
    (0x4a8eb90, 228, '301780014cd1c3808038f815e76264f2c8e38af0d57c98bc3cd10ff01b8742c5'),
    (0x4a8d728, 312, '437beadc001edff7f1261ca71fa02ee305912f4ba989697394f5ddc9f02c68b4'),
)


FINAL_THIRD_NATIVE_PLUGIN = ROLE_NATIVE_PLUGIN
FINAL_THIRD_ENGLISH_RESOURCE = LOSS_ENGLISH_RESOURCE
FINAL_THIRD_NATIVE_SPANS = (
    (0x54010e4, 792, 'dc072c6bed505968347c2e8f5c83d4db7187231c97f9ad57f02d27099aa1d10a'),
    (0x5400f88, 2, 'd3d5b2e28525aa0fdb9b0f0c0247ad7753ba1fc4fe9e2a870d3ff9b84a551734'),
    (0x4867440, 20, '96cf9c7248d417a80a34d52b21eb85362c095727c66180ef4bb55edb877b2863'),
    (0x5400f98, 2, '7a4f21b2c6b9c69afb76b227f0692b15a0ce64296beb939904780c8534c078b7'),
    (0x4867590, 20, '2626dd3852f27671820e12e2f39eef2b22ef4715d775bd92a415e0dadc9577dc'),
    (0x44694e8, 112, '10c4d9afee07bc30c2e3923376554490854386df9b82b8809f7ef4554296fcf4'),
    (0x44695d0, 36, '26d1bb0b82ccdc7a0dbc5e7e941e448604c062a5c728dd17bdf933fad437c74d'),
    (0x4469558, 44, '01b10cb8d5d37bb4c58819545a2dc6d6592b00be2c411dd50e27fff0c67687db'),
    (0x19f345c, 136, '9102590af3e5e01941a99395a2205db1d415f7ff98480b00b0de2e4400eb3246'),
    (0x4a8e878, 372, '72f82016468792d460d84bb6a83cf712fc1b9e46324864532d41036dcb100674'),
    (0x4a8eb90, 228, '301780014cd1c3808038f815e76264f2c8e38af0d57c98bc3cd10ff01b8742c5'),
    (0x4a8d728, 312, '437beadc001edff7f1261ca71fa02ee305912f4ba989697394f5ddc9f02c68b4'),
)


FOCUS_PLAY_NATIVE_PLUGIN = ROLE_NATIVE_PLUGIN
FOCUS_PLAY_ENGLISH_RESOURCE = LOSS_ENGLISH_RESOURCE
FOCUS_PLAY_NATIVE_SPANS = ((88084708, 792, 'dc072c6bed505968347c2e8f5c83d4db7187231c97f9ad57f02d27099aa1d10a'), (88084384, 8, 'eeb62a8c406de547c229db5b4558b3ec23e92425a45d632f2875ba3867025bf0'), (75921120, 16, '5c66365fbc3b9113e7807a6c41d2e91a9dc13e04c7391d9fc09a0162cc7bd2a3'), (75916440, 20, 'f154b1b019002a3bac8acc3a1de2e464e12b2228f156f3c75ebf87678b5bdc4b'), (75917556, 20, '23070aad7c0e23ac2d9725808a2b1c6d8c8ac6da79d0a6128544d866e6500025'), (75916884, 20, '9cc73da3e76b1b6e801f7a94e3914fd031d75b2e9beeb7667c565cc9b3969a5b'), (71734504, 112, '10c4d9afee07bc30c2e3923376554490854386df9b82b8809f7ef4554296fcf4'), (71734736, 36, '26d1bb0b82ccdc7a0dbc5e7e941e448604c062a5c728dd17bdf933fad437c74d'), (71734616, 44, '01b10cb8d5d37bb4c58819545a2dc6d6592b00be2c411dd50e27fff0c67687db'), (27210844, 136, '9102590af3e5e01941a99395a2205db1d415f7ff98480b00b0de2e4400eb3246'), (78178424, 372, '72f82016468792d460d84bb6a83cf712fc1b9e46324864532d41036dcb100674'), (78179216, 228, '301780014cd1c3808038f815e76264f2c8e38af0d57c98bc3cd10ff01b8742c5'), (78173992, 312, '437beadc001edff7f1261ca71fa02ee305912f4ba989697394f5ddc9f02c68b4'))

WIDE_SUPPORT_NATIVE_PLUGIN = ROLE_NATIVE_PLUGIN
WIDE_SUPPORT_ENGLISH_RESOURCE = LOSS_ENGLISH_RESOURCE
WIDE_SUPPORT_NATIVE_SPANS = ((88084708, 792, 'dc072c6bed505968347c2e8f5c83d4db7187231c97f9ad57f02d27099aa1d10a'), (88084392, 12, 'd0386fa2813cb6531f17fd0833d37752a58c2536776253b37bb3ce9918e151ea'), (75918548, 20, '6461f576aa368d3058d6bb4600b772e64bfbf19e42e81e170c981cc3397d7466'), (75916660, 20, '8ba6ea7b27cf2b95acd1df13a2571a7f26e110d5a96ede4a73f341d315a61d71'), (75921892, 20, 'b779d71ecd307e0f96ee0108d5986e1c5c2adbd0f3d80ce536224b70158a7a17'), (75921784, 16, 'b8ae0d31db3fda2ca8c1ae6f10c41513b13db43b0ad02eedd6e95578e152e939'), (75917332, 20, '170aad7c0ff194cf07a55f436153a5f2df1f66d5d3bce5ce499c514c4a34898f'), (75917996, 20, '325facf14611d00465d0e3cd88dacebe74bbc18094c7c745362b87b87b80e50f'), (71734504, 112, '10c4d9afee07bc30c2e3923376554490854386df9b82b8809f7ef4554296fcf4'), (71734736, 36, '26d1bb0b82ccdc7a0dbc5e7e941e448604c062a5c728dd17bdf933fad437c74d'), (71734616, 44, '01b10cb8d5d37bb4c58819545a2dc6d6592b00be2c411dd50e27fff0c67687db'), (27210844, 136, '9102590af3e5e01941a99395a2205db1d415f7ff98480b00b0de2e4400eb3246'), (78178424, 372, '72f82016468792d460d84bb6a83cf712fc1b9e46324864532d41036dcb100674'), (78179216, 228, '301780014cd1c3808038f815e76264f2c8e38af0d57c98bc3cd10ff01b8742c5'), (78173992, 312, '437beadc001edff7f1261ca71fa02ee305912f4ba989697394f5ddc9f02c68b4'))

def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def verify_base_role_native() -> None:
    with ROLE_NATIVE_PLUGIN.open('rb') as handle:
        for offset, size, expected in ROLE_NATIVE_SPANS:
            handle.seek(0x5ED4000 + offset)
            if sha(handle.read(size)) != expected:
                raise ValueError('Native base-role source changed.')


def verify_possession_loss_native() -> None:
    with LOSS_NATIVE_PLUGIN.open('rb') as handle:
        for offset, size, expected in LOSS_NATIVE_SPANS:
            handle.seek(0x5ED4000 + offset)
            if sha(handle.read(size)) != expected:
                raise ValueError('Native possession-loss source changed.')
    if sha(LOSS_ENGLISH_RESOURCE.read_bytes()) != '3ce742519bf694636f41a1dae8d45a3dab86fad7d164a58696139e4b4509dd43':
        raise ValueError('Native possession-loss English definitions changed.')


def verify_possession_gain_native() -> None:
    with GAIN_NATIVE_PLUGIN.open('rb') as handle:
        for offset, size, expected in GAIN_NATIVE_SPANS:
            handle.seek(0x5ED4000 + offset)
            if sha(handle.read(size)) != expected:
                raise ValueError('Native possession-gain source changed.')
    if sha(GAIN_ENGLISH_RESOURCE.read_bytes()) != '3ce742519bf694636f41a1dae8d45a3dab86fad7d164a58696139e4b4509dd43':
        raise ValueError('Native possession-gain English definitions changed.')


def verify_goal_kicks_native() -> None:
    with GOAL_KICKS_NATIVE_PLUGIN.open('rb') as handle:
        for offset, size, expected in GOAL_KICKS_NATIVE_SPANS:
            handle.seek(0x5ED4000 + offset)
            if sha(handle.read(size)) != expected:
                raise ValueError('Native goal-kick-length source changed.')
    if sha(GOAL_KICKS_ENGLISH_RESOURCE.read_bytes()) != '3ce742519bf694636f41a1dae8d45a3dab86fad7d164a58696139e4b4509dd43':
        raise ValueError('Native goal-kick-length English definitions changed.')


def verify_crossing_native() -> None:
    with CROSSING_NATIVE_PLUGIN.open('rb') as handle:
        for offset, size, expected in CROSSING_NATIVE_SPANS:
            handle.seek(0x5ED4000 + offset)
            if sha(handle.read(size)) != expected:
                raise ValueError('Native crossing-style source changed.')
    if sha(CROSSING_ENGLISH_RESOURCE.read_bytes()) != '3ce742519bf694636f41a1dae8d45a3dab86fad7d164a58696139e4b4509dd43':
        raise ValueError('Native crossing-style English definitions changed.')


def verify_pressing_block_native() -> None:
    with PRESSING_BLOCK_NATIVE_PLUGIN.open('rb') as handle:
        for offset, size, expected in PRESSING_BLOCK_NATIVE_SPANS:
            handle.seek(0x5ED4000 + offset)
            if sha(handle.read(size)) != expected:
                raise ValueError('Native pressing-block source changed.')
    if sha(PRESSING_BLOCK_ENGLISH_RESOURCE.read_bytes()) != ENGLISH_RESOURCE_SHA256:
        raise ValueError('Native pressing-block English definitions changed.')


def verify_final_third_native() -> None:
    with FINAL_THIRD_NATIVE_PLUGIN.open('rb') as handle:
        for offset, size, expected in FINAL_THIRD_NATIVE_SPANS:
            handle.seek(0x5ED4000 + offset)
            if sha(handle.read(size)) != expected:
                raise ValueError('Native final-third-delivery source changed.')
    if sha(FINAL_THIRD_ENGLISH_RESOURCE.read_bytes()) != ENGLISH_RESOURCE_SHA256:
        raise ValueError('Native final-third-delivery English definitions changed.')


def verify_focus_play_native() -> None:
    with FOCUS_PLAY_NATIVE_PLUGIN.open('rb') as handle:
        for offset, size, expected in FOCUS_PLAY_NATIVE_SPANS:
            handle.seek(0x5ED4000 + offset)
            if sha(handle.read(size)) != expected:
                raise ValueError('Native focus-play source changed.')
    if sha(FOCUS_PLAY_ENGLISH_RESOURCE.read_bytes()) != ENGLISH_RESOURCE_SHA256:
        raise ValueError('Native focus-play English definitions changed.')

def verify_wide_support_native() -> None:
    with WIDE_SUPPORT_NATIVE_PLUGIN.open('rb') as handle:
        for offset, size, expected in WIDE_SUPPORT_NATIVE_SPANS:
            handle.seek(0x5ED4000 + offset)
            if sha(handle.read(size)) != expected:
                raise ValueError('Native wide-support source changed.')
    if sha(WIDE_SUPPORT_ENGLISH_RESOURCE.read_bytes()) != ENGLISH_RESOURCE_SHA256:
        raise ValueError('Native wide-support English definitions changed.')



def phase_records(tac: bytes) -> dict:
    first = parse_tac_plaintext(tac).get('tactical_style', {}).get('end_exclusive')
    if type(first) is not int:
        raise ValueError('Unsupported native position record boundary.')
    return decode_position_records(tac, first + 4)['phases']


def validate_base_role_records(tac: bytes, donor_tac: bytes) -> tuple[int, bytes]:
    """Validate only the independently proved FM27 IP slot5 stored record case."""
    if tac[11] != 27 or donor_tac[11] != 27:
        raise ValueError('Base-role editing requires native FM27 source and donor.')
    source = phase_records(tac)['in_possession'][5]
    donor = phase_records(donor_tac)['in_possession'][5]
    if source['position_mask'] != 2097280 or donor['position_mask'] != 2097280:
        raise ValueError('Base-role editing requires IP slot5 DM(CR).')
    if source['native_role_word'] != '0000000000410000' or donor['native_role_word'] != '0000000000200010':
        raise ValueError('Unsupported source or donor base role.')
    for word, role, fixed, key, fixed_key in [(0x410000, 'Box-To-Box Midfielder', 'Support', 688121, 297464),
                                              (0x200010, 'Defensive Midfielder', 'Defend', 688083, 297461)]:
        if word_label_binding(word, 'in_possession') != (role, fixed, key, fixed_key):
            raise ValueError('Native base-role label bindings changed.')
    prefix = tac[source['record_offset']:source['role_word_offset']]
    donor_prefix = donor_tac[donor['record_offset']:donor['role_word_offset']]
    if prefix != donor_prefix:
        raise ValueError('Base-role companion record bytes differ.')
    keys, target_bits = [], []
    for index in range(source['instruction_entry_count']):
        at = source['instruction_vector_offset'] + 24 * index
        if tac[at + 8:at + 11] != b'\x02\x02\x02':
            raise ValueError('Unsupported stored role instruction metadata.')
        key = struct.unpack_from('<Q', tac, at)[0]
        keys.append(key)
        if key == 0x10:
            target_bits.append(struct.unpack_from('<Q', tac, at + 11)[0])
    if (any(key != (key & 0xFFFBFFFFF91FFFFF) for key in keys)
            or any(left >= right for left, right in zip(keys, keys[1:])) or target_bits != [0]):
        raise ValueError('Base-role target key must be normalized, sorted, unique, present and have zero instruction bits.')
    if sha(prefix) != ROLE_RECORD_PREFIX_SHA:
        raise ValueError('Unsupported base-role companion prefix.')
    #539184..1A8 replaces the IP name mask; the exact4977470 branch sets
    #fixed bit21.4976FCC then takes4977174 because the existing target PI word is0.
    mask = 0x03FB7B49A90FDEFF
    switched = (0x410000 & ~mask) | (0x200010 & mask)
    if switched & 0xFFC7EFE1C81FBFEC or switched & (1 << 21):
        raise ValueError('Unsupported native base-role normalization branch.')
    normalized = (switched & 0xFFFBFFFFF91FFFFF) | (1 << 21)
    word = normalized.to_bytes(8, 'little')
    if normalized != 0x200010 or prefix + word != donor_tac[donor['record_offset']:donor['record_end_exclusive']]:
        raise ValueError('Native base-role normalization does not reproduce donor record.')
    return source['role_word_offset'], word


def verify_wing_back_native() -> None:
    with ROLE_NATIVE_PLUGIN.open('rb') as handle:
        for offset, size, expected in WING_BACK_NATIVE_SPANS:
            handle.seek(0x5ED4000 + offset)
            if sha(handle.read(size)) != expected:
                raise ValueError('Native OOP wing-back source changed.')
    if sha(WING_BACK_ENGLISH_RESOURCE.read_bytes()) != ENGLISH_RESOURCE_SHA256:
        raise ValueError('Native OOP wing-back English definitions changed.')


def validate_wing_back_records(tac: bytes, donor_tac: bytes, slot: int = 4) -> tuple[int, bytes]:
    """Exact native-format27 OOP WB(R/L), Pressing Wing-Back to Wing-Back."""
    cases = {4: ('WB(R)', 32, WING_BACK_RECORD_PREFIX_SHA),
             7: ('WB(L)', 64, LEFT_WING_BACK_RECORD_PREFIX_SHA)}
    if slot not in cases:
        raise ValueError('Wing-back editing requires OOP slot4 or slot7.')
    position, mask, prefix_sha = cases[slot]
    if tac[11] != 27 or donor_tac[11] != 27:
        raise ValueError('Base-role editing requires native FM27 source and donor.')
    source = phase_records(tac)['out_of_possession'][slot]
    donor = phase_records(donor_tac)['out_of_possession'][slot]
    if source['position_mask'] != mask or donor['position_mask'] != mask:
        raise ValueError(f'Base-role editing requires OOP slot{slot} {position}.')
    if source['native_role_word'] != '0000000000402000' or donor['native_role_word'] != '0000000000201000':
        raise ValueError('Unsupported OOP wing-back source or donor role.')
    for word, role, fixed, key, fixed_key in [(0x402000, 'Pressing Wing-Back', 'Support', 688082, 297464),
                                              (0x201000, 'Wing-Back', 'Defend', 688080, 297461)]:
        if word_label_binding(word, 'out_of_possession') != (role, fixed, key, fixed_key):
            raise ValueError('Native OOP wing-back label bindings changed.')
    prefix = tac[source['record_offset']:source['role_word_offset']]
    donor_prefix = donor_tac[donor['record_offset']:donor['role_word_offset']]
    if prefix != donor_prefix:
        raise ValueError('OOP wing-back companion record bytes differ.')
    keys, target_bits = [], []
    for index in range(source['instruction_entry_count']):
        at = source['instruction_vector_offset'] + 24 * index
        if tac[at + 8:at + 11] != b'\x02\x02\x02':
            raise ValueError('Unsupported OOP wing-back instruction metadata.')
        key = struct.unpack_from('<Q', tac, at)[0]
        keys.append(key)
        if key == 0x1000:
            target_bits.append(struct.unpack_from('<Q', tac, at + 11)[0])
    if (any(key != (key & 0xFFFBFFFFF91FFFFF) for key in keys)
            or any(left >= right for left, right in zip(keys, keys[1:])) or target_bits != [0x80000000]):
        raise ValueError('OOP wing-back target key must be normalized, sorted, unique, present and have exact PI bit31.')
    if sha(prefix) != prefix_sha:
        raise ValueError('Unsupported OOP wing-back companion prefix.')
    #539508..548 replaces the OOP name mask, sets fixed bit21 through4977508,
    #then reconciles through49771CC. Target PI31 takes4975150's unconditional
    #state0/true branch; no insertion or instruction-bit clear occurs.
    mask = 0x00003FFBF81FFFFF
    switched = (0x402000 & ~mask) | (0x201000 & mask)
    if switched & 0xFFFFF76B69122403 or switched & (1 << 21):
        raise ValueError('Unsupported native OOP wing-back normalization branch.')
    normalized = (switched & 0xFFFBFFFFF91FFFFF) | (1 << 21)
    word = normalized.to_bytes(8, 'little')
    if normalized != 0x201000 or prefix + word != donor_tac[donor['record_offset']:donor['record_end_exclusive']]:
        raise ValueError('Native OOP wing-back normalization does not reproduce donor record.')
    return source['role_word_offset'], word


def verify_inside_forward_native() -> None:
    with ROLE_NATIVE_PLUGIN.open('rb') as handle:
        for offset, size, expected in INSIDE_FORWARD_NATIVE_SPANS:
            handle.seek(0x5ED4000 + offset)
            if sha(handle.read(size)) != expected:
                raise ValueError('Native inside-forward source changed.')
    if sha(LOSS_ENGLISH_RESOURCE.read_bytes()) != ENGLISH_RESOURCE_SHA256:
        raise ValueError('Native inside-forward English definitions changed.')


def validate_inside_forward_records(tac: bytes, donor_tac: bytes, slot: int = 7) -> tuple[int, bytes]:
    """Exact v68/source-format26 IP AM(R/L) Winger to Inside Forward."""
    cases = {7: ('AM(R)', 2048, INSIDE_FORWARD_RECORD_PREFIX_SHA),
             9: ('AM(L)', 4096, LEFT_INSIDE_FORWARD_RECORD_PREFIX_SHA)}
    if slot not in cases:
        raise ValueError('Inside-forward editing requires IP slot7 or slot9.')
    position, position_mask, prefix_sha = cases[slot]
    if tac[11] != 26 or donor_tac[11] != 26:
        raise ValueError('Inside-forward editing requires source-format26 source and donor.')
    source = phase_records(tac)['in_possession'][slot]
    donor = phase_records(donor_tac)['in_possession'][slot]
    if source['position_mask'] != position_mask or donor['position_mask'] != position_mask:
        raise ValueError(f'Inside-forward editing requires IP slot{slot} {position}.')
    if source['native_role_word'] != '0000000000400080' or donor['native_role_word'] != '0000000008800000':
        raise ValueError(f'Unsupported {position} source or donor role.')
    for word, role, fixed, key, fixed_key in [
            (0x400080, 'Winger', 'Support', 688102, 297464),
            (0x8800000, 'Inside Forward', 'Attack', 688109, 297465)]:
        if word_label_binding(word, 'in_possession') != (role, fixed, key, fixed_key):
            raise ValueError('Native inside-forward label bindings changed.')
    prefix = tac[source['record_offset']:source['role_word_offset']]
    donor_prefix = donor_tac[donor['record_offset']:donor['role_word_offset']]
    if prefix != donor_prefix:
        raise ValueError('Inside-forward companion record bytes differ.')
    keys, target_bits = [], []
    for index in range(source['instruction_entry_count']):
        at = source['instruction_vector_offset'] + 24 * index
        if tac[at + 8:at + 11] != b'\x02\x02\x02':
            raise ValueError('Unsupported inside-forward instruction metadata.')
        key = struct.unpack_from('<Q', tac, at)[0]
        keys.append(key)
        if key == 0x8000000:
            target_bits.append(struct.unpack_from('<Q', tac, at + 11)[0])
    if (any(key != (key & 0xFFFBFFFFF91FFFFF) for key in keys)
            or any(left >= right for left, right in zip(keys, keys[1:])) or target_bits != [0x2050000]):
        raise ValueError('Inside-forward target key must be normalized, sorted, unique, present and have exact PI bits16/18/25.')
    if sha(prefix) != prefix_sha:
        raise ValueError('Unsupported inside-forward companion prefix.')
    # Original 0x539184..1C8 switches the name; 0x4977470 sets fixed bit23.
    # Reconciliation at 0x4976F28 preserves bits16/18/25 via full 0x4973360 checks.
    switched = (0x400080 & ~0x03FB7B49A90FDEFF) | (0x8800000 & 0x03FB7B49A90FDEFF)
    if (switched != 0x8400000 or not switched & 0xFFC7EFE1C81FBFEC
            or switched & 0xFEBF589A7101F1FF or not switched & 0xFD78B77BB91E6F13):
        raise ValueError('Unsupported native inside-forward word-normalization branch.')
    normalized = (switched & 0xFFFBFFFFF91FFFFF) | (1 << 23)
    word = normalized.to_bytes(8, 'little')
    if normalized != 0x8800000 or prefix + word != donor_tac[donor['record_offset']:donor['record_end_exclusive']]:
        raise ValueError('Native inside-forward normalization does not reproduce donor record.')
    return source['role_word_offset'], word


def verify_tracking_midfielder_native() -> None:
    with ROLE_NATIVE_PLUGIN.open('rb') as handle:
        for offset, size, expected in TRACKING_MIDFIELDER_NATIVE_SPANS:
            handle.seek(0x5ED4000 + offset)
            if sha(handle.read(size)) != expected:
                raise ValueError('Native tracking-midfielder source changed.')
    if sha(LOSS_ENGLISH_RESOURCE.read_bytes()) != ENGLISH_RESOURCE_SHA256:
        raise ValueError('Native tracking-midfielder English definitions changed.')


def validate_tracking_midfielder_records(tac: bytes, donor_tac: bytes, slot: int) -> tuple[int, bytes]:
    if slot not in TRACKING_MIDFIELDER_PREFIXES:
        raise ValueError('Tracking-midfielder editing requires OOP slot8 or slot9.')
    position, mask, prefix_sha = TRACKING_MIDFIELDER_PREFIXES[slot]
    if tac[11] != 27 or donor_tac[11] != 27:
        raise ValueError('Tracking-midfielder editing requires source-format27 source and donor.')
    source = phase_records(tac)['out_of_possession'][slot]
    donor = phase_records(donor_tac)['out_of_possession'][slot]
    if source['position_mask'] != mask or donor['position_mask'] != mask:
        raise ValueError(f'Tracking-midfielder editing requires OOP slot{slot} {position}.')
    if source['native_role_word'] != '0000000040400000' or donor['native_role_word'] != '0000000080200000':
        raise ValueError('Unsupported tracking-midfielder source or donor role.')
    for word, role, fixed, key, fixed_key in [(0x40400000, 'Attacking Midfielder', 'Support', 688095, 297464),
                                              (0x80200000, 'Tracking Attacking Midfielder', 'Defend', 688098, 297461)]:
        if word_label_binding(word, 'out_of_possession') != (role, fixed, key, fixed_key):
            raise ValueError('Native tracking-midfielder label bindings changed.')
    prefix = tac[source['record_offset']:source['role_word_offset']]
    donor_prefix = donor_tac[donor['record_offset']:donor['role_word_offset']]
    if prefix != donor_prefix:
        raise ValueError('Tracking-midfielder companion record bytes differ.')
    keys, target_bits = [], []
    for index in range(source['instruction_entry_count']):
        at = source['instruction_vector_offset'] + 24 * index
        if tac[at + 8:at + 11] != b'\x02\x02\x02':
            raise ValueError('Unsupported tracking-midfielder instruction metadata.')
        key = struct.unpack_from('<Q', tac, at)[0]
        keys.append(key)
        if key == 0x80000000:
            target_bits.append(struct.unpack_from('<Q', tac, at + 11)[0])
    if (any(key != (key & 0xFFFBFFFFF91FFFFF) for key in keys)
            or any(left >= right for left, right in zip(keys, keys[1:])) or target_bits != [0]):
        raise ValueError('Tracking-midfielder target key must be normalized, sorted, unique, present and have zero instruction bits.')
    if sha(prefix) != prefix_sha:
        raise ValueError('Unsupported tracking-midfielder companion prefix.')
    switched = (0x40400000 & ~0x00003FFBF81FFFFF) | (0x80200000 & 0x00003FFBF81FFFFF)
    if switched != 0x80400000 or switched & 0xFFFFF76B69122403 or switched & (1 << 21):
        raise ValueError('Unsupported native tracking-midfielder word-normalization branch.')
    normalized = (switched & 0xFFFBFFFFF91FFFFF) | (1 << 21)
    word = normalized.to_bytes(8, 'little')
    if normalized != 0x80200000 or prefix + word != donor_tac[donor['record_offset']:donor['record_end_exclusive']]:
        raise ValueError('Native tracking-midfielder normalization does not reproduce donor record.')
    return source['role_word_offset'], word


def verify_matrix_role_native() -> None:
    with ROLE_NATIVE_PLUGIN.open('rb') as handle:
        for offset, size, expected in MATRIX_ROLE_NATIVE_SPANS:
            handle.seek(0x5ED4000 + offset)
            if sha(handle.read(size)) != expected:
                raise ValueError('Native role-matrix source changed.')
    if sha(LOSS_ENGLISH_RESOURCE.read_bytes()) != ENGLISH_RESOURCE_SHA256:
        raise ValueError('Native role-matrix English definitions changed.')


def validate_matrix_role_records(tac: bytes, donor_tac: bytes, phase: str, slot: int) -> tuple[int, bytes, dict]:
    case = MATRIX_ROLE_CASES.get((tac[11], phase, slot))
    if case is None or donor_tac[11] != tac[11]:
        raise ValueError('Unsupported role-matrix source or donor format/phase/position.')
    mask, prefix_sha, words, pi_bits = case
    source, donor = phase_records(tac)[phase][slot], phase_records(donor_tac)[phase][slot]
    if source['position_mask'] != mask or donor['position_mask'] != mask:
        raise ValueError('Unsupported role-matrix source or donor position mask.')
    before_word, after_word = int(source['native_role_word'], 16), int(donor['native_role_word'], 16)
    if before_word not in words or after_word not in words or before_word == after_word:
        raise ValueError('Unsupported source or donor base role; no-op role edits are refused.')
    labels = []
    for word in (before_word, after_word):
        role, fixed, key, fixed_key = MATRIX_ROLE_LABELS[(phase, word)]
        if word_label_binding(word, phase) != (role, fixed, key, fixed_key):
            raise ValueError('Native role-matrix label bindings changed.')
        labels.append({'role': role, 'native_role_word': f'{word:016x}'})
    prefix = tac[source['record_offset']:source['role_word_offset']]
    if prefix != donor_tac[donor['record_offset']:donor['role_word_offset']]:
        raise ValueError('Role-matrix companion record bytes differ.')
    target = after_word & 0xFFFBFFFFF91FFFFF
    keys, target_bits = [], []
    for index in range(source['instruction_entry_count']):
        at = source['instruction_vector_offset'] + 24 * index
        if tac[at + 8:at + 11] != b'\x02\x02\x02':
            raise ValueError('Unsupported role-matrix instruction metadata.')
        key = struct.unpack_from('<Q', tac, at)[0]
        keys.append(key)
        if key == target:
            target_bits.append(struct.unpack_from('<Q', tac, at + 11)[0])
    if (any(key != (key & 0xFFFBFFFFF91FFFFF) for key in keys)
            or any(left >= right for left, right in zip(keys, keys[1:])) or target_bits != [pi_bits]):
        raise ValueError('Role-matrix target key must be normalized, sorted, unique, present and have exact proved PI bits.')
    if sha(prefix) != prefix_sha:
        raise ValueError('Unsupported role-matrix complete companion prefix.')
    word = after_word.to_bytes(8, 'little')
    if prefix + word != donor_tac[donor['record_offset']:donor['record_end_exclusive']]:
        raise ValueError('Role-matrix edit does not reproduce the complete donor record.')
    return source['role_word_offset'], word, {'position': source['position_name'], 'before': labels[0], 'after': labels[1]}


PHASE_POSITION_NATIVE_SPANS = (
    (0x4857000, 4096, '7472ce9c8c1bdf09e788e409151d1b9a28ccb30821c2fd8efeaf85a6e4526cd4'),
    (0x491d000, 4096, '6ef6e310299447f4b2027202c48b3d4ed06cc9506b6c56a9599f2d152e51a437'),
    (0x4976000, 4096, '12915dc5e7e16a6aeb07d68b5f2701a2f8435ba2f2fb20fcd6c5ded952bd64e1'),
    (0x4978000, 4096, 'e677ca0d88d26db9344cb77683803b93ef88552149ebe3bdf716312ae85b0e30'),
    (0x4979000, 4096, 'a616bd5d0a746c56689088ef43fc82420bef3ec5cd289944712e96bd3f31eb22'),
    (0x497a000, 4096, '2969ef009e7541e6b1683abda3d1209dc1b90d203d2d62a6176bc4134e5ad072'),
    (0x4acf000, 4096, '6d548e250ae063f81cf78bf3f08a629e2e39976fd5a04519f8de7b1e865b3e62'),
    (0x4ade000, 4096, 'a3c7758b6154693a10b0b187a32dc6aa571f72f498ed1dac0bb9376b1e6717f3'),
    (0x5404000, 4096, '521249a8d3892652ad674fa1930e824551c2cfd3c87b9d0e3f6b6827216707ab'),
    (0x5406000, 4096, 'b4afdd9d9929d572afeb3e1c76733ecaa478a5424afd260f79b90423c7063ab4'),
    (0x4a8d728, 1132, 'a175d89d31de94f5b14e0cdc898e82be820b3029037fa8fa601b229c67a57c26'),
)
PHASE_POSITION_CASES = {
    (27, 4): (32, 4, '351d787e06ca2888d64051c23b58157ba57560c394c41aa32622673980cc5aa6', 'dd5e25233c44895d9c1df3b3f4ea7e58100a06884f75b8c75cfa1e7538c13cb7',
        ('0d8ecdeb8d5b14d23670cc77739f907e7dccad6ce62e5ff5e425f79ac7b6046d', '5f419a52e42e6ddfffc4c8ed9a99c394218060a793e61ce52c14648c83620946')),
    (27, 7): (64, 8, 'c994961c287e64993aabd0f2dbec210ffdf631dfbb789faabb61dcf7bbc3da45', '65b0103faed9186e6c7d8d4013258904cb2813af45a8ecd3faaa06d7b5f311a0',
        ('0d8ecdeb8d5b14d23670cc77739f907e7dccad6ce62e5ff5e425f79ac7b6046d', 'cc546f36612ffbfb81982d4fb0c7773773fa86176db8ea507ffadb2b7e21747f')),
    (26, 7): (256, 2048, 'fe4f61fb352004512063cc8170dc6aa2cb50817b52fe0863b0fb7d5cf7111777', '09d7e8c4b25db687cc6054d9d9a60a4a484e300b0fb05f1e153ab6764f8318f4',
        ('874907c458bae5a73ae0e4c2b557987225cde20905f30f165d4fae13c3df4d5d', 'bc639b537ffa9c02d3dd21bb19e95a283ec76479570be0d80dd3d52940e60cb9')),
    (26, 8): (512, 4096, '74e1b2a2400c3b82d7aab8c83f90941984125787b3409a1881d7f7b75bc529d1', 'f362edd638eefab8872b4e538ad19e2e77b41bb932831b57fd9aea9d2f39dedf',
        ('874907c458bae5a73ae0e4c2b557987225cde20905f30f165d4fae13c3df4d5d', 'fbb90911e34d4e821d7156ce88a39504c89b08366426298f4ed9eedf186db983')),
}


def verify_stored_role_pi_native() -> None:
    with ROLE_NATIVE_PLUGIN.open('rb') as handle:
        for offset, size, expected in STORED_ROLE_PI_NATIVE_SPANS:
            handle.seek(0x5ED4000 + offset)
            if sha(handle.read(size)) != expected:
                raise ValueError('Native stored-role instruction source changed.')
    if sha(LOSS_ENGLISH_RESOURCE.read_bytes()) != ENGLISH_RESOURCE_SHA256:
        raise ValueError('Native stored-role instruction English definitions changed.')
    if sha(STORED_ROLE_PI_METADATA.read_bytes()) != STORED_ROLE_PI_METADATA_SHA:
        raise ValueError('Native stored-role instruction enum metadata changed.')


def stored_role_pi_record(tac: bytes) -> tuple[dict, int, int]:
    """Only the two observed IP9 AM(CL) Attacking Midfielder profiles."""
    if tac[11] != 27:
        raise ValueError('Stored-role instruction editing requires native-format27 source and donor.')
    record = phase_records(tac)['in_possession'][9]
    if record['position_mask'] != 1056768 or record['native_role_word'] != '0000000000800200':
        raise ValueError('Stored-role instruction editing requires IP slot9 AM(CL), Attacking Midfielder.')
    if word_label_binding(0x800200, 'in_possession') != ('Attacking Midfielder', 'Attack', 688095, 297465):
        raise ValueError('Native stored-role instruction role label binding changed.')
    keys, matches = [], []
    for index in range(record['instruction_entry_count']):
        at = record['instruction_vector_offset'] + 24 * index
        if tac[at + 8:at + 11] != b'\x02\x02\x02':
            raise ValueError('Unsupported stored-role instruction metadata.')
        key = struct.unpack_from('<Q', tac, at)[0]
        keys.append(key)
        if key == 0x200:
            matches.append(at + 11)
    if (any(key != (key & 0xFFFBFFFFF91FFFFF) for key in keys)
            or any(left >= right for left, right in zip(keys, keys[1:])) or len(matches) != 1):
        raise ValueError('Stored-role instruction key must be normalized, sorted, unique and present.')
    offset = matches[0]
    bits = struct.unpack_from('<Q', tac, offset)[0]
    if bits not in (0, 0x9000000):
        raise ValueError('Unsupported stored-role instruction selection; only the two proved profiles are supported.')
    canonical = bytearray(tac[record['record_offset']:record['record_end_exclusive']])
    struct.pack_into('<Q', canonical, offset - record['record_offset'], 0)
    if sha(bytes(canonical)) != STORED_ROLE_PI_CANONICAL_SHA:
        raise ValueError('Unsupported stored-role instruction complete companion record.')
    return record, offset, bits


def describe_stored_role_instructions(tac: bytes) -> dict:
    try:
        _, _, bits = stored_role_pi_record(tac)
    except ValueError:
        return {'stored_role_instructions_eligibility': 'unsupported_source_record', 'stored_role_instructions_cases': []}
    return {'stored_role_instructions_eligibility': 'requires_matching_inspected_donor_and_native_checks',
            'stored_role_instructions_cases': [{'phase': 'in_possession', 'position_index': 9, 'position': 'AM(CL)',
                                                'role': 'Attacking Midfielder',
                                                'selected_native_option_ids': [index for index, _ in STORED_ROLE_PI_OPTIONS if bits & (1 << index)]}]}


def prepare_stored_role_instructions(tac: bytes, request: object) -> tuple[bytes, dict, Path, bytes]:
    required = {'phase', 'position_index', 'donor_template_path', 'donor_template_sha256', 'donor_position_index'}
    if type(request) is not dict or set(request) != required:
        raise ValueError('stored_role_instructions requires the exact phase, position and pinned donor fields.')
    if (type(request['phase']) is not str or type(request['position_index']) is not int
            or type(request['donor_position_index']) is not int
            or (request['phase'], request['position_index'], request['donor_position_index']) != ('in_possession', 9, 9)):
        raise ValueError('Stored-role instruction editing supports only in_possession slot9 and donor slot9.')
    if type(request['donor_template_path']) is not str or not request['donor_template_path']:
        raise ValueError('Stored-role instruction donor must be an inspected native template path.')
    donor_path, donor_bytes, donor_members = read_template(request['donor_template_path'])
    if type(request['donor_template_sha256']) is not str or request['donor_template_sha256'] != sha(donor_bytes):
        raise ValueError('Stored-role instruction donor hash changed or missing; inspect it again.')
    verify_stored_role_pi_native()
    source_record, offset, before = stored_role_pi_record(tac)
    donor_record, _, after = stored_role_pi_record(donor_members['.tac'])
    if before == after:
        raise ValueError('Stored-role instruction edit is a no-op; choose a donor with the other proved profile.')
    changed = tac[:offset] + after.to_bytes(8, 'little') + tac[offset + 8:]
    if changed[source_record['record_offset']:source_record['record_end_exclusive']] != donor_members['.tac'][donor_record['record_offset']:donor_record['record_end_exclusive']]:
        raise ValueError('Stored-role instruction edit does not reproduce the complete donor record.')
    def profile(bits):
        return {'native_bits': f'{bits:016x}', 'selected_native_options': [
            {'native_id': index, 'native_symbol': symbol} for index, symbol in STORED_ROLE_PI_OPTIONS if bits & (1 << index)]}
    return changed, {'phase': 'in_possession', 'position_index': 9, 'position': 'AM(CL)',
                     'role': 'Attacking Midfielder', 'native_role_word': '0000000000800200',
                     'before': profile(before), 'after': profile(after),
                     'donor_template_path': str(donor_path), 'donor_template_sha256': sha(donor_bytes),
                     'scope': 'Exact stored base-role instruction record reproduction; personal overrides, role-derived selections, effective instructions and game import are unverified.'}, donor_path, donor_bytes


def verify_phase_position_native() -> None:
    with ROLE_NATIVE_PLUGIN.open('rb') as handle:
        for offset, size, expected in PHASE_POSITION_NATIVE_SPANS:
            handle.seek(0x5ED4000 + offset)
            if sha(handle.read(size)) != expected:
                raise ValueError('Native phase-position source changed.')
    if sha(LOSS_ENGLISH_RESOURCE.read_bytes()) != ENGLISH_RESOURCE_SHA256:
        raise ValueError('Native phase-position English definitions changed.')
    for word, name, key, fixed, fixed_key in [(0x201000, 'Wing-Back', 688080, 'Defend', 297461), (0x200200, 'Full-Back', 688077, 'Defend', 297461), (0x1000200000, 'Tracking Wide Midfielder', 688092, 'Defend', 297461), (0x4000400000, 'Winger', 688102, 'Support', 297464)]:
        if word_label_binding(word, 'out_of_possession') != (name, fixed, key, fixed_key):
            raise ValueError('Native phase-position role label binding changed.')


def phase_position_source_cases(tac: bytes) -> tuple[list[dict], str]:
    if tac[11] not in (26, 27):
        raise ValueError('Phase-position editing requires source-format26 or27 and a same-format donor.')
    records = phase_records(tac)['out_of_possession']
    digest = sha(b''.join(tac[r['record_offset']:r['record_end_exclusive']] for r in records))
    cases = []
    for (major, slot), (before, after, source_sha, _, phases) in PHASE_POSITION_CASES.items():
        if major != tac[11]:
            continue
        record = records[slot]
        if digest in phases and record['position_mask'] == before and sha(tac[record['record_offset']:record['record_end_exclusive']]) == source_sha:
            cases.append({'phase': 'out_of_possession', 'position_index': slot,
                          'before_position': record['position_name'], 'after_position': {4: 'D(R)', 8: 'D(L)', 2048: 'AM(R)', 4096: 'AM(L)'}[after]})
    return cases, digest


def describe_phase_position(tac: bytes) -> dict:
    try:
        cases, _ = phase_position_source_cases(tac)
    except ValueError:
        cases = []
    return {'phase_position_eligibility': 'requires_matching_inspected_donor_and_native_checks' if cases else 'unsupported_source_phase',
            'phase_position_cases': cases}


def prepare_phase_position(tac: bytes, request: object) -> tuple[bytes, dict, Path, bytes]:
    required = {'phase', 'position_index', 'donor_template_path', 'donor_template_sha256', 'donor_position_index'}
    if type(request) is not dict or set(request) != required:
        raise ValueError('phase_position requires the exact phase, position and pinned donor fields.')
    if (request['phase'] != 'out_of_possession' or type(request['position_index']) is not int
            or type(request['donor_position_index']) is not int or (tac[11], request['position_index']) not in PHASE_POSITION_CASES
            or request['donor_position_index'] != request['position_index']):
        raise ValueError('Phase-position editing supports only source-format27 OOP slot4/7 or source-format26 OOP slot7/8 and the same donor slot.')
    if type(request['donor_template_path']) is not str or not request['donor_template_path']:
        raise ValueError('Phase-position donor must be an inspected native template path.')
    donor_path, donor_bytes, members = read_template(request['donor_template_path'])
    if type(request['donor_template_sha256']) is not str or request['donor_template_sha256'] != sha(donor_bytes):
        raise ValueError('Phase-position donor hash changed or missing; inspect it again.')
    verify_phase_position_native()
    cases, digest = phase_position_source_cases(tac)
    slot = request['position_index']
    if not any(case['position_index'] == slot for case in cases):
        raise ValueError('Unsupported phase-position source: all eleven OOP records must match a proved complete phase; no-op and unproved configurations refuse.')
    if members['.tac'][11] != tac[11]:
        raise ValueError('Phase-position editing requires source and donor in the same native format.')
    source = phase_records(tac)['out_of_possession'][slot]
    donor = phase_records(members['.tac'])['out_of_possession'][slot]
    _, after_mask, _, expected_sha, _ = PHASE_POSITION_CASES[tac[11], slot]
    donor_raw = members['.tac'][donor['record_offset']:donor['record_end_exclusive']]
    if donor['position_mask'] != after_mask or sha(donor_raw) != expected_sha:
        raise ValueError('Unsupported phase-position complete donor record; requires the exact proved position, role and instruction record.')
    if len(donor_raw) != source['record_end_exclusive'] - source['record_offset']:
        raise ValueError('Unsupported phase-position record length.')
    changed = tac[:source['record_offset']] + donor_raw + tac[source['record_end_exclusive']:]
    def profile(record):
        return {'position': record['position_name'], 'position_mask': record['position_mask'],
                'role': record['role']['compiled_english_name'],
                'native_role_word': record['native_role_word']}
    return changed, {'phase': 'out_of_possession', 'position_index': slot, 'source_game_major': tac[11], 'before': profile(source), 'after': profile(donor),
                     'source_OOP_phase_sha256': digest, 'donor_template_path': str(donor_path), 'donor_template_sha256': sha(donor_bytes),
                     'scope': 'Exact stored phase-position/role/instruction record reproduced by the original native creator setter and serializer offline. Other phase configurations, personal overrides, full UI parity, effective behavior and game import remain unverified.'}, donor_path, donor_bytes


def describe_base_role_source(tac: bytes) -> dict:
    records = phase_records(tac)
    cases = []
    for (major, phase, slot), (mask, prefix_sha, words, _) in MATRIX_ROLE_CASES.items():
        record = records[phase][slot]
        if (tac[11] == major and record['position_mask'] == mask
                and int(record['native_role_word'], 16) in words
                and sha(tac[record['record_offset']:record['role_word_offset']]) == prefix_sha):
            cases.append({'phase': phase, 'position_index': slot, 'position': record['position_name']})
    return {'base_role_eligibility': 'requires_matching_inspected_donor_and_native_checks' if cases else 'unsupported_source_record',
            'base_role_cases': cases}


def prepare_base_role(tac: bytes, request: object) -> tuple[bytes, dict, Path, bytes]:
    required = {'phase', 'position_index', 'donor_template_path', 'donor_template_sha256', 'donor_position_index'}
    if type(request) is not dict or set(request) != required:
        raise ValueError('base_role requires the exact phase, position and pinned donor fields.')
    if (type(request['phase']) is not str or type(request['position_index']) is not int
            or type(request['donor_position_index']) is not int
            or (request['phase'], request['position_index'], request['donor_position_index']) not in
                [('in_possession', 5, 5), ('out_of_possession', 4, 4), ('out_of_possession', 7, 7), ('in_possession', 7, 7), ('in_possession', 9, 9),
                 ('out_of_possession', 8, 8), ('out_of_possession', 9, 9), ('out_of_possession', 1, 1)]):
        raise ValueError('Base-role editing supports only in_possession slot5 and donor slot5, in_possession slots7/9 and matching donors, or out_of_possession slots1/4/7/8/9 and matching donors, within the exact inspected source-format/position cases.')
    if type(request['donor_template_path']) is not str or not request['donor_template_path']:
        raise ValueError('Base-role donor must be an inspected native template path.')
    donor_path, donor_bytes, donor_members = read_template(request['donor_template_path'])
    if type(request['donor_template_sha256']) is not str or request['donor_template_sha256'] != sha(donor_bytes):
        raise ValueError('Base-role donor hash changed or missing. Inspect the donor again before generating.')
    phase = request['phase']
    slot = request['position_index']
    case = MATRIX_ROLE_CASES.get((tac[11], phase, slot))
    source_record = phase_records(tac)[phase][slot]
    source_word = int(source_record['native_role_word'], 16)
    # Preserve the original seven directed validators and their refusal controls.
    # The finite matrix adds their reverse directions and the observed full-backs.
    is_full_back = tac[11] == 26 and phase == 'out_of_possession' and source_record['position_mask'] in (4, 8)
    is_reverse = case is not None and source_word in case[2] and source_word != case[2][0]
    if (phase, slot) == ('out_of_possession', 1) or is_full_back or is_reverse:
        verify_matrix_role_native()
        offset, word, description = validate_matrix_role_records(tac, donor_members['.tac'], phase, slot)
        changed = tac[:offset] + word + tac[offset + 8:]
        return changed, {'phase': phase, 'position_index': slot, **description,
                         'donor_template_path': str(donor_path), 'donor_template_sha256': sha(donor_bytes),
                         'scope': 'Exact stored record reproduction; full UI setter parity, effective player instructions and game import are unverified.'}, donor_path, donor_bytes
    if phase == 'in_possession' and slot == 5:
        verify_base_role_native()
        offset, word = validate_base_role_records(tac, donor_members['.tac'])
        position, before_role, after_role = 'DM(CR)', 'Box-To-Box Midfielder', 'Defensive Midfielder'
        before_word, after_word = '0000000000410000', '0000000000200010'
    elif phase == 'out_of_possession' and slot in (4, 7):
        verify_wing_back_native()
        offset, word = validate_wing_back_records(tac, donor_members['.tac'], slot)
        position, before_role, after_role = ('WB(R)' if slot == 4 else 'WB(L)'), 'Pressing Wing-Back', 'Wing-Back'
        before_word, after_word = '0000000000402000', '0000000000201000'
    elif phase == 'in_possession':
        verify_inside_forward_native()
        offset, word = validate_inside_forward_records(tac, donor_members['.tac'], slot)
        position, before_role, after_role = ('AM(R)' if slot == 7 else 'AM(L)'), 'Winger', 'Inside Forward'
        before_word, after_word = '0000000000400080', '0000000008800000'
    else:
        verify_tracking_midfielder_native()
        offset, word = validate_tracking_midfielder_records(tac, donor_members['.tac'], slot)
        position, before_role, after_role = TRACKING_MIDFIELDER_PREFIXES[slot][0], 'Attacking Midfielder', 'Tracking Attacking Midfielder'
        before_word, after_word = '0000000040400000', '0000000080200000'
    changed = tac[:offset] + word + tac[offset + 8:]
    return changed, {'phase': phase, 'position_index': slot, 'position': position,
                     'before': {'role': before_role, 'native_role_word': before_word},
                     'after': {'role': after_role, 'native_role_word': after_word},
                     'donor_template_path': str(donor_path), 'donor_template_sha256': sha(donor_bytes),
                     'scope': 'Exact stored record reproduction; full UI setter parity, effective player instructions and game import are unverified.'}, donor_path, donor_bytes


def read_template(raw: str) -> tuple[Path, bytes, dict[str, bytes]]:
    path = Path(raw).expanduser().resolve(strict=True)
    if path.suffix.lower() != '.fmf' or not path.is_file():
        raise ValueError('Template must be an existing .fmf file.')
    if not 26 <= path.stat().st_size <= MAX_TEMPLATE_BYTES:
        raise ValueError('Template size is outside the supported 26 byte to 16 MiB range.')
    data = path.read_bytes()
    members = extract_member_plaintexts(path)
    if '.tac' not in members or '.aom' not in members:
        raise ValueError('Template requires native .tac and .aom members.')
    tac = members['.tac']
    # Observed FM26/FM27 cat. envelope. No fabricated version upgrading.
    if tac[:10] != bytes.fromhex('03016361742e22002244') or tac[11] not in (26, 27):
        raise ValueError('Template is not an observed FM27-generation native tactic (cat. 0x44, source major 26 or 27).')
    return path, data, members


def tackling_selection(tac: bytes) -> tuple[int, int]:
    setup = parse_tac_plaintext(tac).get('pre_style_setup', {})
    offset = setup.get('team_instruction_vector_candidate_offset')
    if not isinstance(offset, int) or setup.get('team_instruction_vector_candidate_size') != 12 or offset + 12 > len(tac):
        raise ValueError('Native team instruction vector is not supported.')
    # FM27 native creator writer 4A8D824 -> 4A8E878 -> 4A8E948 ->
    # 4A8EB90 writes three raw little-endian u32 chunks of options 0..83.
    # Existing native KEY routes name bit72 Get Stuck In and bit73 Stay On Feet.
    value = tac[offset + 9] & 3
    if value == 3:
        raise ValueError('Template has contradictory stored tackling selections.')
    return offset + 9, value


def replace_tackling(tac: bytes, selection: str) -> bytes:
    if selection not in TACKLING_FLAGS:
        raise ValueError('Unsupported team tackling selection.')
    offset, _ = tackling_selection(tac)
    result = bytearray(tac)
    result[offset] = (result[offset] & ~3) | TACKLING_FLAGS[selection]
    return bytes(result)


DEFENSIVE_LINE_FLAGS = {
    "No explicit selection": 0,
    "Much Higher Defensive Line": 1,
    "Higher Defensive Line": 2,
    "Lower Defensive Line": 4,
    "Much Lower Defensive Line": 8,
}


def defensive_line_selection(tac: bytes) -> tuple[int, str]:
    setup = parse_tac_plaintext(tac).get("pre_style_setup", {})
    offset = setup.get("team_instruction_vector_candidate_offset")
    if (not isinstance(offset, int) or offset < 0
            or setup.get("team_instruction_vector_candidate_size") != 12
            or offset + 12 > len(tac)):
        raise ValueError("Unsupported native team instruction vector.")
    value = tac[offset + 7] & 15
    names = {value: name for name, value in DEFENSIVE_LINE_FLAGS.items()}
    if value not in names:
        raise ValueError("Template has contradictory stored defensive-line selections.")
    return offset + 7, names[value]


def replace_defensive_line(tac: bytes, label: str) -> bytes:
    if label not in DEFENSIVE_LINE_FLAGS:
        raise ValueError("Unsupported stored defensive-line selection.")
    offset, _ = defensive_line_selection(tac)
    result = bytearray(tac)
    result[offset] = (result[offset] & 0xF0) | DEFENSIVE_LINE_FLAGS[label]
    return bytes(result)


def describe_defensive_line(tac: bytes) -> dict:
    """Report ambiguous stored choices without blocking unrelated inherited edits."""
    try:
        _, label = defensive_line_selection(tac)
    except ValueError as error:
        if str(error) != "Template has contradictory stored defensive-line selections.":
            raise
        return {"defensive_line": None, "defensive_line_state": "conflicting_stored_selections"}
    return {"defensive_line": label, "defensive_line_state": "known"}


TEMPO_BITS = {
    'No explicit selection': None,
    'Much Higher Tempo': 46,
    'Higher Tempo': 47,
    'Lower Tempo': 48,
    'Much Lower Tempo': 49,
}
TEMPO_MASK = sum(1 << bit for bit in TEMPO_BITS.values() if bit is not None)


def tempo_selection(tac: bytes) -> tuple[int, str]:
    setup = parse_tac_plaintext(tac).get('pre_style_setup', {})
    offset = setup.get('team_instruction_vector_candidate_offset')
    if (not isinstance(offset, int) or offset < 0
            or setup.get('team_instruction_vector_candidate_size') != 12
            or offset + 12 > len(tac)):
        raise ValueError('Unsupported native team instruction vector.')
    # The same native creator writer used for tackling and line height writes
    # options 0..83 directly. Native English option labels bind tempo to 46..49.
    if any(OPTION_NAMES.get(bit) != name for name, bit in TEMPO_BITS.items() if bit is not None):
        raise ValueError('Native tempo option labels changed.')
    selected = int.from_bytes(tac[offset:offset + 12], 'little') & TEMPO_MASK
    for name, bit in TEMPO_BITS.items():
        if selected == (0 if bit is None else 1 << bit):
            return offset, name
    raise ValueError('Template has contradictory stored tempo selections.')


def replace_tempo(tac: bytes, label: str) -> bytes:
    if label not in TEMPO_BITS:
        raise ValueError('Unsupported stored tempo selection.')
    offset, _ = tempo_selection(tac)
    flags = int.from_bytes(tac[offset:offset + 12], 'little') & ~TEMPO_MASK
    bit = TEMPO_BITS[label]
    if bit is not None:
        flags |= 1 << bit
    return tac[:offset] + flags.to_bytes(12, 'little') + tac[offset + 12:]


def describe_tempo(tac: bytes) -> dict:
    try:
        _, label = tempo_selection(tac)
    except ValueError as error:
        if str(error) != 'Template has contradictory stored tempo selections.':
            raise
        return {'tempo': None, 'tempo_state': 'conflicting_stored_selections'}
    return {'tempo': label, 'tempo_state': 'known'}


PASSING_BITS = {
    'No explicit selection': None,
    'Much More Direct Passing': 1,
    'More Direct Passing': 2,
    'Shorter Passing': 3,
    'Much Shorter Passing': 4,
}
PASSING_MASK = sum(1 << bit for bit in PASSING_BITS.values() if bit is not None)


def passing_selection(tac: bytes) -> tuple[int, str]:
    setup = parse_tac_plaintext(tac).get('pre_style_setup', {})
    offset = setup.get('team_instruction_vector_candidate_offset')
    if (type(offset) is not int or offset < 0
            or setup.get('team_instruction_vector_candidate_size') != 12
            or offset + 12 > len(tac)):
        raise ValueError('Unsupported native team instruction vector.')
    # Creator 4A8E948 -> 4A8EB90 serializes raw options0..83 into three u32s.
    # English KEY routes bind these four stored passing selections to bits1..4.
    # This bounded replacement does not establish native UI clearing/defaults.
    if any(OPTION_NAMES.get(bit) != name for name, bit in PASSING_BITS.items() if bit is not None):
        raise ValueError('Native passing option labels changed.')
    selected = int.from_bytes(tac[offset:offset + 12], 'little') & PASSING_MASK
    for name, bit in PASSING_BITS.items():
        if selected == (0 if bit is None else 1 << bit):
            return offset, name
    raise ValueError('Template has contradictory stored passing selections.')


def replace_passing(tac: bytes, label: str) -> bytes:
    if not isinstance(label, str) or label not in PASSING_BITS:
        raise ValueError('Unsupported stored passing selection.')
    offset, _ = passing_selection(tac)
    flags = int.from_bytes(tac[offset:offset + 12], 'little') & ~PASSING_MASK
    bit = PASSING_BITS[label]
    if bit is not None:
        flags |= 1 << bit
    return tac[:offset] + flags.to_bytes(12, 'little') + tac[offset + 12:]


def describe_passing(tac: bytes) -> dict:
    try:
        _, label = passing_selection(tac)
    except ValueError as error:
        if str(error) != 'Template has contradictory stored passing selections.':
            raise
        return {'passing_directness': None, 'passing_directness_state': 'conflicting_stored_selections'}
    return {'passing_directness': label, 'passing_directness_state': 'known'}


LOSS_BITS = {'No explicit selection': None, 'Counter-Press': 70, 'Regroup': 71}
LOSS_MASK = (1 << 70) | (1 << 71)


def possession_loss_selection(tac: bytes) -> tuple[int, str]:
    setup = parse_tac_plaintext(tac).get('pre_style_setup', {})
    offset = setup.get('team_instruction_vector_candidate_offset')
    if (type(offset) is not int or offset < 0
            or setup.get('team_instruction_vector_candidate_size') != 12 or offset + 12 > len(tac)):
        raise ValueError('Unsupported native team instruction vector.')
    if OPTION_NAMES.get(70) != 'Counter-Press' or OPTION_NAMES.get(71) != 'Regroup':
        raise ValueError('Native possession-loss option labels changed.')
    selected = int.from_bytes(tac[offset:offset + 12], 'little') & LOSS_MASK
    for label, bit in LOSS_BITS.items():
        if selected == (0 if bit is None else 1 << bit):
            return offset, label
    raise ValueError('Template has contradictory stored possession-loss selections.')


def replace_possession_loss(tac: bytes, label: str) -> bytes:
    if type(label) is not str or label not in LOSS_BITS:
        raise ValueError('Unsupported stored possession-loss selection.')
    offset, _ = possession_loss_selection(tac)
    #Native44694E8..9550 clears listed opposites before44695D0..95EC sets
    #the requested bit. The pinned complete table pairs only70 with71.
    flags = int.from_bytes(tac[offset:offset + 12], 'little') & ~LOSS_MASK
    bit = LOSS_BITS[label]
    if bit is not None:
        flags |= 1 << bit
    return tac[:offset] + flags.to_bytes(12, 'little') + tac[offset + 12:]


def describe_possession_loss(tac: bytes) -> dict:
    try:
        _, label = possession_loss_selection(tac)
    except ValueError as error:
        if str(error) != 'Template has contradictory stored possession-loss selections.':
            raise
        return {'possession_loss': None, 'possession_loss_state': 'conflicting_stored_selections'}
    return {'possession_loss': label, 'possession_loss_state': 'known'}


GAIN_BITS = {'No explicit selection': None, 'Counter': 54, 'Hold Shape': 55}
GAIN_MASK = (1 << 54) | (1 << 55)


def possession_gain_selection(tac: bytes) -> tuple[int, str]:
    setup = parse_tac_plaintext(tac).get('pre_style_setup', {})
    offset = setup.get('team_instruction_vector_candidate_offset')
    if (type(offset) is not int or offset < 0
            or setup.get('team_instruction_vector_candidate_size') != 12 or offset + 12 > len(tac)):
        raise ValueError('Unsupported native team instruction vector.')
    if OPTION_NAMES.get(54) != 'Counter' or OPTION_NAMES.get(55) != 'Hold Shape':
        raise ValueError('Native possession-gain option labels changed.')
    selected = int.from_bytes(tac[offset:offset + 12], 'little') & GAIN_MASK
    for label, bit in GAIN_BITS.items():
        if selected == (0 if bit is None else 1 << bit):
            return offset, label
    raise ValueError('Template has contradictory stored possession-gain selections.')


def replace_possession_gain(tac: bytes, label: str) -> bytes:
    if type(label) is not str or label not in GAIN_BITS:
        raise ValueError('Unsupported stored possession-gain selection.')
    offset, _ = possession_gain_selection(tac)
    #Native44694E8..9550 clears listed opposites before44695D0..95EC sets
    #the requested bit. The pinned complete table pairs only54 with55.
    flags = int.from_bytes(tac[offset:offset + 12], 'little') & ~GAIN_MASK
    bit = GAIN_BITS[label]
    if bit is not None:
        flags |= 1 << bit
    return tac[:offset] + flags.to_bytes(12, 'little') + tac[offset + 12:]


def describe_possession_gain(tac: bytes) -> dict:
    try:
        _, label = possession_gain_selection(tac)
    except ValueError as error:
        if str(error) != 'Template has contradictory stored possession-gain selections.':
            raise
        return {'possession_gain': None, 'possession_gain_state': 'conflicting_stored_selections'}
    return {'possession_gain': label, 'possession_gain_state': 'known'}


STORED_CONTROLS = {
    'final_third_delivery': {'No explicit selection': None, 'Hit Early Crosses': 9, 'Work Ball Into Box': 17},
    'pressing_block': {'No explicit selection': None, 'High Press': 61, 'Mid Block': 62, 'Low Block': 63},
    'crossing_style': {'No explicit selection': None, 'Floated Crosses': 10, 'Whipped Crosses': 11, 'Low Crosses': 12},
    'goal_kick_length': {'No explicit selection': None, 'Short Goal Kicks': 44, 'Long Goal Kicks': 45},
    'team_width': {'No explicit selection': None, 'Much Wider': 50, 'Wider': 51,
                   'Narrower': 52, 'Much Narrower': 53},
    'pressing_frequency': {'No explicit selection': None, 'Trigger Press Much More Often': 65,
                          'Trigger Press More Often': 66, 'Trigger Press Less Often': 67,
                          'Trigger Press Much Less Often': 68},
}


FOCUS_PLAY_BITS = {'Focus Play Down The Left': 21, 'Focus Play Down The Right': 22,
                   'Focus Play Through The Middle': 23, 'Focus Play Down Both Flanks': 24}
FOCUS_PLAY_MASK = sum(1 << bit for bit in FOCUS_PLAY_BITS.values())
FOCUS_PLAY_VALID = (0, 1 << 21, 1 << 22, (1 << 21) | (1 << 22), 1 << 23, 1 << 24)


def focus_play_selection(tac: bytes) -> tuple[int, list[str]]:
    setup = parse_tac_plaintext(tac).get('pre_style_setup', {})
    offset = setup.get('team_instruction_vector_candidate_offset')
    if (type(offset) is not int or offset < 1 or setup.get('team_instruction_vector_candidate_size') != 12
            or offset + 12 > len(tac) or tac[offset - 1] != 3):
        raise ValueError('Unsupported native team instruction vector.')
    if any(OPTION_NAMES.get(bit) != name for name, bit in FOCUS_PLAY_BITS.items()):
        raise ValueError('Native focus-play option labels changed.')
    flags = int.from_bytes(tac[offset:offset + 12], 'little') & FOCUS_PLAY_MASK
    if flags not in FOCUS_PLAY_VALID:
        raise ValueError('Template has contradictory stored focus-play selections.')
    return offset, [name for name, bit in FOCUS_PLAY_BITS.items() if flags & (1 << bit)]


def replace_focus_play(tac: bytes, selections: list[str]) -> bytes:
    if (type(selections) is not list or len(selections) > 2
            or any(type(s) is not str or s not in FOCUS_PLAY_BITS for s in selections)
            or len(set(selections)) != len(selections)):
        raise ValueError('Unsupported stored focus_play selections; use a distinct list of native labels.')
    selected = sum(1 << FOCUS_PLAY_BITS[s] for s in selections)
    if selected not in FOCUS_PLAY_VALID:
        raise ValueError('Contradictory requested focus-play selections.')
    offset, _ = focus_play_selection(tac)
    flags = (int.from_bytes(tac[offset:offset + 12], 'little') & ~FOCUS_PLAY_MASK) | selected
    return tac[:offset] + flags.to_bytes(12, 'little') + tac[offset + 12:]


def describe_focus_play(tac: bytes) -> dict:
    try:
        _, selections = focus_play_selection(tac)
    except ValueError as error:
        if str(error) != 'Template has contradictory stored focus-play selections.':
            raise
        return {'focus_play': None, 'focus_play_state': 'conflicting_stored_selections'}
    return {'focus_play': selections, 'focus_play_state': 'known'}

WIDE_SUPPORT_BITS = {'Look For Overlap': 25, 'Overlap Left': 26, 'Overlap Right': 27,
                     'Look For Underlap': 28, 'Underlap Left': 29, 'Underlap Right': 30}
WIDE_SUPPORT_MASK = sum(1 << bit for bit in WIDE_SUPPORT_BITS.values())
WIDE_SUPPORT_OPPOSITIONS = ((25, 26), (25, 27), (26, 29), (27, 30),
                            (28, 25), (28, 29), (28, 30))
WIDE_SUPPORT_VALID = tuple(sum(1 << (25 + i) for i in range(6) if subset & (1 << i))
                           for subset in range(64)
                           if not any(subset & (1 << (a - 25)) and subset & (1 << (b - 25))
                                      for a, b in WIDE_SUPPORT_OPPOSITIONS))


def wide_support_selection(tac: bytes) -> tuple[int, list[str]]:
    setup = parse_tac_plaintext(tac).get('pre_style_setup', {})
    offset = setup.get('team_instruction_vector_candidate_offset')
    if (type(offset) is not int or offset < 1 or setup.get('team_instruction_vector_candidate_size') != 12
            or offset + 12 > len(tac) or tac[offset - 1] != 3):
        raise ValueError('Unsupported native team instruction vector.')
    if any(OPTION_NAMES.get(bit) != name for name, bit in WIDE_SUPPORT_BITS.items()):
        raise ValueError('Native wide-support option labels changed.')
    flags = int.from_bytes(tac[offset:offset + 12], 'little') & WIDE_SUPPORT_MASK
    if flags not in WIDE_SUPPORT_VALID:
        raise ValueError('Template has contradictory stored wide-support selections.')
    return offset, [name for name, bit in WIDE_SUPPORT_BITS.items() if flags & (1 << bit)]


def replace_wide_support(tac: bytes, selections: list[str]) -> bytes:
    if (type(selections) is not list or len(selections) > 3
            or any(type(s) is not str or s not in WIDE_SUPPORT_BITS for s in selections)
            or len(set(selections)) != len(selections)):
        raise ValueError('Unsupported stored wide_support selections; use a distinct list of native labels.')
    selected = sum(1 << WIDE_SUPPORT_BITS[s] for s in selections)
    if selected not in WIDE_SUPPORT_VALID:
        raise ValueError('Contradictory requested wide-support selections.')
    offset, _ = wide_support_selection(tac)
    flags = (int.from_bytes(tac[offset:offset + 12], 'little') & ~WIDE_SUPPORT_MASK) | selected
    return tac[:offset] + flags.to_bytes(12, 'little') + tac[offset + 12:]


def describe_wide_support(tac: bytes) -> dict:
    try:
        _, selections = wide_support_selection(tac)
    except ValueError as error:
        if str(error) != 'Template has contradictory stored wide-support selections.':
            raise
        return {'wide_support': None, 'wide_support_state': 'conflicting_stored_selections'}
    return {'wide_support': selections, 'wide_support_state': 'known'}



def stored_control_selection(tac: bytes, field: str) -> tuple[int, str]:
    choices = STORED_CONTROLS[field]
    setup = parse_tac_plaintext(tac).get('pre_style_setup', {})
    offset = setup.get('team_instruction_vector_candidate_offset')
    if (type(offset) is not int or offset < 1
            or setup.get('team_instruction_vector_candidate_size') != 12
            or offset + 12 > len(tac) or tac[offset - 1] != 3):
        raise ValueError('Unsupported native team instruction vector.')
    # Native4A8EBB0 emits count3 followed by exactly three raw u32 words.
    # The same raw-bit serializer and English KEY routes used above bind
    # width50..53 and pressing65..68; native UI clearing remains unverified.
    # Goal-kick44/45 and crossing10/11/12 use separately pinned native
    # opposition groups; no other native opposition touches those groups.
    # Pressing-block61/62/63 likewise has only its three internal oppositions.
    # Final-third9/17 has only its one mutual opposition.
    if any(OPTION_NAMES.get(bit) != label for label, bit in choices.items() if bit is not None):
        raise ValueError(f'Native {field} option labels changed.')
    mask = sum(1 << bit for bit in choices.values() if bit is not None)
    selected = int.from_bytes(tac[offset:offset + 12], 'little') & mask
    for label, bit in choices.items():
        if selected == (0 if bit is None else 1 << bit):
            return offset, label
    raise ValueError(f'Template has contradictory stored {field} selections.')


def replace_stored_control(tac: bytes, field: str, label: str) -> bytes:
    choices = STORED_CONTROLS[field]
    if type(label) is not str or label not in choices:
        raise ValueError(f'Unsupported stored {field} selection.')
    offset, _ = stored_control_selection(tac, field)
    mask = sum(1 << bit for bit in choices.values() if bit is not None)
    flags = int.from_bytes(tac[offset:offset + 12], 'little') & ~mask
    bit = choices[label]
    if bit is not None:
        flags |= 1 << bit
    return tac[:offset] + flags.to_bytes(12, 'little') + tac[offset + 12:]


def describe_stored_controls(tac: bytes) -> dict:
    result = {}
    for field in STORED_CONTROLS:
        try:
            _, label = stored_control_selection(tac, field)
        except ValueError as error:
            if str(error) != f'Template has contradictory stored {field} selections.':
                raise
            result.update({field: None, field + '_state': 'conflicting_stored_selections'})
        else:
            result.update({field: label, field + '_state': 'known'})
    return result


def inspect_stored_football(tac: bytes) -> dict:
    parsed = parse_tac_plaintext(tac)
    style = parsed.get('tactical_style', {})
    first = style.get('end_exclusive')
    if not isinstance(first, int):
        raise ValueError('No supported tactical-style boundary for position records.')
    # 4A8E8F4 writes the style string; 4A8E91C..928 writes exactly four
    # bytes of style code, then creator 4A8D834 starts the IP/OOP records.
    decoded = decode_position_records(tac, first + 4)
    phases = {}
    for phase, records in decoded['phases'].items():
        phases[phase] = [{
            'slot': record['position_index'], 'position': record['position_name'],
            'native_position_mask': record['position_mask'],
            'role': record['role']['compiled_english_name'],
            'native_role_word': record['native_role_word'],
        } for record in records]
    offset = parsed['pre_style_setup']['team_instruction_vector_candidate_offset']
    flags = int.from_bytes(tac[offset:offset + 12], 'little')
    selected = [{'native_option_id': index, 'name': OPTION_NAMES.get(index)} for index in range(1, 84) if flags & (1 << index)]
    return {
        'phase_positions_and_roles': phases,
        'stored_team_instructions': selected,
        'unmapped_team_instruction_bits': [index for index in [0, *range(84, 96)] if flags & (1 << index)],
        'formation': None,
        'read_scope': 'Native stored positions, phase roles and team selection bits; effective player overrides, phase applicability and defaults are unverified.',
        'role_labels_resource_sha256': ENGLISH_RESOURCE_SHA256,
    }


def summarize(raw: str) -> dict:
    path, data, members = read_template(raw)
    tac = members['.tac']
    parsed = parse_tac_plaintext(tac)
    name = parsed.get('name', {}).get('value')
    if not name:
        raise ValueError('Template has no readable native tactic name.')
    setup = parsed.get('pre_style_setup', {})
    phase_position_description = describe_phase_position(tac)
    return {
        'template_path': str(path), 'template_sha256': sha(data), 'name': name,
        'source_game_major': tac[11], 'native_header_hex': tac[:16].hex(),
        'mentality': MENTALITIES.get(setup.get('mentality_id')),
        'team_tackling': next(label for label, value in TACKLING_FLAGS.items() if value == tackling_selection(tac)[1]),
        **describe_defensive_line(tac),
        **describe_tempo(tac),
        **describe_passing(tac),
        **describe_possession_loss(tac),
        **describe_possession_gain(tac),
        **describe_stored_controls(tac),
        **describe_focus_play(tac),
        **describe_wide_support(tac),
        **describe_base_role_source(tac),
        **describe_stored_role_instructions(tac),
        **phase_position_description,
        'tactical_style': parsed.get('tactical_style', {}).get('value'),
        'member_sizes': {key: len(value) for key, value in members.items()},
        'stored_football': inspect_stored_football(tac),
        'shape_and_roles': 'Phase positions and base roles are read from native records. Formation names are not inferred from filenames; unrequested phase/role bytes are inherited.',
        'supported_edits': ['name', 'mentality', 'team_tackling'] + (['defensive_line'] if describe_defensive_line(tac)['defensive_line_state'] == 'known' else []) + (['tempo'] if describe_tempo(tac)['tempo_state'] == 'known' else []) + (['passing_directness'] if describe_passing(tac)['passing_directness_state'] == 'known' else []) + [field for field in STORED_CONTROLS if describe_stored_controls(tac)[field + '_state'] == 'known'] + (['focus_play'] if describe_focus_play(tac)['focus_play_state'] == 'known' else []) + (['wide_support'] if describe_wide_support(tac)['wide_support_state'] == 'known' else []) + (['base_role'] if describe_base_role_source(tac)['base_role_eligibility'] == 'requires_matching_inspected_donor_and_native_checks' else []) + (['stored_role_instructions'] if describe_stored_role_instructions(tac)['stored_role_instructions_eligibility'] == 'requires_matching_inspected_donor_and_native_checks' else []) + (['phase_position'] if phase_position_description['phase_position_cases'] else []) + ['native_authoring'] + (['possession_loss'] if describe_possession_loss(tac)['possession_loss_state'] == 'known' else []) + (['possession_gain'] if describe_possession_gain(tac)['possession_gain_state'] == 'known' else []),
        'game_load_verified': False,
    }


def replace_string(data: bytes, offset: int, name: str, expected: str) -> bytes:
    old = expected.encode('utf-8')
    if data[offset:offset + 4] != struct.pack('<I', len(old)) or data[offset + 4:offset + 4 + len(old)] != old:
        raise ValueError('Native name reference does not match the decoded tactic name.')
    encoded = name.encode('utf-8')
    return data[:offset] + struct.pack('<I', len(encoded)) + encoded + data[offset + 4 + len(old):]


def synchronize_toc(path: Path, old: str, name: str) -> None:
    result = probe(path)
    data = path.read_bytes()
    toc = zstd.ZstdDecompressor().decompress(data[result['zstd_toc_offset']:], max_output_size=2_000_000)
    # Root display name and .tac entry are length-prefixed atoms in all six fixtures.
    matches = [s for s in result['toc']['strings'] if s['text'] == old]
    if len(matches) != 2 or matches[0]['offset'] != 0:
        raise ValueError('Template has an unsupported tactic-name table layout.')
    for entry in reversed(matches):
        toc = replace_string(toc, entry['offset'], name, old)
    path.write_bytes(data[:result['nested_fmf_offset']] + INNER_MAGIC + zstd.ZstdCompressor(level=3).compress(toc))



NATIVE_AUTHORING_FILES = ('fm_tactic_native_authoring.py', 'fm_tactic_native_core.py',
                          'fm_tactic_role_catalog.py', 'fm_tactic_role_catalog.json',
                          'fm_tactic_team_instructions.py')
NATIVE_AUTHORING_BINARY_SHA = '774cacde63567fd3901c47719e7a6ed94cc3a0a62e9b94989dcac6b4890ec0e1'
IGNORED_LEGACY_ROLE_FIELDS = frozenset({'duty'})
SCALAR_TEAM_FIELDS = {'team_tackling', 'defensive_line', 'tempo', 'passing_directness',
                      'team_width', 'pressing_frequency', 'goal_kick_length', 'crossing_style',
                      'final_third_delivery', 'pressing_block', 'focus_play', 'wide_support',
                      'possession_loss', 'possession_gain'}


def native_authoring_sources() -> dict:
    return {name: sha((Path(__file__).resolve().parent/name).read_bytes()) for name in NATIVE_AUTHORING_FILES}


def verify_native_authoring_receipt(receipt: dict) -> None:
    if native_authoring_sources() != receipt['source_hashes']:
        raise ValueError('Native authoring sources changed; no output delivered.')
    with ROLE_NATIVE_PLUGIN.open('rb') as handle:
        if hashlib.file_digest(handle, 'sha256').hexdigest() != NATIVE_AUTHORING_BINARY_SHA:
            raise ValueError('Native authoring binary changed; no output delivered.')
    if sha(LOSS_ENGLISH_RESOURCE.read_bytes()) != ENGLISH_RESOURCE_SHA256:
        raise ValueError('Native authoring English definitions changed; no output delivered.')
    if sha(STORED_ROLE_PI_METADATA.read_bytes()) != STORED_ROLE_PI_METADATA_SHA:
        raise ValueError('Native authoring enum metadata changed; no output delivered.')


def run_native_authoring(action: str, tac: bytes | None = None, request: dict | None = None,
                         expected_records: list | None = None) -> dict:
    before_sources = native_authoring_sources()
    packet = {'action': action}
    if tac is not None:
        packet['payload_base64'] = base64.b64encode(tac).decode('ascii')
    if request is not None:
        packet['request'] = request
    if expected_records is not None:
        packet['expected_records'] = expected_records
    process = subprocess.run([str(NATIVE_READER_ROOT/'.venv/bin/python'), '-E',
                              str(Path(__file__).resolve().parent/'fm_tactic_native_authoring.py')],
                             input=json.dumps(packet), text=True, capture_output=True, timeout=50)
    if native_authoring_sources() != before_sources:
        raise ValueError('Native authoring sources changed during execution.')
    if process.returncode:
        message = process.stderr.strip() or 'Native authoring process refused the request.'
        try:
            packet = json.loads(message)
        except (ValueError, TypeError):
            packet = None
        if type(packet) is dict and type(packet.get('error')) is str and type(packet.get('diagnostic')) is dict:
            error = ValueError(packet['error'])
            error.diagnostic = packet['diagnostic']
            raise error
        raise ValueError(message)
    if len(process.stdout) > 1_048_576:
        raise ValueError('Native authoring response exceeds the bounded protocol.')
    result = json.loads(process.stdout)
    if action == 'author':
        if result['receipt']['source_hashes'] != before_sources:
            raise ValueError('Native authoring source provenance mismatch.')
        payload = base64.b64decode(result['payload_base64'], validate=True)
        if not 16 <= len(payload) <= 65536 or payload[:15] != tac[:15]:
            raise ValueError('Native authoring returned an unsupported source header.')
        result['payload'] = payload
        verify_native_authoring_receipt(result['receipt'])
    return result


def authoring_catalog(params: dict) -> dict:
    if set(params) - {'action', 'template_path', 'template_sha256'}:
        raise ValueError('authoring_catalog accepts only an optional inspected template path and hash.')
    if 'template_path' not in params:
        if 'template_sha256' in params:
            raise ValueError('A catalog template hash requires its path.')
        return run_native_authoring('catalog')
    path, blob, members = read_template(params['template_path'])
    if 'template_sha256' in params and params['template_sha256'] != sha(blob):
        raise ValueError('Catalog template hash changed; inspect it again.')
    result = run_native_authoring('catalog', members['.tac'])
    if path.read_bytes() != blob:
        raise ValueError('Catalog template changed during native inspection.')
    return result | {'template_path': str(path), 'template_sha256': sha(blob)}

def native_source_preservation(source: bytes, authored: bytes, request: dict) -> dict:
    """Compare the original source outside declared complete native records.

    Parent correspondence metadata remains compared, so native coupled changes
    cannot silently turn into a source-byte preservation claim.
    """
    normalized = replace_tac_name(authored, parse_tac_plaintext(source)['name']['value'])
    owned = set()
    for phase in request.get('positions', {}):
        owned.update((phase, slot) for slot in range(11))
    for field in ('roles', 'player_instructions'):
        owned.update((row['phase'], row['position_index']) for row in request.get(field, []))
    if request.get('instruction_policy') == 'native_defaults':
        owned.update((phase, slot) for phase in ('in_possession', 'out_of_possession') for slot in range(11))
    if 'team_instructions' in request:
        source_offset = parse_tac_plaintext(source)['pre_style_setup']['team_instruction_vector_candidate_offset']
        target_offset = parse_tac_plaintext(normalized)['pre_style_setup']['team_instruction_vector_candidate_offset']
        normalized = normalized[:target_offset] + source[source_offset:source_offset+12] + normalized[target_offset+12:]

    def outside_records(payload):
        records = phase_records(payload)
        spans = sorted((records[phase][slot]['record_offset'], records[phase][slot]['record_end_exclusive'])
                       for phase, slot in owned)
        chunks = []; at = 0
        for start, end in spans:
            chunks.append(payload[at:start]); at = end
        chunks.append(payload[at:])
        return b''.join(chunks)

    original_outside = outside_records(source)
    authored_outside = outside_records(normalized)
    return {'source_outside_declared_native_footprints_preserved': original_outside == authored_outside,
            'source_outside_sha256': sha(original_outside), 'authored_outside_sha256': sha(authored_outside),
            'owned_phase_records': [{'phase': phase, 'position_index': slot} for phase, slot in sorted(owned)],
            'team_selection_replacement': 'team_instructions' in request,
            'scope': 'Original source byte comparison after removing declared complete record edits and restoring the source name and explicitly replaced team selections. Parent correspondence metadata remains compared; a difference is disclosed rather than described as preserved.'}


def generate(params: dict) -> dict:
    allowed = {'action', 'template_path', 'template_sha256', 'name', 'mentality', 'team_tackling', 'defensive_line', 'tempo', 'passing_directness', 'team_width', 'pressing_frequency', 'goal_kick_length', 'crossing_style', 'final_third_delivery', 'pressing_block', 'focus_play', 'wide_support', 'base_role', 'stored_role_instructions', 'phase_position', 'native_authoring', 'possession_loss', 'possession_gain', 'preview', 'fm27_folder', 'tactics_directory'}
    if set(params) - allowed:
        raise ValueError('Unsupported tactic edit. Supported edits are name, mentality, team_tackling, defensive_line, tempo, passing_directness, team_width, pressing_frequency, goal_kick_length, crossing_style, final_third_delivery, pressing_block, focus_play, wide_support, possession_loss, possession_gain and the exact supported native_authoring or the exact supported base_role/stored_role_instructions/phase_position cases; other fields are inherited.')
    if 'native_authoring' in params:
        if type(params['native_authoring']) is not dict:
            raise ValueError('native_authoring must be an object.')
        if {'base_role', 'stored_role_instructions', 'phase_position'} & set(params):
            raise ValueError('Use native_authoring for all native record edits in one request; legacy donor edits cannot be combined.')
        if 'team_instructions' in params['native_authoring'] and SCALAR_TEAM_FIELDS & set(params):
            raise ValueError('Complete native team replacement cannot be combined with scalar team-selection fields; mentality remains available.')
        roles = params['native_authoring'].get('roles')
        if type(roles) is list:
            # A role is {phase, position_index, role}. A request written for the earlier interface
            # may carry a fourth field; it is dropped here unread and reaches no result or receipt.
            params = params | {'native_authoring': params['native_authoring'] | {'roles': [
                {key: value for key, value in row.items() if key not in IGNORED_LEGACY_ROLE_FIELDS}
                if type(row) is dict else row for row in roles]}}
    name = params.get('name', '')
    if not isinstance(name, str) or not name.strip() or len(name.encode('utf-8')) > 120 or any(ord(c) < 32 or ord(c) == 127 for c in name):
        raise ValueError('Name must be printable text containing 1 to 120 UTF-8 bytes.')
    name = name.strip()
    preview = params.get('preview', False)
    if not isinstance(preview, bool):
        raise ValueError('preview must be a boolean.')
    fm27_folder = params.get('fm27_folder', False)
    if not isinstance(fm27_folder, bool):
        raise ValueError('fm27_folder must be a boolean.')
    if 'tactics_directory' in params and not fm27_folder:
        raise ValueError('tactics_directory requires fm27_folder.')
    template, source, before = read_template(params.get('template_path', ''))
    expected_sha = params.get('template_sha256')
    if not expected_sha or expected_sha != sha(source):
        raise ValueError('Template hash changed or missing. Inspect/list the template again before generating.')
    old_name = parse_tac_plaintext(before['.tac'])['name']['value']
    base_role, donor_path, donor_bytes = None, None, None
    role_instructions, pi_donor_path, pi_donor_bytes = None, None, None
    phase_position, position_donor_path, position_donor_bytes = None, None, None
    tac = before['.tac']
    native_receipt = None
    if 'native_authoring' in params:
        native_result = run_native_authoring('author', tac, params['native_authoring'])
        tac, native_receipt = native_result['payload'], native_result['receipt']
        native_receipt['source_preservation'] = native_source_preservation(before['.tac'], tac, params['native_authoring'])
    verification_tac = tac
    verification_name = parse_tac_plaintext(tac)['name']['value']
    if 'base_role' in params:
        tac, base_role, donor_path, donor_bytes = prepare_base_role(tac, params['base_role'])
    if 'stored_role_instructions' in params:
        tac, role_instructions, pi_donor_path, pi_donor_bytes = prepare_stored_role_instructions(tac, params['stored_role_instructions'])
    if 'phase_position' in params:
        tac, phase_position, position_donor_path, position_donor_bytes = prepare_phase_position(tac, params['phase_position'])
    tac = replace_tac_name(tac, name)
    mentality = params.get('mentality')
    if mentality is not None:
        if mentality not in MENTALITIES.values():
            raise ValueError('Unsupported mentality.')
        tac = replace_mentality(tac, mentality)
    defensive_line = params.get('defensive_line')
    if defensive_line is not None:
        tac = replace_defensive_line(tac, defensive_line)
    tempo = params.get('tempo')
    if tempo is not None:
        tac = replace_tempo(tac, tempo)
    passing_directness = params.get('passing_directness')
    if 'passing_directness' in params:
        tac = replace_passing(tac, passing_directness)
    for field in STORED_CONTROLS:
        if field in params:
            tac = replace_stored_control(tac, field, params[field])
    if 'focus_play' in params:
        tac = replace_focus_play(tac, params['focus_play'])
        verify_focus_play_native()
    if 'wide_support' in params:
        tac = replace_wide_support(tac, params['wide_support'])
        verify_wide_support_native()
    if 'goal_kick_length' in params:
        verify_goal_kicks_native()
    if 'crossing_style' in params:
        verify_crossing_native()
    if 'pressing_block' in params:
        verify_pressing_block_native()
    if 'final_third_delivery' in params:
        verify_final_third_native()
    if 'possession_loss' in params:
        tac = replace_possession_loss(tac, params['possession_loss'])
        verify_possession_loss_native()
    if 'possession_gain' in params:
        tac = replace_possession_gain(tac, params['possession_gain'])
        verify_possession_gain_native()
    team_tackling = params.get('team_tackling')
    if team_tackling is not None:
        tac = replace_tackling(tac, team_tackling)
    aom = before['.aom']
    handler = b'TACTICS_TYPE_HANDLER'
    if aom[:8] != bytes.fromhex('03016d6f612e0400') or aom[12:12 + len(handler)] != handler:
        raise ValueError('Unsupported native tactic details member.')
    aom = replace_string(aom, 12 + len(handler), name, old_name)
    scratch = Path(__file__).resolve().parent.parent / 'tmp'
    scratch.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='tactic-', dir=scratch) as folder:
        candidate = Path(folder) / 'candidate.fmf'
        repack_native_fmf(template, candidate, plaintext_overrides={'.tac': tac, '.aom': aom})
        synchronize_toc(candidate, old_name, name)
        after = extract_member_plaintexts(candidate)
        if set(after) != set(before) or after['.tac'] != tac or after['.aom'] != aom:
            raise ValueError('Native member roundtrip failed.')
        unchanged = [key for key in before if key not in ('.tac', '.aom')]
        if any(after[key] != before[key] for key in unchanged):
            raise ValueError('Unedited native member changed.')
        # Reverse supported edits to prove every unrequested byte survived.
        restored = replace_tac_name(after['.tac'], verification_name)
        if base_role is not None:
            record = phase_records(after['.tac'])[base_role['phase']][base_role['position_index']]
            donor_tac = extract_member_plaintexts(donor_path)['.tac']
            donor_record = phase_records(donor_tac)[base_role['phase']][base_role['position_index']]
            if after['.tac'][record['record_offset']:record['record_end_exclusive']] != donor_tac[donor_record['record_offset']:donor_record['record_end_exclusive']]:
                raise ValueError('Output does not reproduce the complete donor role record.')
            offset = phase_records(before['.tac'])[base_role['phase']][base_role['position_index']]['role_word_offset']
            restored = restored[:offset] + before['.tac'][offset:offset + 8] + restored[offset + 8:]
        if role_instructions is not None:
            record = phase_records(after['.tac'])['in_possession'][9]
            pi_donor_tac = extract_member_plaintexts(pi_donor_path)['.tac']
            pi_donor_record = phase_records(pi_donor_tac)['in_possession'][9]
            if after['.tac'][record['record_offset']:record['record_end_exclusive']] != pi_donor_tac[pi_donor_record['record_offset']:pi_donor_record['record_end_exclusive']]:
                raise ValueError('Output does not reproduce the complete donor instruction record.')
            _, offset, _ = stored_role_pi_record(before['.tac'])
            restored = restored[:offset] + before['.tac'][offset:offset + 8] + restored[offset + 8:]
        if phase_position is not None:
            slot = phase_position['position_index']
            record = phase_records(after['.tac'])['out_of_possession'][slot]
            donor_tac = extract_member_plaintexts(position_donor_path)['.tac']
            donor_record = phase_records(donor_tac)['out_of_possession'][slot]
            if after['.tac'][record['record_offset']:record['record_end_exclusive']] != donor_tac[donor_record['record_offset']:donor_record['record_end_exclusive']]:
                raise ValueError('Output does not reproduce the complete donor phase-position record.')
            original = phase_records(before['.tac'])['out_of_possession'][slot]
            start, end = original['record_offset'], original['record_end_exclusive']
            restored = restored[:start] + before['.tac'][start:end] + restored[end:]
        if mentality is not None:
            original_id = parse_tac_plaintext(before['.tac'])['pre_style_setup']['mentality_id']
            restored = replace_mentality(restored, MENTALITIES[original_id])
        if defensive_line is not None:
            restored = replace_defensive_line(restored, defensive_line_selection(before[".tac"])[1])
        if tempo is not None:
            restored = replace_tempo(restored, tempo_selection(before['.tac'])[1])
        if 'passing_directness' in params:
            restored = replace_passing(restored, passing_selection(before['.tac'])[1])
        for field in STORED_CONTROLS:
            if field in params:
                restored = replace_stored_control(restored, field, stored_control_selection(before['.tac'], field)[1])
        if 'focus_play' in params:
            restored = replace_focus_play(restored, focus_play_selection(before['.tac'])[1])
        if 'wide_support' in params:
            restored = replace_wide_support(restored, wide_support_selection(before['.tac'])[1])
        if 'possession_loss' in params:
            restored = replace_possession_loss(restored, possession_loss_selection(before['.tac'])[1])
        if 'possession_gain' in params:
            restored = replace_possession_gain(restored, possession_gain_selection(before['.tac'])[1])
        if team_tackling is not None:
            original_tackling = next(label for label, value in TACKLING_FLAGS.items() if value == tackling_selection(before['.tac'])[1])
            restored = replace_tackling(restored, original_tackling)
        if restored != verification_tac:
            raise ValueError('Unsupported tactic bytes changed.')
        if native_receipt is not None:
            native_postpack = run_native_authoring('validate', after['.tac'], expected_records=native_receipt['native_records'])
            offset = parse_tac_plaintext(after['.tac'])['pre_style_setup']['team_instruction_vector_candidate_offset']
            expected_flags = (after['.tac'][offset:offset+12] + bytes(4)).hex()
            if native_postpack['native_team_flags_hex'] != expected_flags:
                raise ValueError('Post-pack original native team selections differ from the archive.')
            if native_postpack['native_mentality_id'] != parse_tac_plaintext(after['.tac'])['pre_style_setup']['mentality_id']:
                raise ValueError('Post-pack original native mentality differs from the archive.')
            native_receipt['postpack_verification'] = native_postpack
            verify_native_authoring_receipt(native_receipt)
        if template.read_bytes() != source:
            raise ValueError('Template changed during generation; no output delivered.')
        if donor_path is not None and donor_path.read_bytes() != donor_bytes:
            raise ValueError('Base-role donor changed during generation; no output delivered.')
        if pi_donor_path is not None and pi_donor_path.read_bytes() != pi_donor_bytes:
            raise ValueError('Stored-role instruction donor changed during generation; no output delivered.')
        if position_donor_path is not None and position_donor_path.read_bytes() != position_donor_bytes:
            raise ValueError('Phase-position donor changed during generation; no output delivered.')
        if phase_position is not None:
            verify_phase_position_native()
        if base_role is not None and base_role['phase'] == 'out_of_possession' and base_role['position_index'] in (4, 7):
            verify_wing_back_native()
        if base_role is not None and base_role['phase'] == 'out_of_possession' and base_role['position_index'] in (8, 9):
            verify_tracking_midfielder_native()
        if base_role is not None and base_role['phase'] == 'in_possession' and base_role['position_index'] in (7, 9):
            verify_inside_forward_native()
        if base_role is not None:
            verify_matrix_role_native()
        if role_instructions is not None:
            verify_stored_role_pi_native()
        if 'possession_loss' in params:
            verify_possession_loss_native()
        if 'possession_gain' in params:
            verify_possession_gain_native()
        if 'goal_kick_length' in params:
            verify_goal_kicks_native()
        if 'crossing_style' in params:
            verify_crossing_native()
        if 'pressing_block' in params:
            verify_pressing_block_native()
        if 'final_third_delivery' in params:
            verify_final_third_native()
        if 'focus_play' in params:
            verify_focus_play_native()
        if 'wide_support' in params:
            verify_wide_support_native()
        blob = candidate.read_bytes()
        parsed = parse_tac_plaintext(after['.tac'])
    stamp = datetime.now(timezone.utc)
    safe_name = re.sub(r'[^\w .-]', '-', name, flags=re.UNICODE).strip(' .')[:90] or 'Tactic'
    if fm27_folder:
        normalized = unicodedata.normalize('NFKC', name)
        if '/' in normalized or '\\' in normalized or normalized in ('.', '..'):
            raise ValueError('Tactic name must be a single filename component without path separators or traversal.')
        safe_name = ''.join(c if c.isalnum() or c in ' -_' else '-' for c in normalized).strip(' .-_')
        while len(safe_name.encode('utf-8')) > 100:
            safe_name = safe_name[:-1]
        safe_name = safe_name.rstrip(' .-_')
        if not safe_name or safe_name.upper() in {'CON', 'PRN', 'AUX', 'NUL', *[f'COM{i}' for i in range(1, 10)], *[f'LPT{i}' for i in range(1, 10)]}:
            raise ValueError('Tactic name cannot form a safe filename.')
        directory = params.get('tactics_directory')
        if directory is not None and (not isinstance(directory, str) or not directory.strip()):
            raise ValueError('tactics_directory must name an existing FM27 Tactics directory.')
        output_dir = Path(directory).expanduser().resolve() if directory is not None else TEMPLATES.resolve()
        if not output_dir.is_dir():
            raise ValueError('FM27 Tactics directory does not exist; supply the existing directory explicitly.')
    else:
        output_dir = OUTPUTS / f'{stamp:%Y-%m-%d} — Pi FM tactic files'
    if not preview:
        output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / (f'{safe_name}.fmf' if fm27_folder else f'{safe_name} — {uuid4().hex[:8]}.fmf')
    receipt = (output_dir / '.fm-tactics-receipts' / f'{safe_name}.receipt.json') if fm27_folder else output.with_suffix('.receipt.json')
    def collision(path: Path) -> bool:
        target = unicodedata.normalize('NFKC', path.name).casefold().rstrip(' .')
        return path.exists() or path.is_symlink() or (path.parent.is_dir() and any(unicodedata.normalize('NFKC', p.name).casefold().rstrip(' .') == target for p in path.parent.iterdir()))
    if collision(output) or collision(receipt):
        raise FileExistsError('Output or receipt already exists; choose a different tactic name. No files were overwritten.')
    result = {
        'status': 'native_archive_written_and_roundtrip_verified', 'output_path': str(output),
        'receipt_path': str(receipt), 'output_sha256': sha(blob), 'output_bytes': len(blob),
        'destination': 'fm27_tactics' if fm27_folder else 'agent_outputs',
        'destination_mode': 'fm27_folder' if fm27_folder else 'agent_outputs',
        'output_directory': str(output_dir),
        'template_path': str(template), 'template_sha256': sha(source),
        'stored_football': inspect_stored_football(tac),
        'name': name, 'source_game_major': tac[11], 'native_header_hex': tac[:16].hex(),
        'mentality': MENTALITIES.get(parsed.get('pre_style_setup', {}).get('mentality_id')),
        'team_tackling': next(label for label, value in TACKLING_FLAGS.items() if value == tackling_selection(tac)[1]),
        **describe_defensive_line(tac),
        **describe_tempo(tac),
        **describe_passing(tac),
        **describe_possession_loss(tac),
        **describe_possession_gain(tac),
        **describe_stored_controls(tac),
        **describe_focus_play(tac),
        **describe_wide_support(tac),
        'defensive_line_mode': 'inherit' if defensive_line is None else 'explicit_change',
        'tempo_mode': 'inherit' if tempo is None else 'explicit_change',
        'passing_directness_mode': 'explicit_change' if 'passing_directness' in params else 'inherit',
        'base_role': base_role,
        'base_role_mode': 'explicit_change' if base_role is not None else 'inherit',
        'native_authoring': native_receipt,
        'native_authoring_mode': 'explicit_native_authoring' if native_receipt is not None else 'inherit',
        'phase_position': phase_position,
        'phase_position_mode': 'explicit_change' if phase_position is not None else 'inherit',
        'stored_role_instructions': role_instructions,
        'stored_role_instructions_mode': 'explicit_change' if role_instructions is not None else 'inherit',
        'possession_loss_mode': 'explicit_change' if 'possession_loss' in params else 'inherit',
        'focus_play_mode': 'explicit_change' if 'focus_play' in params else 'inherit',
        'wide_support_mode': 'explicit_change' if 'wide_support' in params else 'inherit',
        'possession_gain_mode': 'explicit_change' if 'possession_gain' in params else 'inherit',
        **{field + '_mode': 'explicit_change' if field in params else 'inherit' for field in STORED_CONTROLS},
        'edits': ['name'] + (['mentality'] if mentality is not None else []) + (['team_tackling'] if team_tackling is not None else []) + (['defensive_line'] if defensive_line is not None else []) + (['tempo'] if tempo is not None else []) + (['passing_directness'] if 'passing_directness' in params else []) + [field for field in STORED_CONTROLS if field in params] + (['focus_play'] if 'focus_play' in params else []) + (['wide_support'] if 'wide_support' in params else []) + (['base_role'] if base_role is not None else []) + (['stored_role_instructions'] if role_instructions is not None else []) + (['phase_position'] if phase_position is not None else []) + (['native_authoring'] if native_receipt is not None else []) + (['possession_loss'] if 'possession_loss' in params else []) + (['possession_gain'] if 'possession_gain' in params else []),
        'preserved': (['native payload version', 'original non-name metadata bytes', *unchanged]
                      if native_receipt is not None else
                      ['native payload version', 'unrequested phase positions' if phase_position is not None else 'formations', 'unrequested phase roles' if base_role is not None or phase_position is not None else 'phase roles', 'unrequested player instruction bytes' if role_instructions is not None or phase_position is not None else 'player instruction bytes', 'unrequested team instruction bits', *unchanged]),
        'verification': {'native_decode_roundtrip': True,
                         'all_unrequested_tactic_bytes_preserved': native_receipt['source_preservation']['source_outside_declared_native_footprints_preserved'] if native_receipt is not None else True,
                         'host_edits_preserved_native_authoring_result': native_receipt is not None,
                         'template_unchanged': True,
                         'game_load_verified': False, 'scope': 'Local native archive structural verification; FM27 import and semantic acceptance remain unverified.'},
        'codec': {'root': str(CODEC_ROOT), 'source_hashes': {f: sha((CODEC_ROOT / 'scripts' / f).read_bytes()) for f in CODEC_FILES}},
        'created_at': stamp.isoformat(),
    }
    if preview:
        result.update(status='preview', files_created=False)
        return result
    receipt.parent.mkdir(parents=True, exist_ok=True)
    output_created = receipt_created = False
    try:
        if native_receipt is not None:
            verify_native_authoring_receipt(native_receipt)
        if phase_position is not None:
            verify_phase_position_native()
        if donor_path is not None:
            if base_role['phase'] == 'in_possession':
                verify_base_role_native()
            else:
                verify_wing_back_native()
            verify_matrix_role_native()
        if role_instructions is not None:
            verify_stored_role_pi_native()
        if 'possession_loss' in params:
            verify_possession_loss_native()
        if 'possession_gain' in params:
            verify_possession_gain_native()
        if 'goal_kick_length' in params:
            verify_goal_kicks_native()
        if 'crossing_style' in params:
            verify_crossing_native()
        if 'pressing_block' in params:
            verify_pressing_block_native()
        if 'final_third_delivery' in params:
            verify_final_third_native()
        if 'focus_play' in params:
            verify_focus_play_native()
        if 'wide_support' in params:
            verify_wide_support_native()
        if template.read_bytes() != source:
            raise ValueError('Template changed before delivery; no output delivered.')
        if donor_path is not None:
            if donor_path.read_bytes() != donor_bytes:
                raise ValueError('Base-role donor changed before delivery; no output delivered.')
        if pi_donor_path is not None and pi_donor_path.read_bytes() != pi_donor_bytes:
            raise ValueError('Stored-role instruction donor changed before delivery; no output delivered.')
        if position_donor_path is not None and position_donor_path.read_bytes() != position_donor_bytes:
            raise ValueError('Phase-position donor changed before delivery; no output delivered.')
        with output.open('xb') as handle:
            output_created = True
            handle.write(blob)
        with receipt.open('x', encoding='utf-8') as handle:
            receipt_created = True
            json.dump(result, handle, ensure_ascii=False, indent=2)
            handle.write('\n')
    except BaseException:
        if receipt_created:
            receipt.unlink(missing_ok=True)
        if output_created:
            output.unlink(missing_ok=True)
        raise
    return result


def native_build() -> dict:
    """The game build the native edits run against, and the writer's functions that refuse on it."""
    if adviser_book is None:
        return {'state': 'pinned_only', 'reason': 'the reader at PI_FM_TACTIC_READER_ROOT has no adviser_book',
                'unavailable_functions': {}}
    state = adviser_book.state()
    return {**state, 'unavailable_functions': adviser_book.unavailable()}


def main() -> None:
    params = json.load(sys.stdin)
    action = params.get('action')
    if action == 'authoring_catalog':
        result = authoring_catalog(params)
    elif action == 'list_templates':
        rows, errors = [], []
        for path in sorted(TEMPLATES.glob('*.fmf')):
            try:
                rows.append(summarize(str(path)))
            except (ValueError, OSError, KeyError) as error:
                errors.append({'path': str(path), 'error': str(error)})
        result = {'templates': rows, 'excluded': errors, 'native_build': native_build(), 'supported_edits':['name', 'mentality', 'team_tackling', 'defensive_line', 'tempo', 'passing_directness', 'team_width', 'pressing_frequency', 'goal_kick_length', 'crossing_style', 'final_third_delivery', 'pressing_block', 'focus_play', 'wide_support', 'base_role', 'stored_role_instructions', 'phase_position', 'native_authoring', 'possession_loss', 'possession_gain'], 'game_load_verified': False}
    elif action == 'inspect':
        result = summarize(params.get('template_path', ''))
    elif action == 'generate':
        result = generate(params)
    else:
        raise ValueError('Expected list_templates, inspect or generate action.')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        details = {'error': str(error), 'type': type(error).__name__}
        if type(getattr(error, 'diagnostic', None)) is dict:
            details['diagnostic'] = error.diagnostic
        if adviser_book is not None and adviser_book.state()['state'] == 'unsupported':
            details['native_build'] = native_build()     # names the build and the command that maps it
        print(json.dumps(details), file=sys.stderr)
        sys.exit(1)
