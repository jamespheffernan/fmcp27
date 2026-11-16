"""Independent frozen native layouts for composed prepared-tactic tests."""
import struct
import base64
import zlib

from fm_live_mcp import prepared_tactic_formations as formations

# Frozen native initializer IDs/compact positions from batch09, independent of
# production recognition. High packed bits are irrelevant to this native route.
IDENTIFIERS = bytes.fromhex(
    '2c2b192d2e0a220b233f09061f071b041a271314342021183e1c12281535321d250e0c24100305160817332f3d022a29401e'
    '260f363738393a3b3c4142434445'
)
POSITIONS = bytes.fromhex(
    'f1f4f6fdfe000107080a0bf1f4f6feff000708090a0bf1f4f5f6fafdff0104080af1f4f5f6fe000708090a0bf1f4f5f6feff'
    '0007080a0bf1f4f5f6fdfe000104080af1f4f5f6f9fbfdff01080af1f4f5f6fdfe0001030509f1f4f5f6f8f9fbfc020609f1'
    'f4f5f6f8f9fbfc030509f1f4f5f6fdfe000108090af1f4f5f6fdfeff0001080af1f4f5f6f8f9fbfcfe0009f1f3f4f6f7fafe'
    '0004080af1f3f4f6f7fafe00030509f1f3f4f6f7fafe00020609f1f3f4f6f7fafe0008090af1f3f4f6f7ff030508090af1f3'
    'f4f6f7fafeff000409f1f3f4f6f7fafeff00080af1f3f4f6f7fafdff01080af1f3f4f6f7fafdfe000109f1f3f4f6f7f9fbfd'
    '010409f1f3f4f6f7f9fbfe00080af1f3f4f6f7f9fb0305080af1f3f4f6f7f9fb0206080af1f3f4f6f7fe0003040509f1f3f4'
    'f6f7f9fb03040509f1f3f4f6f7fe0002040609f1f3f4f6f7fa00fd060309f1f3f4f6f7fafe01020509f1f3f4f6f7f9fb0204'
    '0609f1f3f4f6f7fe0007080a0bf1f3f4f6f7feff0004080af1f3f4f6f7feff00030509f1f3f4f6f7feff0008090af1f3f4f6'
    'f7fdfe00010409f1f3f4f6f7fdfe0001080af1f3f4f6f7fe000206080af1f3f4f6f7f9fbfd01080af1f3f4f6f7fdfeff0001'
    '09f1f3f4f6f7f9fbff020609f1f3f4f6f7f9fb02030506f1f3f4f5f6f7fe0008090af1f8f4f5f6fcfe00020906f1f4f5f6f8'
    'fcfeff00080af1f3f4f5f6f7fafe00080af1f4f5f6f8fcfe0004080af1f4f5f6f8fcf9fb04080af1f4f5f6f8fafcfe00080a'
    'f1f3f4f5f6f7fdfe000109f1f4f5f6f8fcfafe000409f1f3f4f6f7f9fbfdff0109f1f3f4f6f7f9fbfdff0104f1f8fcf4f5f6'
    'fafeff0009f1f3f4f5f6f7fdf9fb0109f1f3f4f5f6f7fdf9fb0104f1f8fcf4f5f6fe00030509f1f4f5f6fafd01fe00080af1'
    'f4f5f6fbf90605030209f1f3f4f5f6f7fbf904080af1f3f4f5f6f7fbf9050309f1f3f4f5f6f7fbf9060209f1f3f4f5f6f7fa'
    '00fe080a'
)


