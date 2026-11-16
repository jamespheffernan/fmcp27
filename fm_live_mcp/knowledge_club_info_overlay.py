"""Finite source-proven non-scout CLUB-owned INFO kinds, private candidate only.

Package copy of `evidence/knowledge-club-info-next-family-20261109/club_info_overlay.py` (lane codex/continuous-knowledge-20261109, commit 268c3a2, SHA256 87d5d69e4a239011305487444d612ee5b44b2fdb648a9c67e0d7c45f0cf743d4); the code is unchanged.


Every listed slot28 getter is exactly MOV W0,#non31_kind; RET; names alone grant nothing.
Only the existing nonnull-expected-TEAM recent-fanout context is supported.
No immutable source/global catalog is edited and no native function is called.
"""
EXTRA_TYPES={
    0x55c3610:(b'N2db32FAILED_CONTRACT_NEGOTIATION_INFOE',0x181250c,3,bytes.fromhex('60008052c0035fd6')),
    0x55c36d0:(b'N2db45FAILED_INTERMEDIARY_TRANSFER_NEGOTIATION_INFOE',0x1812684,11,bytes.fromhex('60018052c0035fd6')),
    0x55c3790:(b'N2db14MLS_SLOTS_INFOE',0x1814514,24,bytes.fromhex('00038052c0035fd6')),
    0x55c3850:(b'N2db20PLAYER_BUY_BACK_INFOE',0x1803400,7,bytes.fromhex('e0008052c0035fd6')),
    0x55c39d0:(b'N2db16AWARD_BONUS_INFOE',0x18041d4,1,bytes.fromhex('20008052c0035fd6')),
    0x55c3c30:(b'N2db26EPPP_APPEARANCE_MONEY_INFOE',0x1812e94,37,bytes.fromhex('a0048052c0035fd6')),
    0x55c3d10:(b'N2db32SPECIAL_SEASON_TICKET_PRICE_INFOE',0x1813348,35,bytes.fromhex('60048052c0035fd6')),
    0x55c3dd0:(b'N2db13MLS_CLUB_INFOE',0x1813a20,25,bytes.fromhex('20038052c0035fd6')),
    0x55c3e90:(b'N2db34MAX_PLAYERS_ON_LOAN_IN_SEASON_INFOE',0x1810e4c,0,bytes.fromhex('00008052c0035fd6')),
    0x55c3f80:(b'N2db60LONG_TERM_INJURED_PLAYERS_THAT_CAN_BE_REPLACED_IN_SQUAD_INFOE',0x1811154,32,bytes.fromhex('00048052c0035fd6')),
    0x55c4058:(b'N2db36NUMBER_OF_GUEST_PLAYERS_ALLOWED_INFOE',0x1811290,40,bytes.fromhex('00058052c0035fd6')),
    0x55c4130:(b'N2db63YOUNG_PLAYER_MAX_CONTRACT_LENGTH_EXEMPTIONS_USED_IN_SEASON_INFOE',0x18113cc,64,bytes.fromhex('00088052c0035fd6')),
    0x55c4208:(b'N2db48NUMBER_OF_PLAYERS_OVER_AGE_SIGNINGS_ALLOWED_INFOE',0x181156c,59,bytes.fromhex('60078052c0035fd6')),
    0x55c42e0:(b'N2db37FOREIGN_PLAYERS_SIGNED_IN_SEASON_INFOE',0x181171c,63,bytes.fromhex('e0078052c0035fd6')),
    0x55c43b8:(b'N2db59NUMBER_OF_NON_EU_PLAYERS_SIGNED_FROM_ABROAD_PER_SEASON_INFOE',0x18118bc,8,bytes.fromhex('00018052c0035fd6')),
    0x55c4568:(b'N2db57MAX_TRANSFERS_IN_A_SEASON_USING_SQUAD_SELECTION_RULE_INFOE',0x1811a20,49,bytes.fromhex('20068052c0035fd6')),
    0x55c4640:(b'N2db39MAX_TRANSFERS_IN_A_TRANSFER_WINDOW_INFOE',0x1811b74,17,bytes.fromhex('20028052c0035fd6')),
    0x55c4718:(b'N2db68MAX_TRANSFERS_OF_AGE_GROUP_AND_DOMESTICITY_IN_A_TRANSFER_WINDOW_INFOE',0x1811cb8,52,bytes.fromhex('80068052c0035fd6')),
    0x55c48c8:(b'N2db53MAX_TRANSFERS_PER_AGE_GROUP_IN_A_SEASON_TRANSFER_INFOE',0x1811e2c,42,bytes.fromhex('40058052c0035fd6')),
    0x55c49a0:(b'N2db36NUMBER_MONTHS_ON_LOAN_TO_A_CLUB_INFOE',0x1811f70,18,bytes.fromhex('40028052c0035fd6')),
    0x55c4a78:(b'N2db29LOAN_DAYS_USED_IN_SEASON_INFOE',0x18120ac,65,bytes.fromhex('20088052c0035fd6')),
    0x55c4b50:(b'N2db36MAX_PLAYERS_ON_LOAN_FROM_A_TEAM_INFOE',0x18121e8,21,bytes.fromhex('a0028052c0035fd6')),
    0x55c4c28:(b'N2db38MAX_PLAYERS_OUT_ON_LOAN_TO_A_TEAM_INFOE',0x1812324,67,bytes.fromhex('60088052c0035fd6')),
    0x55c4d00:(b'N2db59MAX_PLAYERS_MOVED_BETWEEN_MAIN_CLUB_AND_AFFILIATE_CLUB_INFOE',0x18123cc,54,bytes.fromhex('c0068052c0035fd6')),
    0x55c4e98:(b'N2db27STARTING_PLAYER_RECORD_INFOE',0x18130d8,9,bytes.fromhex('20018052c0035fd6')),
    0x55c4f70:(b'N2db22ARRANGED_FRIENDLY_INFOE',0x1813210,10,bytes.fromhex('40018052c0035fd6')),
    0x55c5060:(b'N2db22CLUB_WAIVER_ORDER_INFOE',0x1813474,15,bytes.fromhex('e0018052c0035fd6')),
    0x55c5330:(b'N2db37PLAYERS_ALLOWED_TO_BE_REGISTERED_INFOE',0x1813e64,28,bytes.fromhex('80038052c0035fd6')),
    0x55c5408:(b'N2db43PLAYERS_NOT_ALLOWED_TO_BE_REREGISTERED_INFOE',0x1814014,57,bytes.fromhex('20078052c0035fd6')),
    0x55c54e0:(b'N2db64LEGACY_NUMBER_OF_NON_EU_PLAYERS_SOLD_TO_CLUB_IN_SAME_NATION_INFOE',0x1814160,43,bytes.fromhex('60058052c0035fd6')),
    0x55c55b8:(b'N2db23BOARD_REQUEST_DATA_INFOE',0x18142a0,29,bytes.fromhex('a0038052c0035fd6')),
    0x55c5780:(b'N2db28PLAYERS_USED_IN_MATCHES_INFOE',0x1814650,41,bytes.fromhex('20058052c0035fd6')),
    0x55c5858:(b'N2db38MAX_PLAYERS_OUT_ON_LOAN_IN_SEASON_INFOE',0x1814784,46,bytes.fromhex('c0058052c0035fd6')),
    0x55c5930:(b'N2db40NATIONAL_TEAM_SQUAD_SELECTION_MONEY_INFOE',0x1814934,47,bytes.fromhex('e0058052c0035fd6')),
    0x55c5a08:(b'N2db60NATIONAL_PLAYERS_SELECTED_IN_MATCH_SQUAD_MATCHDAY_COUNT_INFOE',0x1814a68,48,bytes.fromhex('00068052c0035fd6')),
    0x55c5ae0:(b'N2db55ITALIAN_CLUB_PLAYERS_THAT_CAN_BE_REPLACED_IN_SQUAD_INFOE',0x1814b9c,12,bytes.fromhex('80018052c0035fd6')),
    0x55c5bb8:(b'N2db28REGISTERED_PLAYERS_LIST_INFOE',0x1814c44,58,bytes.fromhex('40078052c0035fd6')),
    0x55c5c90:(b'N2db38CLUB_DEVELOPED_PLAYER_TRANSFERRED_INFOE',0x1814e04,60,bytes.fromhex('80078052c0035fd6')),
    0x55c5d68:(b'N2db30LOCKED_SQUAD_NUMBERS_LIST_INFOE',0x1814fa4,61,bytes.fromhex('a0078052c0035fd6')),
    0x55c5f18:(b'N2db21TRIALIST_MATCHES_INFOE',0x1815190,30,bytes.fromhex('c0038052c0035fd6')),
    0x55c60c8:(b'N2db17SQUAD_REWARD_INFOE',0x181572c,44,bytes.fromhex('80058052c0035fd6')),
    0x55c61a0:(b'N2db37PLAYERS_USED_IN_PREVIOUS_MATCHES_INFOE',0x18158cc,45,bytes.fromhex('a0058052c0035fd6')),
    0x55c6278:(b'N2db26WORK_PERMIT_EXEMPTION_INFOE',0x1815a64,50,bytes.fromhex('40068052c0035fd6')),
    0x55c6350:(b'N2db30PLAYER_MAX_WAGE_EXEMPTION_INFOE',0x1815bec,51,bytes.fromhex('60068052c0035fd6')),
    0x55c6440:(b'N2db45MAX_PLAYERS_ON_SHORT_TERM_LOAN_IN_SEASON_INFOE',0x1815d40,13,bytes.fromhex('a0018052c0035fd6')),
    0x55c6518:(b'N2db44MAX_PLAYERS_ON_LONG_TERM_LOAN_IN_SEASON_INFOE',0x1815e6c,14,bytes.fromhex('c0018052c0035fd6')),
    0x55c65f0:(b'N2db42MAX_OVER_21_PLAYERS_ON_LOAN_IN_SEASON_INFOE',0x1815f98,2,bytes.fromhex('40008052c0035fd6')),
    0x55c66c8:(b'N2db42MAX_OVER_23_PLAYERS_ON_LOAN_IN_SEASON_INFOE',0x18160c4,19,bytes.fromhex('60028052c0035fd6')),
    0x55c67a0:(b'N2db43MAX_UNDER_23_PLAYERS_ON_LOAN_IN_SEASON_INFOE',0x18161f0,20,bytes.fromhex('80028052c0035fd6')),
    0x55c6878:(b'N2db44MAX_OVER_23_PLAYERS_ON_LOAN_FROM_A_TEAM_INFOE',0x181631c,56,bytes.fromhex('00078052c0035fd6')),
    0x55c6950:(b'N2db18EXTERNAL_CLUB_INFOE',0x1816394,33,bytes.fromhex('20048052c0035fd6')),
    0x55c6a28:(b'N2db40MAX_WORK_EXPERIENCE_LOANS_IN_SEASON_INFOE',0x18164e0,66,bytes.fromhex('40088052c0035fd6')),
    0x55c6bd8:(b'N2db38PROCESS_BANKRUPT_CLUB_NEXT_SEASON_INFOE',0x1813b58,27,bytes.fromhex('60038052c0035fd6')),
    0x55c6c98:(b'N2db22CLUB_FFP_SANCTION_INFOE',0x1813c90,36,bytes.fromhex('80048052c0035fd6')),
}

