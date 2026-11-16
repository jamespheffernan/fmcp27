"""Complete current COMP counter ranking, separate from per-match lineup inference."""

import struct

from . import competition_scorers, competition_stages, players, teams

METRICS = ("starting_appearances", "minutes", "goals")
NATIVE_SPANS = (
    (
        0xF47A8C,
        bytes.fromhex(
            "ffc301d1f65704a9f44f05a9fd7b06a9fd83019108008052090400513f31027188910454f30301aaf43a02b0801246f92a2202b04a9906918b0000104c7969786b090c8b60011fd6"
        ),
    ),
    (0x538C1FE, bytes.fromhex("7201")),
    (0xF4809C, bytes.fromhex("49bd8d520901a072e883009182c5013421652011024ed294")),
    (0xF4B958, bytes.fromhex("21692011d73fd294")),
    (
        0x39DAED4,
        bytes.fromhex(
            "f44fbea9fd7b01a9fd430091f40302aaf30308aa1f0100f93f040071c1000054549fff97e10313aae20314aa628a559705000014449fff97e10313aae20314aadeb25597fd7b41a9"
        ),
    ),
    (
        0x39C2C18,
        bytes.fromhex(
            "080400511f7d0171c8000054081d409229d1009029d12691287968780200001408008052003d0013c0035fd6"
        ),
    ),
    (
        0x39CD54C,
        bytes.fromhex(
            "c80240f914815ef8e0031baab0d5ff97fc0300aac102148be00317aa0200805281ae5597e10300aa00e4002fa10000b4e00317aae2031caa23008052cb8f5597"
        ),
    ),
    (
        0xF31600,
        bytes.fromhex(
            "290500513f310271c8620054ca2202d04a4132918b0000104c7969786b090c8b60011fd6"
        ),
    ),
    (0x538BCE8, bytes.fromhex("4d02")),
    (0xF31F58, bytes.fromhex("28284039295442390801094b081d0013bd000014")),
    (
        0xF314B4,
        bytes.fromhex(
            "f85fbca9f65701a9f44f02a9fd7b03a9fdc3009100e4002fa16c00b4280440b9686cf837093d02b029c136912ac15c39290140f95f05007181000054294540f9292940a90200001429a946a94a0109cb1f0d8aebc26a0054280d088b080140f9686a00b4f70302aaf40303aaf50301aa01dc43f9f60300aa0228e039e00308aa40d12094400100b4080040f9081140f9c1108052020080d200013fd60800381e1f0d0071f3a79f1a0200001433008052e10315aae90317aae00316aacade43f9480d40b98bb989524b00a0721f010b6b4b768c524be7ae7204114b7a00e4002f61000054a805805219000014485940f9a80100b4e00308aa775ec797e90317aae10315aa00e4002fe80300aae00316aa4a1f8052ab0580521f01007168118a1a0b00001448e14339081900511f8d0071c8000054081d4092ca2202f04a211391487968b802000014481f8052290500513f310271c8620054ca2202d04a4132918b0000104c7969786b090c8b60011fd6285cc2390d0300142a3440b95f650171e9d3931a5f01086b4c0000540961003428304039c86000340001231e211840bd11010014287cc239000300142864c239fe0200142880c239fc020014293440b93f650171ead3931a3f01086b4c000054ea5e00342880c079e10200142a3440b95f650171e9d3931a5f01086b4c000054e95d00342870c0791f1900718b5d00542974c079fc0200142844c239e702001428b4c079e502001428304039885c0034203440bd00d8215ec10200142884c239de02001428304039a85b00342984c0793f0500714b5b00540001231e283d00120101231e0018211e0859a8520101271e0008211ed2020014203440bd00d8215ecf02001428c4c079cc0200142a3440b95f650171e9d3931a5f01086b4c000054e958003428d0c0791f1900718b58005429d4c079d40200142a3440b95f650171e9d3931a5f01086b4c00005489570034289cc079745800361f0500716a580054b70200142880c079b40200142868c239b20200142a3440b95f650171e9d3931a5f01086b4c000054a955003428f8c0791f1900714b55005429c4c0792ac8c0792bccc0794901090b29010b0b2001621e290be8d22101679e0008611e083d00120201631e0018621ec90000142830c2391f0500714b5300542910c17976020014284cc23995020014293440b93f650171ead3931a3f01086b4c0000540a520034287cc0797a020014293440b93f650171ead3931a3f01086b4c0000540a5100342878c0797202001428e4c079830200142884c07981020014293440b93f650171ead3931a3f01086b4c0000548a4f003428d4c079660200142a3440b95f650171e9d3931a5f01086b4c000054894e0034287cc0791f0500712b4e0054890c8052087d091b0001231e2878c0790101221e5b02001428b0c079680200142034403d4a02001428d0c079640200142a3440b95f650171e9d3931a5f01086b4c000054e94b0034a3feff97404d0034a82e403900e4002f484b0034a912c0792001221e0190241e0018211e35020014293440b93f650171ead3931a3f01086b4c000054ea4900342834403982000014293440b93f650171ead3931a3f01086b4c000054ea480034202840bdb7010014293440b93f650171ead3931a3f01086b4c000054ea470034201c40bdaf0100142860c2393a02001428f4c07938020014293440b93f650171ead3931a3f01086b4c0000546a46003428f0c0791d0200142890c0792e02001428f0c0792c02001428c0c0792a020014293440b93f650171ead3931a3f01086b4c000054aa44003428e4c0790f020014293440b93f650171ead3931a3f01086b4c000054aa4300342af84079483d00138a010034202c40bd00c0221e0101621e0018611e01106e1e2038601e2a0be8d24101679e0008611e0078611e0040621e0a59a8524101271e0018211e0101221e0008211e7b010014293440b93f650171ead3931a3f01086b4c0000546a4000342894c0794a0b8052087d0a1b0001221e2809090b08791f53dc0100142a3440b95f650171e9d3931a5f01086b4c000054c93e0034202c40bd2134403d21d8217e0038211ef1010014293440b93f650171ead3931a3f01086b4c0000546a3d003428c0c079d50100142028403dca0100142a3440b95f650171e9d3931a5f01086b4c000054293c003428f84079e83b0034202c40bd00c0221e083d00130101621e0018611e01106e1e2038601e280be8d20101679e0008611e0078611eeb010014293440b93f650171ead3931a3f01086b4c000054aa390034283040394a0b8052087d0a1b0001231eb7010014293440b93f650171ead3931a3f01086b4c0000544a38003428b4c079ac0100142800c179bd010014293440b93f650171ead3931a3f01086b4c0000540a370034201840bd280100142030403d970100142858c2391f0d00712b360054295cc2398a0c8052297d0a1b2001621e081d0012c1010014293440b93f650171ead3931a3f01086b4c000054aa34003428d0c0798f010014293440b93f650171ead3931a3f01086b4c000054aa33003428a8c07987010014293440b93f650171ead3931a3f01086b4c000054aa32003428ecc0797f010014293440b93f650171ead3931a3f01086b4c000054aa310034289cc079770100142808c17988010014293440b93f650171ead3931a3f01086b4c0000546a3000342800c1796d010014293440b93f650171ead3931a3f01086b4c0000546a2f003428ccc07965010014293440b93f650171ead3931a3f01086b4c0000546a2e003428c8c0795d010014293440b93f650171ead3931a3f01086b4c0000546a2d003428d8c0795501001428fcc07966010014293440b93f650171ead3931a3f01086b4c0000542a2c003428b0c0794b010014293440b93f650171ead3931a3f01086b4c0000542a2b00342888c0794301001428d8c07954010014293440b93f650171ead3931a3f01086b4c000054ea29003428fcc07939010014293440b93f650171ead3931a3f01086b4c000054ea28003428bcc07931010014293440b93f650171ead3931a3f01086b4c000054ea27003428acc07929010014293440b93f650171ead3931a3f01086b4c000054ea260034203040bda7000014293440b93f650171ead3931a3f01086b4c000054ea250034202440bd9f000014293440b93f650171ead3931a3f01086b4c000054ea2400342874c079110100142874c07922010014293440b93f650171ead3931a3f01086b4c000054aa23003428dcc07907010014293440b93f650171ead3931a3f01086b4c000054aa22003428a4c079ff000014293440b93f650171ead3931a3f01086b4c000054aa2100342898c079f70000142a3440b95f650171e9d3931a5f01086b4c000054a92000342884c0791f0500714b200054201840bd083d0012df0000142804c179fc0000142878c239fa000014293440b93f650171ead3931a3f01086b4c000054aa1e0034202040bd65000014293440b93f650171ead3931a3f01086b4c000054aa1d003428a0c079d7000014280cc179e8000014293440b93f650171ead3931a3f01086b4c0000546a1c0034280cc179cd000014202040bddf000014202440bddd00001428e8c079da000014293440b93f650171ead3931a3f01086b4c000054aa1a00342870c079bf000014293440b93f650171ead3931a3f01086b4c000054aa1900342884c079b70000142870c079c80000142898c079c60000142888c079c40000142894c239c200001428284039295442390801094b081d0013bd000014293440b93f650171ead3931a3f01086b4c0000540a17003428c4c0792ac8c0792bccc0794801080b08010b0b0001621ec82202d0012546fd0008611e0040621e9c000014293440b93f650171ead3931a3f01086b4c000054ea140034288cc23991000014288cc239a200001428b8c079a0000014293440b93f650171ead3931a3f01086b4c0000546a13003428e8c07985000014293440b93f650171ead3931a3f01086b4c0000546a120034202c40bd2134403d21d8217e0038211e8856a8520101271e0008211e7a000014293440b93f650171ead3931a3f01086b4c000054aa10003428e0c0796f000014293440b93f650171ead3931a3f01086b4c000054aa0f003428b8c07967000014293440b93f650171ead3931a3f01086b4c000054aa0e003428f4c0795f000014288cc07970000014289cc0796e0000142a3440b95f650171e9d3931a5f01086b4c000054290d00342884c079d40e00361f050071ca0e00546400001428e0c0796100001428dcc0795f00001428a0c0795d000014293440b93f650171ead3931a3f01086b4c0000540a0b003428c4c079420000142860c2391f0500716b0a00542964c2398a0c8052297d0a1b2d00001428c4c07929c8c0792accc0792801080b08010a0b48000014293440b93f650171ead3931a3f01086b4c0000546a0800342890c0792d000014201c40bd3f000014293440b93f650171ead3931a3f01086b4c0000542a070034288cc07923000014286cc2393400001428bcc079320000142878c07930000014201840bd2f00001428ecc0792c0000142830c2392a00001428d4c07928000014287cc079260000142848c2391f0500718b0400542914c1792001221e081d00120101231e0f000014202c403d00d8217e1c000014293440b93f650171ead3931a3f01086b4c000054ca0200342868c2394a0b8052087d0a1b0001221e2101231e0018211e0f0000142858c2390c0000142834c2390a00001428c8c0790800001428ccc079060000142874c239040000142838c239020000142870c2390001221efd7b43a9f44f42a9f65741a9f85fc4a8c0035fd62894c0790001221e0190241ee8ffff171f190071cbfeff5429a0c0790600001400e4002ff2ffff171f1900710bfeff542988c0798a0c8052297d0a1b2001621e083d00120101631e0018611e0040621ee7ffff17"
        ),
    ),
    (
        0x538BC90,
        bytes.fromhex(
            "27015a01a70000005b00d9020d03090313020d0011002f001b007a001300a102140307012a006b0247024e00a50028006d02db02ab000f03e30043007300e3020f03e902bb00f102030326000d004b020b037800000001034d028c004902410005030703a900e502ae02ac0231003e000f000f00d3000f030f035900e7028a003302e100e102df02cf02d5005d003d01f4025201cb003d02b101050245023502a9019f027d019d02df00d102c702d700dd0282009600c3017501e5008e0095026501c300ba025202eb01b002c102ed0029011401020002003102db012f028d0285021f01b2028f01970177026302fd01ed016f021d02e3014801a7015001110285015c01250287012702bb011502f5016d01b9019f01cb01d301"
        ),
    ),
    (
        0xF5301C,
        bytes.fromhex(
            "ff0302d1fc6f02a9fa6703a9f85f04a9f65705a9f44f06a9fd7b07a9fdc30191e70f00f9f40306aafb0304aaf70301aaf80300aab64f41a9480840b9c80600b9281840b91f050031e04d0054e8aa4239e972413909012837e8010035e8c24239a8010035e8ca42391f0100716800881a09000014284c0035e8c24239e84b0035e9ca4239e8be4239294c0035480000346800084b081d00131c7da80ac93640b929011c0bc93600b91f0900716a0000541a0080521500001468558552687c081b097d1053287d480b9fa3286bca010054e806c179081500110001621e280be8d20101679e0018611e0190631e0020611eaa000054e82e423968000035e87e4239484700343a00805209df43f92a3140f928e14339f30b00f9ca0000b41f3900712a0080524a21c81a6b008852060000141f5900712a0080524a21c81a8b0682520b0ca0724a010b0a4499407a803b0054f90302aaf50305aa680240f9087143f9e00313aa00013fd6400400b4e10313aa33008052e00318aa220080528e92ff97e8324239093440392801080b08340039c80640b9080400b90828403908050011082800399a020034082c403908050011082c0039e806c17908150011e9cc8c52c9ccac72087d299b09fd7fd308fd62930801090b1f05007108c59f1a091040792801280b08100079940000b50500001413008052740000b488ee4039c88a0239da020034e806c17908150011e9cc8c52c9ccac72087d299b09fd7fd308fd62930801090b1f05007108c59f1aca9ac2395f81286b091d00134ac1891aca9a0239ca9ec2395f050031600000545f01096b4d000054c89e0239c82a403908050011c82a0039e8324239c93640392901080bc9360039e9d2413909010036c992423929050011c992023988000035c88e423908050011c88e0239e8be423988000034c856423908050011c8560239e82e42394802003493000034093040392901080b09300039c93240392801080bc8320039540100b408df43f9005940f9e10314aab2ddaf94a0000034e82e4239c99642392801080bc8960239e8364239c95a42392801080bc85a0239e83a4239c95e42392801080bc85e0239e8764239c96242392801080bc8620239e87a4239c96642392801080bc8660239e87e423988000034c96a42392901080bc96a0239e90f40f92a81c039f30315aa8a000034c96e423929010a0bc96e0239e90f40f92985c039f50319aa89000034cb7242396b01090bcb7202395f01096bad000054ca7642394a050011ca760239050000148a000054ca7a42394a050011ca7a0239eb9a4239ea9e42397f050071400000540a0100347f050071cb7e42396b158b1acb7e0239cb8242396a010a0bca820239ea1a40b95f011b6b81000054ca8642394a050011ca860239fa060034ea06c1794a150011ebcc8c52cbccac724a7d2b9b4bfd7fd34afd62934a010b0b5f0500714bc59f1a6a1d0012cc1240798c012b0bcc120079cc2e40398c050011cc2e0039cc1241798b012b0bcb120179ec2e4239eb324239c18e40bd2084000f2284000f821d064e621d0a4e021d0e4e4110212e2118000ec18e00bd9ff30071a300005489000035c942423929050011c9420239e97640b9cd3a4229a901092ac91200b9e97640b9c901092ac91600b9c916417929010a0bc9160179801d024e601d0a4ec11249bc001d0e4e0010212e0018000ec01209bc01df43f9022be039e00315aa4f492094e8864239000100b4090843792901080b09080379e98242390a1443794901090b09140379e9ea4239eaee4239eb1a4339ec1e4339ed424239ee464239ef8e4239c082c33c2101271e411d064e611d0a4e811d0e4e011d124ea11d164ec11d1a4ee11d1e4e0084614ec082833ce8924239c99240792801080bc892007973000034e06a40bd05000014e06a40bd081d02f001b54fbd0008211e0190241e0008211e0800381ee9964239eade4239ebd64239ecda4239ed7e4339ee824339cd010d0bee864339ef8a4339ee010e0beff242390001271e201d064e601d0a4e801d0e4ea01d124ec01d164ec1a2c43c401d1a4ee01d1e4e2084604ec0a2843ce83a0391e96e0291e022433d0005400de82a0391e1f24c7c0038410ee192497c20040a6e2019400d001d400dc1a2c53c2010202ec0a2853ce8720291e9820291ea6a0391eb7a0391e0b24c7c0009400d200d400d4011400d6015400de1724d7c20040e6ec1a2c63c2010202ec0a2863ce01e40bdc10a432d0028211ec01a00bde02640bd0028221ec01e00bde02e40bdc10a452d0028211ec02a00bde03240bd0028221ec02e00bde02a40bdc10a442d0028211ee8664339c9f640792801080bc8f60079e8764339c9fa40792801080bc8fa0079e8c64339c9fe40792801080bc8fe0079e8d64339c90241792801080bc8020179e8b24339c90641792801080bc8060179e8b64339c90a41792801080bc80a0179e8f64239c90e41792801080bc80e0179c02200bde02240bd0028221ec02600bde03640bdc13240bd0028211ec03200bd1a2749f933008052611e0013e0031aaac2f70094600000b408204039e8030037681e0012730600111f0d0171e3feff5408df43f9085940f9080300b408e543f9c80200b4089d40f9005940f9600200b43b00805201008012220080526442ad94e00100b41a2449f9ba0100b433008052611e0013e0031aaaa8f70094600000b408204039e8110037681e0012730600111f0d0171e3feff543b00805208df43f9085940f9e80200b408e543f9a80200b4089d40f9005940f9400200b401008012220080524a42ad94c00100b41a2449f99a0100b433008052611e0013e0031aaa8ef70094600000b408204039480e0037681e0012730600111f0d0171e3feff54130080529b010034012749f9022b49f9ff230039e81b41a9e80300f9e00318aae30317aae40315aae50314aae70316aa710000941302003408df43f9085940f9e80400b408e543f9f30b40f9480200b4089d40f9005940f9e00100b401008012220080522242ad94600100b4012449f91d000014fd7b47a9f44f46a9f65745a9f85f44a9fa6743a9fc6f42a9ff030291c0035fd6010080d213000014295940f9690400b428f94e391f650071290080522921c81a0a8890524a41a07229010a0a2499407a61c3ff54089501511f0d00710499427ae1c2ff541d000014010080d2f30b40f908df43f9085940f9c80100b408e543f9880100b4089d40f9005940f9200100b4f90313aaf30301aa0100801222008052f641ad94600200b4022849f912000014020080d2120000141f7d0071290080522821c81a098890524941b0720801090a0499407a41bfff54f90302aaf50305aa13008052000080d2f4c3ffb520feff17020080d2e10313aaf30319aa28008052a8630039b30b00f9e00318aae30317aae40315aae50314aae60f40f9e70316aafd7b47a9f44f46a9f65745a9f85f44a9fa6743a9fc6f42a9ff03029111000014330080529bf2ff359effff171b00805276ffff17e83242391f010071fa079f1ac5fdff17e9be42390801094ba5fdff171c008052aafdff172801084ba1fdff17"
        ),
    ),
)
SCOPE = (
    "All physical rows in the selected current COMP-owned resident PERSON counter pool. "
    "Starting appearances follow the official competition stat enum45; this does not decode "
    "formal starting XIs for individual fixtures. Minutes are accumulated native playing-duration "
    "values. The native season discriminator is not a calendar date interval or completed-season "
    "guarantee. Primary player League categories and current-club rosters are not substituted. "
    "Last-associated TEAM is not attribution of all counters after transfers. Counter anomalies "
    "and unsupported identities remain explicit. No native sort, refresh, row creation or game writes."
)


