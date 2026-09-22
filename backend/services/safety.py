"""Crisis messages: recognised on the server, before any LLM call.

The persona rule in prompts/persona.md asks the model not to read the cards for
a person who writes that they do not want to live, but a live test showed a
smaller model ignoring it and giving a normal reading. This check is the first,
deterministic layer; the persona rule stays as the second one.
"""
import re

# The same numbers as prompts/persona.md (tests/test_safety.py keeps them in sync).
CRISIS_REPLY = (
    "Мне очень жаль, что вам сейчас так тяжело, и хорошо, что вы об этом написали: это важно. "
    "С этим не нужно справляться в одиночку: поговорите с близким человеком "
    "или позвоните туда, где выслушают и помогут прямо сейчас. "
    "Телефон психологической помощи МЧС России: +7 495 989-50-50, "
    "детский телефон доверия для подростков и родителей: 8-800-2000-122 (бесплатно). "
    "Если есть непосредственная опасность, звоните 112."
)

# --- the phrase list ------------------------------------------------------------
#
# Tradeoff: a false positive shows a caring message instead of a tarot reading;
# a false negative sends a person in crisis a tarot reading. When a phrase is
# ambiguous, it is caught.
#
# Every pattern runs over _normalise(text): lower case, "ё" as "е", words kept
# apart by one space, or by "|" where the gap held punctuation, an emoji or a
# line break. A space in a pattern matches either gap ("не хочу... жить" is
# caught); "\x20" matches a plain space only. The checks for where or with whom
# to live use "\x20", so they stay inside one clause: "Не хочу жить. С мужем
# ссоримся" is a crisis, "не хочу жить с мужем" is not.
#
# Decisions for ambiguous phrasing:
# * "не хочу жить с мужем / с родителями / в этом городе / у свекрови / вместе /
#   одна / здесь / прошлым / ради других / от зарплаты до зарплаты ..." is about
#   where, with whom or how to live: NOT a crisis. The words right after "жить"
#   that mean this are _LIVING_ARRANGEMENT; "больше", "дальше", "уже", "вообще"
#   may stand between ("не хочу жить больше с ним").
# * The reversed order is the same: "с мужем жить не хочу", "в этом городе жить
#   не хочется", "так жить не хочу" are consumed by _NOT_CRISIS_PATTERNS before
#   the crisis patterns see their "жить не хочу". Only inside one clause:
#   "Расстались с ним, жить не хочу" is a crisis; without the comma it is not.
# * "не хочу жить так / как ..." asks how to live, not whether to: NOT a crisis,
#   and "не хочу больше так жить" is not caught either. "не хочу жить, как все"
#   compares (Russian needs the comma there), "не хочу жить, как мне быть" asks
#   for help and IS a crisis. "не хочу жить, так плохо" and "так как он ушёл"
#   (because) ARE a crisis; so is "не хочу жить так как мои родители" typed
#   without the comma.
# * "не хочу жить без него / без мамы" IS a crisis: "без" a person says that
#   life itself is not wanted, and despair after a breakup or a loss is exactly
#   when a reading must not be given. "без любви / денег / детей / работы" asks
#   how to live: NOT a crisis.
# * "не хочу жить с этим / с этой болью" and "в этом мире / в этом аду / на
#   этом свете / на этой земле" ARE a crisis, despite the "с" / "в" / "на"
#   (_LIFE_ITSELF); "с этим человеком" is not.
# * A mention of suicide anywhere counts, a series or a book title included
#   ("сериал про суицид"): excluding it is not cheap, and a false positive only
#   shows the caring message. So do "мысли о смерти" and "причинить себе вред"
#   even after "не" ("как не причинить себе вред"). "Смерть" and "Повешенный"
#   as card names, "убить время", "умереть от смеха", "умираю от любопытства",
#   "не хочу умереть", "умереть в один день", "уйти из жизни бывшего" and a
#   third person ("он не хочет жить вместе") are not crisis messages.

# "хочу" and "хочется" with the usual typos: "хачу", "хочеться".
_WANT = r"(?:х[оа]чу|хочеть?ся)"
# не хочу, нехочу, не хочется, не очень хочется, не хотелось бы, неохота
_DONT_WANT = rf"не ?(?:(?:очень|особо|особенно|сильно) )?(?:{_WANT}|хотелось бы|охота)"
_LIVE = r"ж[иы]ть"
# Fillers allowed around the verb: "не хочу больше жить", "не хочу я жить".
_FILLER = r"(?: (?:больше|дальше|уже|вообще|совсем|просто|я|мне|сейчас|теперь))*"

# After "с", "в" or "на" these words keep "жить" about life itself.
_LIFE_ITSELF = (
    r"(?:этим(?! (?:человеком|мужчиной|мужиком|парнем|мужем|соседом))"
    r"|(?:\w+ )?(?:болью|тоской|пустотой|виной|грузом)"
    r"|(?:этом |таком )?(?:аду|кошмаре)"
    r"|(?:этом |том |белом )?(?:мире|свете)"
    r"|(?:этой )?(?:земле|планете)"
    r")\b"
)

