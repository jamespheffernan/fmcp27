"""Private candidate: reciprocal used-length budget separate from spare capacity.

Package copy of `evidence/knowledge-fow-used-ranges-20261109/reciprocal_used_ranges.py` (lane codex/continuous-knowledge-20261109, commit 268c3a2, SHA256 8354541254306d1bcaa761d8cc465c243195b38e7347f68b9d77620d414178b6); the code is unchanged.


This evidence-only subclass preserves the original helper/node/score semantics.
It does not alter immutable privatec66b or any installed/public source.
"""
USED_LIMIT=4096
CAPACITY_LIMIT=2_000_000


def source_type(approved_source_type,core):
    class UsedReciprocalSource(approved_source_type):
        def _reciprocal_used_bounds(self,address):
            # Bounds still verify begin/end/capacity geometry and a finite
            # canonical-sized allocation ceiling. Only used entries count
            # toward the existing4096 traversal budget; spare slots are unread.
            start,count=self.reader.bounds(address,8,CAPACITY_LIMIT)
            if count>USED_LIMIT:
                raise core.SourceUnavailable('Reciprocal used-entry reader budget exceeded')
            return start,count

        def reciprocal_score(self):
            self.ordinary_primary()
            start,count=self._reciprocal_used_bounds(self.subject.primary+0xc8)
            owner_uid=self.owner.person.identity[1]
            for i in range(count-1,-1,-1):
                row=self.knowledge_node(start+8*i,required=True)
                if self.u32(row+4)!=owner_uid:
                    continue
                if self.u32(row)!=self.subject.person.identity[0]:
                    raise core.SourceUnavailable('Reciprocal node subject ordinal changed')
                own_start,own_count=self._reciprocal_used_bounds(self.fow_record)
                if not any(self.knowledge_node(own_start+8*j)==row for j in range(own_count)):
                    raise core.SourceUnavailable('Reciprocal node not in selected FOW owner vector')
                return core._signed(self.u8(row+8),8)
            return 0
    return UsedReciprocalSource