def verify_native(read, base):
    for rva, expected in NATIVE_SPANS:
        if read(base + rva, len(expected)) != expected:
            raise ValueError(
                f"Competition ranking native getter/label changed at {rva:#x}"
            )


def decode_row(raw):
    if not isinstance(raw, bytes) or len(raw) != 172:
        raise ValueError("Competition PERSON counter row must be exactly172 bytes")
    apps, subs = raw[10], raw[149]
    starts = (apps - subs + 128) % 256 - 128
    minutes = struct.unpack_from("<i", raw, 52)[0]
    return {
        "starting_appearances": starts,
        "minutes": minutes,
        "goals": raw[12],
        "metric_states": {
            "starting_appearances": "anomalous_substitutes_exceed_appearances"
            if subs > apps
            else "anomalous_negative_native_signed_result"
            if starts < 0
            else "official_native_counter",
            "minutes": "anomalous_negative_native_value"
            if minutes < 0
            else "stored_native_duration_minutes",
            "goals": "stored_native_unsigned_counter",
        },
        "raw": {
            "appearance_counter_u8": apps,
            "substitute_appearance_counter_u8": subs,
            "starting_appearances_formula_signed8": starts,
            "minutes_signed32": minutes,
            "goals_unsigned8": raw[12],
        },
    }


