"""Bot Forge marks: the acknowledgement reaction, installed into a Bot's own profile.

A hook runs in whichever profile runs the turn — so a hook living in the profile that *created* a
Bot never fires when the user talks to that Bot. This is the piece that ships with the Bot. It
registers two hooks and no tools: a Bot never gains the ability to create or delete Bots from it.
"""

from . import tapback


def register(ctx):
    marks = tapback.Tapback(ctx, lambda: ctx.get_config("ack_tapback", default=True) is not False)
    ctx.register_hook("pre_llm_call", marks.on_turn_start)
    ctx.register_hook("post_llm_call", marks.on_turn_end)