# Frozen native renderer bytes, compressed only to keep test evidence compact.
_NAME_NATIVE_BYTES = (
    'c-qxl3wTu3wO;3(WO8OEggnVh^B|~6K#>xKDBPS$kOHDyhpDLby9sJb9w;}ly&7oE1hggwD<jb<v2B8nni)y8mDuD~1gh0w)NAn7'
    'TD>GZ%1nYn%5#t~_h09nNhSe8{F?iH_kMhbwfA0o@3r>7)?Rz<b0*%5_IuB)5?rTOh^|wGlIz5>5ZAFKp{{{72G_tk!Qn3m>pCux'
    '+ar;W_S35Fbs;UD5_&~mc!RGyhI|VIYV9bc59Q5?4teMH*&W{(u2t(h6C7Uj%Ul?$j+4p0yL+9frF)$bkBlb_j{#3;OZU-7=X6U_'
    'i%V20v*IXb+FXjx@;6$$<Lz@B1!LJ3fozRYR6b1tHBx!FOtx-Gu)Svxa=eo4?#0s>O63CD&5GT6K&IFdjOVds7*ng4w}g=GUX;y|'
    'cB@%zsu&zAOejk?kS&TRR^^2>RdD|%mYYcB_5rdD_Kl<RotVdn^_cLO>0x!QP<<@7XOrF9JCl68<|<=cg#sPIpImP(6T(e>BIRU)'
    '@423Qu^6*U*UcUx*j$0~B*E5)@{oS!vUKQTw%e`0#o8E)?&Co^O`!6kg@WxRgHl-r{8j?Lsp?$jvXwe^TSN`JEm)`hG}#spP!40Z'
    '*`Q(eE6iJ_kLg6;I=%d!G#oR=N(d!e1a!YL&>o_-rv>mj2Ff^LYyh7S9iK&^<X~(VmmT5|E@i+)29I%xMBh$bzH)|aFX`o?2n`o5'
    '_mGCissJ8eK_+n6VF3=NG2-wKvaLKm9EZa3#Np8R;lP*%aA-1|i^Gfn4hJ+Gx^sa;#29htCENP1hU1Vvo;d6uKOA-(8p5IbES-bH'
    '(J&o{FEt$KJHR1&j5zEi+m-{vao86&jyQZVemKy9Aso_9o{K|k0EbUB9MZCZ!=y3d@HyGu`*JuAFN`M+ACF^v_%bLy96lF^2Ld>}'
    'ui>Cf1`bJM#9=qt4t+8lhZW<A!+YZxA3h0+4+qc1Avb`-pEVqcl7K_X7;$(P@;?}kL)LiW@YXoShxdcx!=7_-_{N~)uua3k9t|8O'
    'j}eDIk!{-B!*S>{j3W-Ok7ImzJ19Q<<y;)L1#oE9aA-0Chs(!^!+#=wcw;yYE#ry9)^UsvZv@4M56{J+Du6?ao<E4dA$yEC{2uwk'
    'Yr}C^H3|+T!*DPT;*d2A2jdV9TP}>lLafyrgo6<{ln6#s$p{?YRppz??5~l{t(TiR$kwZu12|X$IJ}_e56BUdk-z$@1lJ`@{i4gC'
    'ikud*W#}pI6mIdDsa@VMIR$yH)wO!fgPgl(0kgczsQfGFWIEdzJxwr~8*`~VGYoRl?A8+WHHFx%Pl4Ww=dg`FJnR)6UlB!qUAgkX'
    '7Gp$RIAnxF#!0i%-Xx@cs>;OL;~}#UYsv#A(|}PP?64Tv6ao8M1Lfqw4m<Tbz_r{joyu=QKbdN*3hI*}?;1Se0>#FQcI#rav8*KS'
    '3%t8A7mu;SE_s(y`Emn~-C&);d|=arHRW;aWIl9Q9?JZORoybVPZshG+zs-sr1EOeOlq=D)@6jF&woJnNh#cY724tiyR{mW$0w?E'
    'tu<by)z&zs`kJLc8F-k5h^Sh=TS#U%+twu8tr7Yh%$EXXjFXK@loZ5Eg`c=EHY=_+iSG=Bp~)2ru<^`Pe5s+-?|~n93KXB}I|bys'
    'Rn^tx<~f+2kc@5_KIRwYQcqZ8lHU+saV(}LsnGz;F;<RzROM|(IR|5BVw~TUP+<qAo_NLAD9L?yf#>`#wM_%BccS9kB$+y|@#k-B'
    'Hju+O@X$v_FSUBnceY^aH2N(Y^8~psv%03id-S2-r%J{?Bb|COW=3tpOo6uI4!VJG2VH*Rp^uKddeC_qcU0aRv5?L8swDXAo#wc@'
    '1?HGKPdxcpZnu==J_@-#QjB}Al<0mx!B8I)G?&(%;Ers?d=tqhVjiY7_inVpmKD4{f)DsjaTRvPYpRadRPy<g61BGJdfRlgnNljM'
    'xh+p`%Ol@$Dc=1fqHCF!V*c&u!+UVMDY;^~z%-$v33WTxA%m}g8q|Jq70oD9Tul<|RmA*-YgN6rGwv8$GsR)$vVd|cHO<;Cnk)FO'
    'DPRoGu^eT_NC4$IszDQuo^^VzC~(aN*0HdKonw!I`fGmH*pL`QU8j>3-$F@gPbFg+`}Q3%<j6%k*3)nC`)wYx;`62|KDO0b=zYx%'
    ')aFH;VEfnTcCGy!cEvos=zF_h?93Wr+q_`gio<PNsoORj^I0I<!?H;3W31VpY{!3t9T!N6bsor#(`~=d9IM&hOum3ls{NCdK|9}c'
    'Ui&AyH*AH>WZnLt9%)jxw?K4U8z<L&JlW!E6y?4*O=R0?P<*wb&^db`f1@#s9NAcF_NUY;3qq%9z_PJWF!n91u5IXL{}oJqGS)b2'
    'Moq&5;XyL7Mg?o!xm$6`azfo&%$FdDoyV|8pPEl?$72*<K6EUMq<;3LOj6oqiQ4&nLtz^AryJEaAKH9IIlhi{`pa%|bwnt>T@mEN'
    'e%vZTpMbpEv9^y*<ZDK}mJzRI#A}MoNLhHc(VB|0=U&(!<!D(jnp0;`c?WEs1wYA5??_6GqKX~h3z2Cl>5z|l`TJboPt&vX@kQA0'
    'sT@nOPg42p0*zJsCRf<ivFRz%T<6%0`aZ0Q%QPV^#f<jAnm_aV<Aun{DPg*tBJPLSYXK#kIf9awvO`q1rDZauZ5;;S5=v1W25Mge'
    'TU1Sle|Gw9CX7D{|LKOkyW$P?-LUa%n48bMma~3@T>I{4Q9rq&z?CV*_sOuO9JS-~T@$h9P`UGZw0RNlywk;8#=#}U&)z51G(1}%'
    'c6DP9_rPDKp#2xSLhDZ>w$w;Tov9Y;KOreTK8w63mG<6vOS@;5rF|hV%@$;HA=YC7Z_#um>*t6qS78rV2@$1-Ag2(tR4`@Ng|2T{'
    'Jj;^Rh<aIQUBh}|LiQpdJbOFp_oM!pVfM9V?Ek5V^*0J;lNsk<9ri!x5QT!dw2$XP%<q-zl6t3#x!IwV<Bb>EyN@c{dSWcwC^J2!'
    'J4V=c41V3SQSt44Vu`Dm#Lf_`-#%G%+!smptg{!oXF_KWkDX~5HdY(AblA8ejN^R3TZR4JsQCPA$md;$SojS2dY>a7+tbAFzc9B!'
    'FLO-tL&qu;_4mdDYs6LdiRVZ?<NKF`@;fy?i~6SK=K>$oB7vfNuMl&45nBrdZCr1Ln9Jk%T^^6?3FWiL($4-V;;A9Z>4yHIkdY!L'
    'OitnTNRiW0Bsn9+yUfyF3x3a1%eE=trzcEFxoh_1l=RsdDN0&;ifpM(s!gz4ALHE1Qrlocne#B&NKuD?VNFR^Te0P_hU${y*BKvs'
    'N#^TvqTOnYf*)CG8jMNEd!n_m)g>jT7`GDOHidB$<hp3aoAClp9^mBtOlhx;r5q3ZX8|ZdrykgD??>?Y1nfW5EeYu<G&?;-*f1r9'
    'pkrtZ^4k}0a$PBy`?|6A-WQj+u0q^tLOC3M{xW2}k7qk#cgrJ<4SvwCL7#x%Tn&70!Ncc{0e*Ekd~$i^$~F<@$tdTMSjy*A9!*r~'
    'dYotQ&Ay(qep}p#Gi9$d!MzVT!#(qqwnj2nTxM`2HBxv*X!IkX6H7xQnHoy>$2^jhM<Hd(1hVCaAiiO)UhGBII|q92K#ct+jC@Ct'
    'mmHU3J5L~v#v_J)W3KOH|H=|#>vDG%w$)+}WwDNuu`~_)>P*JXu0X!A3FrP5(5q*a;#(^TowuDCiq)pyoExiCg-Lza&2TnchnU+@'
    'LPt1eT24On(PzIq=<Ip!CKt!j1(<_<kz<Dkape-k?Iby=?iXgcbCa59B)DIjWT<DEo(B})siPBIrym%K#esQG{QjWx%>A(UXIkv?'
    'd`9gatX;sm^2pdXJCeGv_d44}xlTLp64dkQS<Ef-d53+){(-T#curFL{Wxzq2GvJXS8Fsm5C?zv<_W*;DDt@zs}vW<RgQDT0_AWl'
    '^UlP6LC(y1pdWoWzV1`c7~Y>^uDUOeLMLFY%9@^^+iap)EVJ0e@x;=OxN=J&_M8Xj&}8@|?=SXK-d_^x83`FF`Pf4ed{jxxNO=MF'
    ';aIbh#6Hg3`5k&6_Rn3_9dj&m5^lbce)#Jv$=uljKYdvD)h+PRM)=3$4>vaa9KJdo`u!^&2j_b5&m7oZd9buC6}}c~*pQS8Upo->'
    '2xvs<W$?LxKc~Xyy5VyNkc0mnIdmSG`}jP22Y%|u*cgoUW9-qWji3>wGozWtmL81Rh`GYb_@4EG?x%bYEfgm7S<d)vj8h2Kp~gc='
    'atGpNAWnL)K1vrIi4(EMtF)NNcxK{0<VhAPJsJ6`9XQT$T;#Le3#_@!cbXnPM|7;sj5pfu+GJUsiFP$EAdc+??iY#+2Y|EprCVG#'
    '!N)l+Fy@C|Uh29}2=Dv=7;{|M1DxL<Lrh4oENugB6_c^2^MI8Yy*7zsf*83rNkX3tHC9NaJuz#Ov^Ws%t`fpkoW~juiiDwfpy3>$'
    ';;iB*hz_Azbo}k@(0VK5bVYtHV-#XkRu>^&a2(IpF&gwq#B|1Jbe~*$9-n;g|G!VZ8swA9be~)r@JY$>qX?>3&m5dReC}x9ro>#&'
    '68PzjXkUu6yDG%hEeQ?*Ia70~$N3TB*MrgXeYY8CE4TMxu9gt^_EgP}dw^lHnja;&cdmWHx*6-t>F_$aZ#w2bUEy(hGLW+(#(J07'
    '+mUP58AJH2q)N!uV&M{M{}E(tUpMJg^SayGFz<|R?2j7cw{de7-{S3mds>ziAMQJSML75FE~5>1@0jaof?Vw^vPZ9d!RzGyvSmST'
    'O%&xc?-RS2f4JG}Y+h$Og|^o9z$vhXpYR%>SMm2~>t5)wM<kz+PL6JAlDqz=9_JS#{0;YI&-FNajI^~G@tpUrXCh+aEXCJ6QNx4R'
    'xO0qa^vu*S<2+ftiz9Ejo6EDbc0tsz^cDz?Gz&SFukoljZbn;kna9~IEjxv~`&Np=oeXQ1$-`KwdGf3h@O3++&w9pM4Lj_9$Lkyo'
    '*As6H;i^QRAJ=I?xE4na;krr36>Y8SfNSw=;B&pcj@jxrTNRttW5j0AhjiVayNK@Z1nIuxJLlJZ;Q1llJy#FuUaISkw$?`lifvxE'
    '>=g3Ft<b59bI&XxyR8{=RqXE;yA}d_+-G6~Yr5fo$=(N657~R#MeO~@;&bhN>qRhI9gNwe^JDf(5M~{*LzrC}z$}(pU!;p;b_TIy'
    'CNK;Bc0TJA?qZ-n(dp|tJ)_e(KAo@A*L8YEr*ls0e4V}yIyC=UYpOcWTI)SJeO{;gbvnhT^L6^XPWS6{%4wai)8|!MJ@{=t?37kt'
    'tkd;6eNU(1KAo@A^*Vh|r{Vg1i*>plH1O^(J@9)3lqUz3GlI%fg36Z#l`jt}UlCN!3@T>@m9zOShO!CesUzMwI)Z)|QHJ`H{|D--'
    't|5H))#~hf&ARWgub<EV?u7p}ue<ev`=@V(XYh==rF@M0S&whac@JN&?PrPi@IHMHSCivdrM`#JcD<^D?SeYI3mtfDaNPUB+xi}s'
    'Vox<ox1O_yYqtgMVKHbA?;F~~+n)=Hd${K|0}tj;d(j)fq?PaH&C>VI-NTTp>Mu!MX4YS_o#MO1h1ReMYv8$G|Fzf2@7?*mKkrBN'
    '&M}L8*PVo~qb-ZSVW9rg5%oWgsQX6L)tC`f|M7_Wt0U_DBkI$A!|V5ssK12z#bVj663v%J!(kcYfH=7tIPkmm1yiWibA{$F)uBT<'
    'Qng#lk^25Tlq3D_-~ag>Nec3dBILLQWprd@Y|jnyiyFgFZ2!$~^c=}RtvRqE=Q*-W*9LT6-k|CHMv%@AkAu#izCNTgWu9N>@F1P#'
    '%ZGHX)OF6hoLXm$;S9fR3^x4x4>cPaVZ%HrzK?bFh{<)*&ce36xTE!8F2>`7H$&^2?@)62T_yiki*d-5&dno5<Zp|3pXoSSE_GOY'
    'fa6Nw`0O1!a#>co`mPIWb%v_>Xr`devwdCcDRoa{t|Q0`ILGI?=koUf=3(r!`-aAs7{7RWv{>^p)^<N^!E*%Lq8Ql5!WQ@Iw&3^O'
    '{9gBbws1Y`bruK572Ot-0{$aVYq-8%8G7^k6#_oN@tWla?9+iVk8k-E{0eK|fj%Sku7=(xIrlazK2eD0_bDH0@9*Q?n}2)Id763g'
    '%u5R5CAk~G>v>u6^?={=D(*Ia;6B1&pC_5$sPl0b^1L{l{}}V1(D@s|cMj*TWqy^;=l3O#4(G3C{wkf%?|mK^&aYs8q0YY>{1wCb'
    'rOaQV^KmcpEE~?h3w(b;m}6kgeAlrhH@HqLo98-JSl~LnBHwjpmBr=FcxUAfsqoW5-*f-kx*Wdu{#!$Pc;l*neh(k`<M8w7e14Ps'
    '?1=M7_nVp*yn*vkJC821hgTF|d=DT0fwqSe;8RU!gY(0O)tut#<67>><<Eo4i6@52w*{4*LFG?_%5f)$%C?~L#-Q@<pmNkH?VPz-'
    '-f|Vz_$l;Wbma4=`CIh@&;<UjQ9!;MQ0DiqO{H{%ni3rek%oGD{%np~-;v-*d+DIF=)e3MNWolaOGn$YTL(VOCvqI0Xs8d2n}BhQ'
    'VHDPXHRepCw2%3_Nr3O4sC_%RviI|+Io{0C<!7Oui}Dqqm*cq%&qCC{kB8r5&Bw#vd*|V~70)rusor7a^VkY!)MKy}=M0?Ja-6(&'
    'a14AxIL{cwlAmG>e=Fs@mGfA}gY(?$@LaBs=eYTcUwWOKJ9A#m-zWKdQwp9-^*+3ws{-=igB|ce{wAM1*mmowV)0xZc0z|cp+mU('
    'J%eH=s^8uDJ0!&>>Ns%we|tZF`b#`QKqvU*{m_Zy_-AO3(Azog;chuB?(sL>0?06^?{z4)6a7W?y}LHXldSoF4^#8-xNv97L8oV;'
    '&Sx4woNsFxJuWV889gq}YZ*N*&S@DvF6Ok19v7#zj2;)Kw2U4XF9E+>igjNWVW|HpaQg|KHF*5%gsv0IB*e-P*T9-k*8uYMW0K%z'
    'zfVmN%HfALl&@(mp(9O*cOHoxn=QXoW2VsVb+&R_veF)if6a(zlMw$de?^Obd-&WmsPRwD$Gb5;5dZFc8gVX=cZE=n=Q&dOyEb{9'
    '$6+7#+v5_q#kfD+<#+OYL_6koOZK_^O`H2}zJnZlG44&w$=@L7p71*Z^VE6$&Kgni@$V^81!EsUj|;`etL{L|N52|T`+j~rO!0k!'
    'zRl6p#W}kyWVMOvzOwJ;Ia7tWKD&6~`I0c-Q=+Eh9EaCgB~p2ZY`5MMy<l~BSYy(_nj3)mJe*GjF4(}qXHx4~|JJ7H;d2RR{kAa7'
    '^|jw0?-}rKO&cj|z;E;44&A}mzVVVH&B13`jC-nNsP{`^*O^r!&OZs~U<l-eLaqU}4s#8>DLD9DXO>J|CPC_42@3nV`y`Y5m=x|t'
    '9O+!d--U3W+k!RiGm?$VybtsF+xrCSS4?P&qW&T?XdLx-M}RJ;{zZ{w+aF8UrV2tIe~&U7$x(&!jxg=-2GsWknBy>LpFov2f}f@L'
    'X@Z>&K?nYgPhF@|d2bxWJRvBRUxRKJBFeInhuv3x>CzA88e^UarOLzV-v{8F1r~=Tqnl&RdLwm3iQqxs?lXQ{q%g5AYH#6#X_I&k'
    'Dl_~2wnJD)TE(SHX%5Bgxy)Wx2COHd-xt7g{WtzW8Am`P|AqT(D0}y`-?k6@!@y@Zs5e7!d8S)jM(8&U`jvv-6lYl4Sn_z;q6uUx'
    '!P-oC2G)ERxX%avH^2__V2=XiBl#}aN3}iAvsbdX1eqM8^_`2Hp8N7|c$S;UaaXjqKV}J3&oPhnn96#Xl*+}>qpD<m*&^7eB%dB+'
    'J&N;{2aU|1tUP!l_<1FDWsjLS-=)e@6CP2i478hK(GCnt!TV5O>waBFF_Iio!sxmdLD#)u<l=Evq0~=_97{snr(stQ_E$1|IWdvC'
    '?i{du#IZRp^pd(lLF``$AKCkTi;M3HJyM(-xpMtySZkY!^xqrsH^5{!a@_iphD+*p00Yi@`Mcn8v~ga?<MyI0HC+3hT&j#a3IBF2'
    'mdZu`CVnd&ksaX<x_x;Y<DZ&9<!StTjYulrtoQqqr1zUKVW?kt5MR{!Jwx-T^9S0yg2u&a=d{Wfbbj>^zli9XH0(t#lTO3=cP>N}'
    'ss3Y{MmYBfF`4YB*;R@x1(Xn+C<MK@LkL;~bpTNs{^Jg5_>U)Jh7zewqNMQz6iv6#ALuSZ+@ovgd-NTOr>ki`6`<2og8xmS>wJF|'
    'brid9K`m{N|C*0XnNL*yYagZESebH5szWH3_*a0SyBI}@e0Qy;5A)y3a&%{~wd~f*E`g;`zT%gc*7NDjzoNSlV<_Ej?ZHX)#@Bu)'
    '|JBtAJbQjdZ6`sG-ArxutCc5vGPIlIUhda$Y5ktkoY@@7n#Ihv2M~4nE#SMG=#@o}&+}y?i%5N3C~pSp3ns{Qa&@=^(HIdtrmqKW'
    'oT0FOMbMAhvK;(N9p*D-{nc?dW!1?-;@~*`t0-Rc$gCW@#b*ef&z|M*V0V7RzihzivJiNEOFVtRvOk0W+Nv_83;OgA!*l--o<g#Q'
    'r}WJE@oe~NY<M<oIu}nqiFX0dEZ~`?;n~l)WRAd--`ppUz%x$Alc@>5QK(~@c~ka3h3Ri64q=)F%(4XS7kK>3jNsd!U*Zf$KwSjZ'
    '5>7oD%y4kKaLbF8whjr|2Qb+4V~<nABF4RF1y0ql3*V^zdXEQq#=4tt&ToTmIXs4Mk8|$xIE#@X;MTvjBtpAAx<a+vV{wFbdn}Hi'
    '_7F9@(Z=(yTRf`VIQJVtI%Hi$hqgf-=Cu_E>5#1JAYVj>fXvN7GQ%$-^O-@J^M}bid+)cC`EZcT!#^Bd=0k%r7Yvix^DSkr2$H$`'
    'A~Kf`%3L%|=3C!V=As~(trw9w?;ejcAjkbJ<k+Jn$JIe{p1FveY{(f{Q-D2@k3C}HJ)&kI0bg2h*ndsH#x?&4lozyh91oNiwaGsJ'
    'H9dOPIhw4A`kL}480rVsY<CT)HvsLXB7`8u$-{3d*;@`mx1G(bPn`!h6g`9Wze!!kmI&Cx*vIP#@ltYUVIE$8+6;1hdC0Hg)y%iX'
    'fju=vqV@~A8%6$w2yKlG;nQ?TH~uB*jQJj?sQ+S`<4~1}+GV@l+9*brSO2LdiS@qfyV_gEViU%PP<v_`<yHar0M@k&M#nl~K4YB^'
    'tS!6-73co}`Ai9@'
)