CONSUMER=(0x17db1d8,460,'45cc93d9aee990e2d3bb6edb8e9d32a12d1a5dcd2be5cec957fa104f491013ee')
NATIVE_GUARDS=(CONSUMER,
    (0x181250c,8,'008816324250c06e66ca174f257c933b0d3a7d05ae19334ddb101a72517eaadd'),
    (0x1812684,8,'78583cb90ad13e712ee5163aea9c5efe9cbc3402f4096685a45821db97a1cd2a'),
    (0x1814514,8,'25f632edc3cbd5f092dcb6a86533b912088445e8a3e3405fa54d046a5537cc2d'),
    (0x1803400,8,'6b5eade566e78d8649a397cb7fe17ef26a1b166b9a6810377342a0796be72586'),
    (0x18041d4,8,'5103ba3de080c52a046485f800433848701faa49ab8f60241a80987ca249d7ac'),
    (0x1812e94,8,'9f994e1054a653b123d5ff17333c14762ce6d4ac276ee51422da8528c5dacdc5'),
    (0x1813348,8,'a049ecc402db1b8fd9e51519d61cf92e7114d14ecd398c5066c67e3e55716abe'),
    (0x1813a20,8,'4369487546d15d31dcbe1cc7ff3134d6db1f4c320da42bed88990fa030cd8ae8'),
    (0x1810e4c,8,'2f6110664dbd16b514a0c2c7c8326932a36e85d2f15b91e57ca76efd2c7a625a'),
    (0x1811154,8,'833f1cce2c038760f5c7da6a265b10169d41932e7f3d7f76a1d9fb07c8a6f020'),
    (0x1811290,8,'1e4eaf3091dc637ce530ea3faa9a622e2d1c288bb3777f595084df9999f5aeca'),
    (0x18113cc,8,'96f35ded10588c50f8ea6d8fc0f91008229c5e82a8e0a3ee895ebfe8eadfa34c'),
    (0x181156c,8,'7d40c8cdb6518141ef44e616a678f69a1b260ca1e32198ed2eab06bb40efcac9'),
    (0x181171c,8,'1d38e6fd1390b5e0c3126ccdbe30cd35bab3d5bb2559fa29571428f94900806d'),
    (0x18118bc,8,'d5b79016b9fb751da31585e8fe24a684680be6bc5e71460e2422f620bbe78195'),
    (0x1811a20,8,'3e4aa732b96fb58f88d14be1efdee4c2d3451c4cf3d0ca2caad932d089f7d01e'),
    (0x1811b74,8,'c56baecfc366185dc8c75e403b8ef95a8915c1c345814d4b75876b2a77097277'),
    (0x1811cb8,8,'b0e9d4e809a6ab12eafcd05716cb1d1e3f88b8247bbf82ca28d40d12b5ee8ae5'),
    (0x1811e2c,8,'4009fea0cfd27dce07fc75f16edea3c268316d4f138bbcd08a766ca0dc0f947d'),
    (0x1811f70,8,'7275bd756a535a850585a3ba8702a2e1926422de27d779c0ee5c3a5ce782d6dd'),
    (0x18120ac,8,'db9a09ae82f1d2215486903f3be242f72c5cbfebb026edc96d685ce8e88ccede'),
    (0x18121e8,8,'342b47b17de91f3b42c722128d54e43a1273f0592ae1ecd9d19121f47a54d974'),
    (0x1812324,8,'b68f805521ceae27bbe05da424e1172b3aa5c599dd1ec307dee47b1a682abab5'),
    (0x18123cc,8,'7a585f1d80f63c2daf80c14d6d9fc8cd83d6a104c33b60e1a48d7b63670ce220'),
    (0x18130d8,8,'7cffe687c758bc2cd950a25a5cf0fffb605cc3561d20b4b0a099f830c104365b'),
    (0x1813210,8,'f2a41acf67c1de0eee5443c8fa2e53019a2650b802e011084b07064fdddf8e82'),
    (0x1813474,8,'fe47d7a16181f369cbe73d0e546796e691abdb56b6757a3ab277e21315425461'),
    (0x1813e64,8,'831444e617233442a94d9499383be0f5ed91284f77d5854abf2e18ca5875dbe4'),
    (0x1814014,8,'3f30815dce02bb866ea8c7e0982862b123430c870c7da8c795673e38842ce0a3'),
    (0x1814160,8,'081c19ee1bdb89e7009fcded221faf85e3761d603e71b727237f1f3eb724236a'),
    (0x18142a0,8,'cf290d8c46a15a670dd9bedaa1f6533acffdb0046b27036cb04c571e8344c363'),
    (0x1814650,8,'fe242a6cce3e5b82e79cee86f675670aa3b9ef158f0b680345648dba5b2b6ddc'),
    (0x1814784,8,'b45514df49a21bddb4016ebad7a3ba6da007a5ae965c0f491e704b3af68f69b1'),
    (0x1814934,8,'3fbfc2463a348fd57d729609992942d8f293274e9711bcc2f1b6b07ac2adecf0'),
    (0x1814a68,8,'0a7bc4ac64a6118d59ac01cec4eb80e854de1b68b50af86557c4ffb1fcfe11ed'),
    (0x1814b9c,8,'2f81b8ca92806467f52c028a8889f581e61fd7fbb047f552b98233e6afd468ac'),
    (0x1814c44,8,'24357369a1134ccab1fc348526ded356fd5b0a974fe8ccc6cb6b17d4319ed5a6'),
    (0x1814e04,8,'819f7d29f35d1e892da3b49f4fc63044f3ff5fdce304b2eb2a6919d832549125'),
    (0x1814fa4,8,'a524669f2e2d714a9360f5a14f30c2bce5c7ce06e7f1e38d1893638b744b9086'),
    (0x1815190,8,'3a8890f6ca88167477be3f907ddedd3a417ed1df5a93f7b1028b1d75d952ef1f'),
    (0x181572c,8,'d5f9e914cdb84b18ef80751f97097c6c7924e71bd3723e540da9df27b07e5b8f'),
    (0x18158cc,8,'64cca734619b32b253a9e43203a085f324fd7ca5978403586ec0e3513a8b7113'),
    (0x1815a64,8,'65b496ac6aa988576027cad3a939c7f869166d333043d1d43a4ef2b37a27282a'),
    (0x1815bec,8,'a67bc11203a3d3671ba3a7094a2992ec61d4e305e6356adc8953059c6e2fc3b6'),
    (0x1815d40,8,'da213f955b8f14a0c0111dc8b2cfb634e53abeb514f662c0fb6f962dbf4e5f3e'),
    (0x1815e6c,8,'479964d8d31378e02d0921c0d7b354379428cd2cc3a8563b37218ba5ca2081f7'),
    (0x1815f98,8,'0becf359e148792c5ed24ca79a91209e5f15e0f015d2a0b9f4d69c2e82d59f3a'),
    (0x18160c4,8,'34b93e543416a5e1500f244faa2d3f8ee2561801ff18cec55166b2f095ab9796'),
    (0x18161f0,8,'92f20bad37febfbee9558cacaf3bd499b6039b6e867e929a86f360042190e77f'),
    (0x181631c,8,'cec06de81883d4a536ba86a650cb5d8a50d8423de7a50cc0580f147d3e7f216e'),
    (0x1816394,8,'e562b180fb723bdd62886ccaeeacf3cfa8ddd6a03d2d6c8d8bd9f51e71dd6ef1'),
    (0x18164e0,8,'be6a88150324722971545e6579084bb5fafdade10a9b3a3947b1150359372a70'),
    (0x1813b58,8,'94472306d462b77f0580f7a9b5ef44faef1d6af29a27774e72fed3a12cecf782'),
    (0x1813c90,8,'26b3fdeff73ac7eac7e22bbd7aead2d51114523df1c39d28782225daacf340e4'),
)


