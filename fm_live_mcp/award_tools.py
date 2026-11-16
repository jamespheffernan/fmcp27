"""Bounded live AWARD definition search and canonical-reference readback."""
from datetime import datetime, timezone
from typing import Annotated, Any
import secrets

from mcp.types import ToolAnnotations
from pydantic import Field

from . import awards, database, players, world


def find_awards(bridge, session_id, name=None, native_id=None, competition_native_id=None,
                nation_native_id=None, period_code=None, recipient_type_code=None,
                category_code=None, max_matches=20, record_budget=1000, cursor=None):
    from .bridge import BridgeError, integer
    integer(max_matches,1,100,'max_matches'); integer(record_budget,1,1000,'record_budget')
    for key,value in [('native_id',native_id),('competition_native_id',competition_native_id),('nation_native_id',nation_native_id)]:
        if value is not None:integer(value,1,0xffffffff,key)
    for key,value in [('period_code',period_code),('recipient_type_code',recipient_type_code),('category_code',category_code)]:
        if value is not None:integer(value,-128,127,key)
    if name is not None and (not isinstance(name,str) or not 1<=len(name)<=128 or any(ord(c)<32 or ord(c)==127 for c in name)):
        raise BridgeError('Award name must contain1–128 characters without controls.')
    if name is not None:
        try:
            if len(name.encode('utf-8'))>128:raise BridgeError('Award name must fit within128 UTF-8 bytes.')
        except UnicodeError as exc:raise BridgeError('Award name must be valid Unicode.') from exc
    criteria=dict(name=name,native_id=native_id,competition_native_id=competition_native_id,
                  nation_native_id=nation_native_id,period_code=period_code,
                  recipient_type_code=recipient_type_code,category_code=category_code)
    with bridge.lock,bridge._read_scope(session_id):
        process=bridge._current(session_id); tables=bridge._player_layout(process);base=tables[0]-players.RVA[0]
        read,save,_=bridge._world_state(process,tables)
        try:
            info=database.table(read,base,'awards');start=0
            if cursor is not None:
                saved=bridge.database_cursors.get(cursor)
                if not saved or saved['kind']!='award_lookup' or saved['identity']!=info['identity'] or saved['criteria']!=criteria:
                    raise ValueError('Award cursor expired or belongs to another query')
                start=saved['index']
            end=start;pending=[];cache={};unnamed=0
            while end<min(info['count'],start+record_budget):
                row,binding=awards.record(read,base,world.pointer(read,info['start']+end*8),cache=cache)
                if binding['database_index']!=end:raise ValueError('Award table slot/index mismatch')
                end+=1;unnamed+=not row['name']
                if native_id is not None and row['native_id']!=native_id:continue
                if name is not None and not any(name.casefold() in (row[k] or '').casefold() for k in ('name','short_name')):continue
                if competition_native_id is not None and (row['competition'] or {}).get('native_id')!=competition_native_id:continue
                if nation_native_id is not None and (row['nation'] or {}).get('native_id')!=nation_native_id:continue
                if any(code is not None and row[field]['native_code']!=code for field,code in [('award_period',period_code),('recipient_type',recipient_type_code),('award_category',category_code)]):continue
                pending.append((row,binding))
                if len(pending)==max_matches:break
            read.verify()
        except (ValueError,IndexError,KeyError,TypeError) as exc:
            raise BridgeError(f'Award query rejected; no partial result returned: {exc}') from exc
        bridge._current(session_id)
        bridge._reserve_geographic_references([b for _,b in pending])
        rows=[bridge._publish_geographic(row,binding,tables) for row,binding in pending]
        next_cursor=None
        if end<info['count']:
            if len(bridge.database_cursors)>=100:bridge.database_cursors.clear()
            next_cursor=secrets.token_urlsafe(12)
            bridge.database_cursors[next_cursor]=dict(kind='award_lookup',criteria=criteria,identity=info['identity'],index=end)
        return dict(session_id=session_id,observed_at=datetime.now(timezone.utc).isoformat(),save=bridge._public_save(save),
                    awards=rows,count=len(rows),total_records=info['count'],scanned_records=end-start,
                    unnamed_records_examined=unnamed,next_cursor=next_cursor,complete_table_scan=end==info['count'],
                    stop_reason='table_end' if end==info['count'] else 'match_limit' if len(rows)==max_matches else 'record_budget',
                    criteria=criteria,limitations=awards.SCOPE)


