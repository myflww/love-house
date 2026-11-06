"""Content-bearing overlap for automatic recall, never a change to stored text.

Possessives, pointers and question frames can locate a part of a sentence but
cannot by themselves establish its topic. Keep the original query for ranking
and interpretation; only this evidence check masks their shared fragments.
Literal lookups bypass this check and use the actual recorded body instead.
"""
import re

_FRAMES = (
    '我指的是','你指的是','我说的是','你说的是','我的意思是','也就是说','换句话说',
    '为什么','怎么回事','怎么样','是什么','是不是','怎么','如何','为何',
    '我们的','你们的','他们的','她们的','它们的','我的','你的','他的','她的','它的','自己的',
    '我们','你们','他们','她们','它们','这个','那个','这些','那些','这样','那样',
    '的这个','的那个','一下','的话','的是','就是','是的','不是','没有','不要','不能',
    '请问','谢谢','你好','好的','好吧',
)
_FRAME_PATTERN=re.compile('|'.join(re.escape(value) for value in sorted(_FRAMES,key=len,reverse=True)))


def topic_terms(text, encoder):
    # Spaces matter: removing "你的" must not glue its neighbors into a new
    # bigram. Negation remains in the original search/ranking text and records.
    return set(encoder(_FRAME_PATTERN.sub(' ',text)))
