"""Finite native source bindings for retained per-attempt UI XgValue."""

NATIVE_XG_VALUE_SPANS = (
    (0x1a2104, bytes.fromhex('092340bde02300912041201e9e870995e0630091e2230091e1aa8952a16aa87270540995')),
    (0x4403f88, bytes.fromhex('e923bd6df44f01a9fd7b02a9fd8300910840201ef30300aa4dffff9708a00191680a00bd680200f9e00313aafd7b42a9f44f41a9e923c36cc0035fd6')),
    (0x493a9c4, bytes.fromhex('4000c03d0000803d202c40bd001000bd0390022928d0403908700039c0035fd6')),
    (0x493ac90, bytes.fromhex('ff0301d1f65701a9f44f02a9fd7b03a9fdc30091f30301aaf40300aa092040a9080109cb08fd44d3695595524955b572087d091be80f00b9200040f9080040f9081940f9e13300918200805200013fd6952240a9600240f9bf0208eb60070054080040f9081940f9e10315aa8200805200013fd6a01240bde00f00bd600240f9080040f9081940f9e13300918200805200013fd6a01640bde00f00bd600240f9080040f9081940f9e13300918200805200013fd6a02240bde00f00bd600240f9080040f9081940f9e13300918200805200013fd6600240f9080040f9081940f9a19200918200805200013fd6600240f9080040f9081940f9a1a200918200805200013fd6600240f9080040f9081940f9b5b20091e10315aa2200805200013fd6600240f9091040b93f010071e8179f1a29010035890640f9b5120091bf0209eb01f9ff5404000014081040b91f010071e8179f1ae00308aafd7b43a9f44f42a9f65741a9ff030191c0035fd6')),
    (0x495db70, bytes.fromhex('2080052d')),
    (0x48da79c, bytes.fromhex('680240f9804a44bd01102e1e2238201e033140bd2338231e4208231e2138221e2038201e003100bd814a44bd2028201e804a04bd')),
    (0x493eae8, bytes.fromhex('c03240bd616240bd0128211e616200bd570100b4e11e40bd0128211ee11e00bdc8d240391f11007180000054e12240bd0128211ee12200bd')),
)

def verify_native_xg_value(read, base):
    for rva, expected in NATIVE_XG_VALUE_SPANS:
        if read(base + rva, len(expected)) != expected:
            raise ValueError('Retained native XgValue source binding changed')

def value_definition():
    return {
        'field': 'native_xg_value', 'official_frontend_property': 'XgValue',
        'property_key': '0x43554d57', 'source': 'retained shot48+0x20 from model source+0x2c',
        'unit': 'unscaled native float32 per-attempt XgValue',
        'aggregate_equivalence': False,
        'aggregate_source': 'independent team/player xG accumulates context-adjusted source+0x30',
        'credited_contribution_state': 'not_retained_in_checked_shot_representation',
        'scope': 'Original compiled exporter and retained writer; live-rendered UI not observed',
        'native_binary_sha256': '774cacde63567fd3901c47719e7a6ed94cc3a0a62e9b94989dcac6b4890ec0e1',
    }