# Right after "жить": where, with whom or how to live.
_LIVING_ARRANGEMENT = (
    rf"(?:со?|во?|на)\b(?! {_LIFE_ITSELF})"
    r"|без (?:любви|денег|детей|ребенка|семьи|работы|жилья|квартиры|отношений|секса)\b"
    r"|(?:у|по|под|при|за|от|для|ради|среди|между|возле|около|рядом|вместе|отдельно|раздельно"
    r"|порознь|одна|один|одной|одному|вдвоем|здесь|тут|там|прошлым|чужой|чужую|чужими"
    r"|бедно|скучно|серо|скромно|впроголодь|вечно)\b"
    # "так, как живут родители"; but "так как" (because) and "так плохо" stay a crisis
    r"|так\b(?!\x20(?:как|плохо|тяжело|больно|страшно|одиноко|пусто|устала?|надоело|все)\b)"
)
# "как все", "как раньше", "как мои родители", with a comma or without one.
_LIKE = r"как\b(?! (?:мне|быть|дальше|жить|теперь|же|пережить|справиться|это|так)\b)"
_NOT_ABOUT_ARRANGEMENT = (
    rf"(?!(?:\x20(?:больше|дальше|уже|вообще))*(?:\x20(?:{_LIVING_ARRANGEMENT})| {_LIKE}))"
)

# Before "жить" in the reversed order: "с мужем", "в этом городе", "так".
_DETERMINER = (
    r"(?:этом|этой|этих|том|той|таком|такой|моем|моей|моих|нашем|нашей|его|ее|их"
    r"|своем|своей|чужом|чужой|одном|одной|съемной|съемном)"
)
_ARRANGED_BEFORE = (
    rf"(?:(?:со?|во?|на)\x20(?!{_LIFE_ITSELF})"
    rf"|(?:у|при|под|за|от|для|ради|среди|возле|около|рядом с|вместе с)\x20)"
    rf"(?:{_DETERMINER}\x20)?\w+"
    r"|так|здесь|тут|там|вместе|отдельно|одна|один"
)
_NOT_CRISIS_PATTERNS = (
    rf"\b(?:{_ARRANGED_BEFORE})(?:\x20(?:больше|уже|вообще|совсем|просто|я|мне|сейчас|теперь))*"
    rf"\x20{_LIVE}{_FILLER} (?:{_DONT_WANT}|надоело|устала?)\b",
)

# Whose life one leaves: "уйти из жизни бывшего" is about a relationship.
_SOMEONE = (
    r"(?:мужа|жены|бывш\w*|парня|девушки|человека|семьи|любим\w*|сына|дочери|мамы|папы|матери"
    r"|отца|родителей|детей|ребенка|друга|подруги|него|нее|его|ее|их)"
)