def options(sort_by, order, minutes_over, limit):
    if sort_by not in METRICS:
        raise ValueError("sort_by must be starting_appearances, minutes or goals")
    if order not in ("ascending", "descending"):
        raise ValueError("order must be ascending or descending")
    if minutes_over is not None and (
        type(minutes_over) is not int or not 0 <= minutes_over <= 2**31 - 1
    ):
        raise ValueError(
            "minutes_over must be null or a nonnegative signed32 integer; threshold is exclusive"
        )
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("limit must be an integer in1..100")


def rank(
    candidates,
    sort_by="starting_appearances",
    order="ascending",
    minutes_over=None,
    limit=10,
):
    options(sort_by, order, minutes_over, limit)
    if (
        not isinstance(candidates, list)
        or len(candidates) > competition_scorers.MAX_CANDIDATES
    ):
        raise ValueError("Competition ranking source budget exceeded")
    ids = set()
    ordinals = set()
    known = []
    unknown = []
    below = []
    anomaly_count = 0
    for row in candidates:
        index, ordinal = row["person_index"], row["source_ordinal"]
        if (
            type(index) is not int
            or index < 0
            or index in ids
            or type(ordinal) is not int
            or ordinal < 0
            or ordinal in ordinals
        ):
            raise ValueError("Ambiguous competition PERSON/source row identity")
        ids.add(index)
        ordinals.add(ordinal)
        for key in METRICS:
            if row.get(key) is None and row["metric_states"][key].startswith(
                "unavailable_"
            ):
                continue
            if type(row.get(key)) is not int:
                raise ValueError("Missing raw signed/unsigned competition metric")
        anomalies = [
            key for key in METRICS if row["metric_states"][key].startswith("anomalous_")
        ]
        anomaly_count += bool(anomalies)
        if (
            row["metric_states"][sort_by].startswith(("anomalous_", "unavailable_"))
            or minutes_over is not None
            and row["metric_states"]["minutes"].startswith(
                ("anomalous_", "unavailable_")
            )
        ):
            unknown.append(
                {
                    "person_index": index,
                    "source_row_index": ordinal,
                    "reason": "unavailable_or_anomalous_metric_for_filter_or_order",
                    "anomalous_metrics": anomalies,
                    "raw": row["raw"],
                }
            )
            continue
        if minutes_over is not None and row["minutes"] <= minutes_over:
            below.append(index)
            continue
        known.append(row)
    known.sort(
        key=lambda r: (
            (r[sort_by] if order == "ascending" else -r[sort_by]),
            r["person_index"],
        )
    )
    cutoff = known[min(limit, len(known)) - 1][sort_by] if known else None
    chosen = (
        [
            r
            for r in known
            if (r[sort_by] <= cutoff if order == "ascending" else r[sort_by] >= cutoff)
        ]
        if cutoff is not None
        else []
    )
    result = []
    last = None
    place = 0
    for position, row in enumerate(chosen, 1):
        if row[sort_by] != last:
            place = position
        result.append({**row, "rank": place})
        last = row[sort_by]
    return {
        "rows": result,
        "metric": sort_by,
        "order": order,
        "minutes_over": minutes_over,
        "minutes_filter": "strictly_greater_than"
        if minutes_over is not None
        else "not_applied",
        "physical_count": len(candidates),
        "qualified_known_count": len(known),
        "below_or_equal_minutes_count": len(below),
        "unknown_filter_or_order_count": len(unknown),
        "anomalous_metric_row_count": anomaly_count,
        "unknown_rows": unknown,
        "limit": limit,
        "selected_count": len(result),
        "cutoff_value": cutoff,
        "cutoff_ties_added": max(0, len(result) - limit),
        "cutoff_ties_complete": True,
        "entire_pool_scanned_before_ranking": True,
        "all_filter_and_order_values_known": not unknown,
        "tie_order": "canonical_PERSON_index; equal metric values retain equal rank",
    }


