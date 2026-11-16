"""Regression for the genuine four-byte-aligned kind11 native getter."""
import struct

import pytest

from fm_live_mcp import player_registration_source as source,world
from test_player_registration_source import current_context_reader,TEAM


@pytest.mark.parametrize('vector',('first','second'))
def test_exact_kind11_four_byte_code_pointer_is_supported(monkeypatch,vector):
    assert 0x22BEF64%8==4 and 0x22BEF64%4==0
    read,_,base=current_context_reader(monkeypatch,**{vector:((0x22BEF64,11),)})
    context,binding=source.current_league_context(read,base,dict(team_address=TEAM),'2030-11-26')
    assert context['source_state']=='available'and context['pending_context_kinds']==[11]
    assert binding['selector']==8


@pytest.mark.parametrize('rva',(0x22BEF68,0x22D3828))
def test_other_aligned_code_address_is_not_a_known_leaf(monkeypatch,rva):
    read,_,base=current_context_reader(monkeypatch,first=((rva,11),))
    context,binding=source.current_league_context(read,base,dict(team_address=TEAM),'2030-11-26')
    assert context['source_state']=='unavailable'and binding is None
    assert context['reason']=='unsupported_pending_player_context_kind'


@pytest.mark.parametrize('rva',(0x22BEF66,0x55EC,0x4AED934))
def test_misaligned_or_outside_text_code_pointer_rejects(monkeypatch,rva):
    read,_,base=current_context_reader(monkeypatch,first=((rva,11),))
    with pytest.raises(ValueError,match='code pointer'):
        source.current_league_context(read,base,dict(team_address=TEAM),'2030-11-26')


def test_object_pointer_still_requires_eight_byte_alignment(monkeypatch):
    read,memory,base=current_context_reader(monkeypatch,first=((0x22BEF64,11),))
    memory[0x110000]=struct.pack('<Q',0x110044)
    with pytest.raises(ValueError,match='source address'):
        source.current_league_context(read,base,dict(team_address=TEAM),'2030-11-26')


def test_exact_kind11_leaf_cannot_change_returned_kind(monkeypatch):
    read,_,base=current_context_reader(monkeypatch,first=((0x22BEF64,19),))
    with pytest.raises(ValueError,match='kind leaf changed'):
        source.current_league_context(read,base,dict(team_address=TEAM),'2030-11-26')


def test_late_code_pointer_change_is_detected(monkeypatch):
    read,memory,base=current_context_reader(monkeypatch,first=((0x22BEF64,11),))
    snapshot=world.ReadSet(read)
    assert source.current_league_context(snapshot,base,dict(team_address=TEAM),'2030-11-26')[0]['source_state']=='available'
    memory[0x110040+0x10]=struct.pack('<Q',base+0x22BEF68)
    with pytest.raises(ValueError,match='changed during read'):snapshot.verify()


@pytest.mark.parametrize('vector',('first','second'))
def test_genuine_kind12_leaf_skips_kind19_matching(monkeypatch,vector):
    read,_,base=current_context_reader(monkeypatch,**{vector:((0x22A11B4,12),)})
    context,binding=source.current_league_context(read,base,dict(team_address=TEAM),'2030-11-26')
    assert context['source_state']=='available'and context['pending_context_kinds']==[12]
    assert binding['selector']==8


@pytest.mark.parametrize('changed',(19,23))
def test_kind12_body_drift_cannot_skip_native_kind19_matching(monkeypatch,changed):
    read,_,base=current_context_reader(monkeypatch,first=((0x22A11B4,changed),))
    with pytest.raises(ValueError,match='kind leaf changed'):
        source.current_league_context(read,base,dict(team_address=TEAM),'2030-11-26')