def source_type(approved_source_type,relation):
    if not issubclass(approved_source_type,relation.RelationSource)or CONSUMER not in relation.NATIVE_GUARDS:
        raise ValueError('CLUB INFO overlay requires the pinned original relation source')
    class ClubInfoSource(approved_source_type):
        def _recent_nodes(self,club,team,expected_team):
            # Both reached canonical recent-fanout callers guard these TEAMs
            # nonnull. The original x1=null helper branch has a different
            # handle-return policy and is deliberately outside this overlay.
            if team is None or expected_team is None:
                raise relation.core.SourceUnavailable('CLUB INFO overlay requires the nonnull TEAM caller context')
            if self.entity(club.address,'club')!=club:
                raise relation.core.SourceUnavailable('CLUB INFO canonical owner context changed')
            holder=self.ptr(club.address+0xb0)
            if not holder:
                raise relation.core.SourceUnavailable('Missing owned CLUB node container')
            start,count=self.reader.bounds(holder,8,4096)
            for i in range(count-1,-1,-1):
                row=self.ptr(start+8*i)
                if not row:
                    continue
                table=self.ptr(row)-self.base
                if table in EXTRA_TYPES:
                    name,target,kind,literal=EXTRA_TYPES[table]
                    if self.read(self.base+target,8)!=literal:
                        raise relation.core.SourceUnavailable('CLUB INFO literal kind getter changed')
                elif table in relation.NODE_TYPES:
                    name,target,kind=relation.NODE_TYPES[table]
                else:
                    raise relation.core.SourceUnavailable('Unproved owned CLUB node family')
                relation.prepared_tactics_source._typed(self.read,self.base,row,table,name,0)
                self.route(self.base+table,0x28,target)
                if kind!=31 or self.ptr(row+0x38)!=team.address:
                    continue
                day,year=relation.struct.unpack('<HH',self.read(row+0x50,4))
                if self.days_since_exceeds(year,day,20):
                    return
                resolved=self.resolve_team_handle(row+0x48)
                if resolved is None or resolved==expected_team:
                    return row
            return None
    return ClubInfoSource