def get_award(bridge,session_id,award_ref):
    from .bridge import BridgeError
    with bridge.lock,bridge._read_scope(session_id):
        process=bridge._current(session_id);tables=bridge._player_layout(process);base=tables[0]-players.RVA[0]
        read,save,_=bridge._world_state(process,tables)
        saved=bridge.geographic_refs.get(award_ref)
        if not saved or saved.get('kind')!='award' or saved['tables']!=tables:
            raise BridgeError('Unknown or expired award reference; repeat fm_find_awards.')
        try:
            row,binding=awards.record(read,base,saved['address'])
            if binding['identity']!=saved['identity'] or binding['database_index']!=saved['database_index']:
                raise ValueError('Award identity changed')
            read.verify()
        except (ValueError,IndexError,KeyError,TypeError) as exc:
            bridge.geographic_refs.pop(award_ref,None)
            raise BridgeError(f'Award reference rejected: {exc}') from exc
        bridge._current(session_id)
        return dict(session_id=session_id,observed_at=datetime.now(timezone.utc).isoformat(),save=bridge._public_save(save),
                    award=bridge._publish_geographic(row,binding,tables,ref=award_ref),limitations=awards.SCOPE)


def register_award_tools(mcp,bridge):
    read=ToolAnnotations(readOnlyHint=True,destructiveHint=False,openWorldHint=False)

    @mcp.tool(annotations=read)
    def fm_find_awards(
        session_id: str, name: str|None=None,
        native_id: Annotated[int|None,Field(strict=True,ge=1,le=4294967295)]=None,
        competition_native_id: Annotated[int|None,Field(strict=True,ge=1,le=4294967295)]=None,
        nation_native_id: Annotated[int|None,Field(strict=True,ge=1,le=4294967295)]=None,
        period_code: Annotated[int|None,Field(strict=True,ge=-128,le=127,description='Stored award period code; returned labels include Of The Month, Season, Year or Competition. Not proof of a scheduled or completed award.')]=None,
        recipient_type_code: Annotated[int|None,Field(strict=True,ge=-128,le=127)]=None,
        category_code: Annotated[int|None,Field(strict=True,ge=-128,le=127)]=None,
        max_matches: Annotated[int,Field(strict=True,ge=1,le=100)]=20,
        record_budget: Annotated[int,Field(strict=True,ge=1,le=1000)]=1000,
        cursor: str|None=None,
    )->dict[str,Any]:
        """Find live award definitions by stored Unicode name/short-name substring, canonical ID, competition/nation ID and raw period/category/recipient codes. Omit filters to enumerate all definitions, including unnamed records. Returns award_ref and source-labelled categories with canonical competition/nation/continent links. An award definition or Of The Month/Season/Year period does not identify an actual winner or prove it took place. Winner history and runtime decisions remain not_decoded. Follow every next_cursor with identical filters, including empty pages;100matches/1000records per call. Read-only canonical table/type/identity and consumed-byte checks; no UI, game functions or saved-file fallback."""
        return find_awards(bridge,session_id,name,native_id,competition_native_id,nation_native_id,
                           period_code,recipient_type_code,category_code,max_matches,record_budget,cursor)

    @mcp.tool(annotations=read)
    def fm_get_award(session_id: str,award_ref: str)->dict[str,Any]:
        """Recheck one canonical live AWARD reference from fm_find_awards. Returns stored definition names, category, period, recipient type and nullable canonical nation/competition/continent relationships. These are award definitions, not winners. Winner history remains explicitly not_decoded; unknown enums and null/empty names stay distinct. References expire after detach/reload or identity changes. No UI, game execution, saved-file decode or writes."""
        return get_award(bridge,session_id,award_ref)