def add_formation_context(m):
    """Seed real native resources; update and return the same memory helper dict.

    Exports formation_metadata, formation_templates, formation_policy_address,
    formation_set_policy(flags|None), formation_set_template(identifier,codes).
    Policy None uses null empty storage; b'' uses allocated empty storage.
    """
    base = m['base']
    for rva, raw in formations.NATIVE_SPANS:
        m['put'](base+rva, raw)
    native = zlib.decompress(base64.b85decode(_NAME_NATIVE_BYTES))
    offset = 0
    for rva, size, _ in formations.NAME_NATIVE_DIGESTS:
        m['put'](base+rva, native[offset:offset+size])
        offset += size
    assert offset == len(native)
    localization = m['allocate'](8)
    cache = m['allocate'](0x348)
    m['q'](base+formations.LOCALIZATION_RVA, localization)
    m['q'](base+formations.NUMERIC_CACHE_RVA, cache)
    digits = {}
    for number in range(1,5):
        digits[number] = m['text'](str(number))
        m['q'](cache+0x320+number*8, digits[number])
    m.update(formation_localization=localization, formation_numeric_cache=cache, formation_digits=digits)
    m['put'](base+formations.METADATA_GUARD_RVA, b'\x01')
    m['put'](base+formations.TEMPLATE_GUARD_RVA, b'\x01')
    metadata = base+formations.METADATA_RVA
    records = m['allocate'](64*24)
    for index, identifier in enumerate(IDENTIFIERS):
        codes = struct.unpack_from('<11b', POSITIONS, index*11)
        packed = struct.pack('<11H', *(code & 63 for code in codes))
        m['put'](metadata+index*24, bytes([identifier, 0])+packed)
        m['put'](records+index*24, packed+b'\x04\x02')
    m['put'](base+formations.TEMPLATE_VECTOR_RVA,
             struct.pack('<QQQ', records, records+64*24, records+64*24))
    policy_address = m['allocate'](4096)

    def set_policy(flags):
        if flags is None:
            bounds = (0, 0, 0)
        else:
            flags = bytes(flags)
            assert len(flags) <= 4096
            m['put'](policy_address, flags)
            bounds = (policy_address, policy_address+len(flags), policy_address+4096)
        m['put'](base+formations.POLICY_RVA, struct.pack('<QQQ', *bounds))

    def set_template(identifier, codes):
        index = IDENTIFIERS.index(identifier)
        assert len(codes) == 11
        m['put'](records+index*24, struct.pack('<11H', *(code & 63 for code in codes))+b'\x04\x02')

    # Independent current native policy: nonzero at these candidate IDs only.
    enabled = {3,4,7,22,27,28,29,30,32,33,35,62,63,64,65,66,67,68,69}
    set_policy(bytes(15 if index in enabled else 0 for index in range(70)))
    m.update(formation_metadata=metadata, formation_templates=records,
             formation_policy_address=policy_address,
             formation_set_policy=set_policy, formation_set_template=set_template,
             formation_identifiers=tuple(IDENTIFIERS))
    return m
