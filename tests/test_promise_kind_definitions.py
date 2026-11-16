"""Original installed static source; no game attachment or UI label claim."""
import hashlib
from pathlib import Path
import re
import pytest
from fm_live_mcp import promise_kind_definitions as source

import _pinned_build
PLUGIN=_pinned_build.PLUGIN
BASE=0x100000000

class Original:
    def __init__(self):
        self.cells={}
        with PLUGIN.open('rb')as stream:
            for at,size,digest in source.SOURCE:
                stream.seek(0x5ed4000+at);raw=stream.read(size);assert hashlib.sha256(raw).hexdigest()==digest
                for i,value in enumerate(raw):self.cells[BASE+at+i]=value
    def read(self,address,size):
        try:return bytes(self.cells[address+i]for i in range(size))
        except KeyError as error:raise ValueError('Missing original promise-definition operand')from error


@pytest.mark.parametrize('kind',[1,16,25,69,120])
def test_known_compiled_definition_templates_are_exact_pinned_resource_entries(kind):
    old=Original();result=source.inspect(old.read,BASE,kind)
    RESOURCE=_pinned_build.language_template();text=RESOURCE.read_text();assert hashlib.sha256(RESOURCE.read_bytes()).hexdigest()==source.ENGLISH_SHA256
    match=re.search(r'^KEY-'+str(result['translation_id'])+r': (.*)$',text,re.M);assert match
    assert result['english_template']==match[1].split('[COMMENT',1)[0]
    assert result['state']=='compiled_english_definition_template'
    assert result['localized_UI_rendered']is result['placeholder_people_resolved']is result['lifecycle_evaluated']is False


@pytest.mark.parametrize('kind',[7,0,-1,-32768,32767,248,249])
def test_other_kinds_and_generic_default_preserve_unknown(kind):
    old=Original();result=source.inspect(old.read,BASE,kind)
    assert result['state']=='unmapped_native_kind'
    assert result['english_template']is result['translation_id']is None


@pytest.mark.parametrize('bad',[True,False,None,'1',1.0,[],{},-32769,32768])
def test_only_native_signed16_values_are_accepted(bad):
    with pytest.raises(ValueError,match='signed16'):source.inspect(None,BASE,bad)


@pytest.mark.parametrize('slot',range(len(source.SOURCE)))
def test_every_corrupted_definition_source_span_rejects(slot):
    old=Original();old.cells[BASE+source.SOURCE[slot][0]]^=1
    with pytest.raises(ValueError,match='native binding changed'):source.inspect(old.read,BASE,1)


def test_missing_table_operand_has_no_disk_or_zero_fill_fallback():
    old=Original();old.cells.pop(BASE+0x53b90a6)
    with pytest.raises(ValueError,match='Missing original'):source.inspect(old.read,BASE,7)


@pytest.mark.parametrize('base',[True,None,0,4097,1<<64,(1<<64)-8])
def test_invalid_image_base_rejects_before_reading(base):
    with pytest.raises(ValueError,match='image base'):source.inspect(None,base,1)