def collect(read, base, saved):
    verify_native(read, base)
    coverage, candidates = competition_scorers.collect(read, base, saved)
    if coverage["source_state"] != "available":
        return {**coverage, "limitations": SCOPE}, []
    context, runtime, binding = competition_stages.runtime_context(read, base, saved)
    stats = competition_scorers._pointer(players.u64(read(runtime + 0x390, 8)))
    start, end, capacity = struct.unpack("<QQQ", read(stats + 0x1278, 24))
    if (end - start) // 8 != len(candidates):
        raise ValueError("Competition pool count changed")
    pointers = (
        tuple(
            value
            for cursor in range(start, end, 16384)
            for (value,) in struct.iter_unpack(
                "<Q", read(cursor, min(16384, end - cursor))
            )
        )
        if end > start
        else ()
    )
    if len(pointers) != len(set(pointers)):
        raise ValueError("Duplicate competition counter pointers")
    result = []
    team_cache = {}
    for candidate, pointer in zip(candidates, pointers, strict=True):
        if pointer + 172 >= 1 << 64:
            raise ValueError("Competition row span overflows")
        raw = read(pointer, 172)
        if (
            struct.unpack_from("<I", raw)[0] != candidate["person_index"]
            or raw[12] != candidate["goals"]
        ):
            raise ValueError("Competition counter ownership changed")
        decoded = decode_row(raw)
        team_index = candidate["last_associated_team_index"]
        if team_index not in team_cache:
            if team_index is None:
                team_cache[team_index] = None
            else:
                team_cache[team_index] = teams.by_index(read, base, team_index)[0]
        if team_cache[team_index] is None:
            decoded["metric_states"]["starting_appearances"] = (
                "unavailable_native_getter_TEAM_precondition"
            )
            decoded["starting_appearances"] = None
            decoded["raw"]["native_getter_zero_default_for_missing_TEAM"] = 0
        result.append(
            {
                **candidate,
                **decoded,
                "_raw_hex": raw.hex(),
                "last_associated_team": team_cache[team_index],
            }
        )
    return {
        **coverage,
        "source_population": "every physical current COMP-owned resident PERSON counter row",
        "starting_appearances_source": {
            "native_enum": 45,
            "native_English_resource_key": 554500,
            "native_English_label": "Starting Appearances",
            "encoding": "signed8(u8 appearance counter minus u8 substitute counter)",
        },
        "minutes_source": "signed32 cumulative native playing-duration minutes",
        "whole_completed_season_verified": False,
        "universal_season_rollover_semantics": "not_established",
        "formal_starting_XI_per_fixture": "not_decoded",
        "match_completion": "not_evaluated",
        "primary_League_category_used": False,
        "limitations": SCOPE,
    }, result