_CRISIS_PATTERNS = (
    # не хочу жить, не хочется жить, не хочу больше жить, не хочу жить дальше, неохота жить
    rf"\b{_DONT_WANT}{_FILLER} {_LIVE}\b{_NOT_ABOUT_ARRANGEMENT}",
    # жить не хочу, жить не хочется, жить больше не хочу, жить неохота
    rf"(?<!\bх[оа]чу )\b{_LIVE}{_FILLER} {_DONT_WANT}\b{_NOT_ABOUT_ARRANGEMENT}",
    # устала жить, надоело жить, жить надоело
    rf"\b(?:устала?|надоело) {_LIVE}\b{_NOT_ABOUT_ARRANGEMENT}",
    rf"\b{_LIVE}{_FILLER} (?:надоело|устала?)\b{_NOT_ABOUT_ARRANGEMENT}",
    rf"\b(?:не могу больше|больше не могу|нет сил|нет больше сил|не осталось сил){_FILLER} {_LIVE}\b"
    rf"{_NOT_ABOUT_ARRANGEMENT}",
    # нет смысла жить, не вижу смысла в жизни, незачем жить, зачем мне жить дальше
    rf"\b(?:нет|не вижу|не осталось|потерял[аи]?) (?:никакого |больше )?смысла"
    rf" (?:{_LIVE}\b{_NOT_ABOUT_ARRANGEMENT}|в жизни\b)",
    rf"\b(?:незачем|не для чего|не ради чего|зачем(?: мне)?(?: вообще)?) {_LIVE}\b{_NOT_ABOUT_ARRANGEMENT}",
    rf"\b(?:смысла|сил) {_LIVE} (?:больше |уже )?нет\b",
    r"\bв (?:моей |этой )?жизни (?:больше |уже )?нет (?:никакого )?смысла\b",
    r"\bжизнь (?:потеряла (?:всякий )?смысл|не имеет (?:никакого )?смысла|бессмысленна)",
    rf"\b{_DONT_WANT}{_FILLER} существовать\b",
    # "не хочу больше просыпаться", but not "не хочу просыпаться рано"
    rf"\b{_DONT_WANT}{_FILLER} просыпаться\b(?!\x20\w)",
    r"\b(?:уснуть|заснуть|усну|засну) и не (?:проснуться|просыпаться|проснусь)\b",
    # хочу умереть, хочется просто умереть; "не хочу умереть", "умереть от смеха"
    # and "умереть с ним в один день / в старости" are not a crisis
    rf"(?<!\bне )\b(?:{_WANT}|хотела? бы)(?: (?!не\b)\w+)? (?:умереть|умирать|сдохнуть)\b"
    r"(?!(?: \w+){0,2} в (?:один день|старости)| от (?:смеха|счастья|любопытства|стыда))",
    # умереть хочется; "не хочу умереть, хочу жить" is not a crisis
    rf"(?<!\bне хочу )(?<!\bнехочу )(?<!\bне хочется )\b(?:умереть|сдохнуть)"
    rf"\x20(?:(?!не\b)\w+\x20)?{_WANT}\b(?! {_LIVE})",
    r"\bлучше (?:бы? )?(?:умереть|сдохнуть)\b(?! от)",
    # лучше бы меня не было, было бы лучше, если бы меня не было, лучше б я умерла
    r"\bлучше(?: \w+){0,2} (?:бы|б) (?:меня (?:вообще |просто )?не (?:было|стало)"
    r"|я (?:умерла?|сдохла?|не родилась?))\b",
    r"\bвсем(?: \w+){0,2} лучше без меня\b",
    r"\bчтобы? меня не стало\b",
    r"\bмысли о (?:своей )?смерти\b|\bо своей смерти\b",
    r"\bпоконч\w* (?:с собой|с жизнью)\b",  # покончить, покончу, покончила
    r"сам[оа]уби",  # самоубийство, самоубийца
    r"су[иеы]ц[иы]д",  # суицид, суицидальные мысли, "суецид"
    r"\bsuicid",
    r"\bселф ?харм|\bself ?harm",
    r"\b(?:убить|убью|убила|убил|убиваю) себя\b",
    r"(?<!\bне )\b(?:убиться|убьюсь)\b",  # but "как не убиться на гололеде"
    r"\b(?:выпилиться|выпилюсь)\b(?! из)",  # slang; "выпилиться из чата" is not
    r"\b(?:свести|сведу|свела|свел|сводить|свожу) счеты с жизнью\b",
    rf"\b(?:уйти|уйду|ухожу) из жизни\b(?!\x20(?:\w+\x20)?{_SOMEONE}\b)",
    # причинить себе вред, наносить себе порезы, нанести себе телесные повреждения
    r"\b(?:причин|нанос|нанес|нанош)\w* себе (?:\w+ )?(?:вред|боль|порез|увечь|травм|повреж)",
    r"\b(?:по)?(?:резать|режу|резала|резал) (?:себя|себе (?:руки|вены|запястья|ноги)|руки|вены|запястья)\b",
    r"\b(?:вскрыть|вскрою|вскрыла|вскрыл|перерезать|перережу) (?:себе )?вены\b",
    r"\b(?:повеситься|повешусь|повесилась|повесился)\b",
    r"\b(?:вы|с)?прыг\w* (?:из окна|с крыши|с балкона|с моста|с \w+ этажа|под поезд)",
    r"\b(?:выйти|выйду|шагнуть|шагну) (?:в окно|с крыши)\b",
    r"\b(?:выброситься|выброшусь|выбросилась|выбросился) из окна\b",
    r"\b(?:броситься|брошусь|бросилась|бросился|кинуться|кинусь|лечь|лягу) под (?:поезд|машину|электричку)\b",
    r"\bнаглота\w* (?:таблет|снотворн|лекарств|колес)",
    r"\b(?:выпить|выпью|выпила|выпил) (?:все|всю пачку|пачку|горсть|кучу) (?:таблет|снотворн|лекарств)",
    # "сделаю с собой что-нибудь"; "сделать с собой что-то красивое" is not a crisis
    r"\b(?:сделаю с собой что ?(?:то|нибудь)|сделать с собой что ?нибудь|что ?нибудь с собой сделаю)\b",
)


def _alternation(patterns: tuple[str, ...]) -> str:
    return "|".join(f"(?:{pattern})" for pattern in patterns)


# At each position the not-a-crisis phrases are tried first and consumed whole.
_PHRASES_RE = re.compile(
    f"(?P<not_crisis>{_alternation(_NOT_CRISIS_PATTERNS)})|(?P<crisis>{_alternation(_CRISIS_PATTERNS)})"
    .replace(" ", "[ |]")  # a space matches any gap between words, "\x20" a plain one
)


def _normalise(text: str) -> str:
    text = text.lower().replace("ё", "е")
    # One space between words, or "|" where the gap held anything but spaces.
    text = re.sub(r"[\W_]+", lambda gap: " " if not gap.group().strip(" \t\xa0") else "|", text)
    return text.strip(" |")


def is_crisis_message(text: str) -> bool:
    """True when the text says the person does not want to live or may harm themselves."""
    # Redis hands back what json.loads made of the question: "42" comes back as a number.
    if not isinstance(text, str):
        return False
    return any(match.group("crisis") is not None for match in _PHRASES_RE.finditer(_normalise(text)))
